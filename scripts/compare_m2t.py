"""M2T: compare Dali's fine-tuned model (callverse-m2-v3) as Agent B with the saved Groq runs, message by message.

Usage (from the repo root, after the two m2-v3 runs of scripts/run_t14c.py):
    python -m scripts.compare_m2t

Reads the result files only (no model call): the Groq runs saved in T14c (out/t14c_practice_run1.json,
out/t14c_heldout.json) and the m2-v3 runs (out/m2t_practice.json, out/m2t_dev.json). Also reads each m2-v3 run's
trace file (its path is in the summary) to count Groq calls (must be 0) and Agent B tool problems.
Prints a markdown table (id, expected, Groq got, m2 got, same?, m2 seconds), the totals and the WIN RULE line.

M2T2: `python -m scripts.compare_m2t --m2t2` compares THREE setups on the same 24 messages:
  1 = A local cv-qwen3.5-4b + B Groq (saved T14c runs), 2 = A local + B m2-v3 (M2T runs),
  3 = A m2-v3 + B m2-v3 (out/m2t2_practice.json, out/m2t2_dev.json). It also lists which model each Agent A
  call used (from the traces) and prints the M2T2 WIN RULE line (fixed in tasks/M2T2_all_dali_model.md).

M2T3: `python -m scripts.compare_m2t --m2t3` compares setup L (Agents A + B on cv-qwen3.5-4b) with setup D (A + B on
callverse-m2-v3) on all 60 real messages (5 sets, out/m2t3_L_<set>.json and out/m2t3_D_<set>.json). Wrong write =
the runner's WRONG WRITE or any refund / compensation row or order status change the message's expect does not allow.
Messages without expect (review) count only for crash / leak / wrong write. Agent A's OWN turns (routed to A, not the
"ask A" sub-calls) are listed per message. The saved Groq runs are shown as reference only (older code).
"""

import json
import sys
from collections import Counter
from pathlib import Path

PAIRS = [("practice", "out/t14c_practice_run1.json", "out/m2t_practice.json"),
         ("dev", "out/t14c_heldout.json", "out/m2t_dev.json")]
MESSAGE_FILES = {"practice": "tests/dev/t14c_practice_messages.json", "dev": "tests/data/t14c_heldout_messages.json"}


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def got(r: dict) -> str:
    """What the run did, in short: outcome + rule."""
    return f"{r['outcome']} {r['rule_id'] or ''}".strip()


def has(r: dict, word: str) -> bool:
    """True if one of the message's problems starts with this word (same counting as run_t14c.py)."""
    return any(p.startswith(word) for p in r["problems"])


def trace_counts(trace_path: str) -> dict:
    """From one run's trace: calls to an API model, and Agent B tool problems."""
    counts = {"api_calls": 0, "b_calls": 0, "b_tool_errors": 0, "b_tool_refused": 0, "b_step_limit": 0,
              "b_fallbacks": 0}
    for line in Path(trace_path).read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        step, data = rec["step"], rec.get("data") or {}
        if step == "llm_call":
            if data.get("provider") != "ollama":
                counts["api_calls"] += 1
            if data.get("role") == "agent_b":
                counts["b_calls"] += 1
        elif step == "llm_fallback" and data.get("role") == "agent_b":
            counts["b_fallbacks"] += 1
        elif step == "tool_call" and data.get("agent") == "B" and isinstance(data.get("result"), dict) \
                and "error" in data["result"]:
            counts["b_tool_errors"] += 1
        elif step == "tool_refused" and data.get("agent") == "B":
            counts["b_tool_refused"] += 1
        elif step == "step_limit" and rec.get("actor") == "B":
            counts["b_step_limit"] += 1
    return counts


def p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, round(0.95 * len(ordered)) - 1)]


def main() -> None:
    rows, totals = [], {"groq": {"pass": 0, "ww": 0, "crash": 0, "leak": 0, "secs": []},
                        "m2": {"pass": 0, "ww": 0, "crash": 0, "leak": 0, "secs": []}}
    trace_totals = {}
    for name, groq_file, m2_file in PAIRS:
        expects = {m["id"]: m.get("expect", {}) for m in load(MESSAGE_FILES[name])["messages"]}
        groq = {r["id"]: r for r in load(groq_file)["results"]}
        m2_run = load(m2_file)
        for c, n in trace_counts(m2_run["summary"]["trace"]).items():
            trace_totals[c] = trace_totals.get(c, 0) + n
        for r in m2_run["results"]:
            g = groq[r["id"]]
            e = expects[r["id"]]
            expected = f"{e.get('outcome', '?')} {e.get('rule_id', '')}".strip()
            for key, run in (("groq", g), ("m2", r)):
                t = totals[key]
                t["pass"] += run["passed"]
                t["ww"] += has(run, "WRONG WRITE")
                t["crash"] += has(run, "CRASH")
                t["leak"] += has(run, "internal words")
                t["secs"].append(run["seconds"])
            same = "yes" if (got(g) == got(r) and g["passed"] == r["passed"]) else "NO"
            rows.append(f"| {r['id']} | {expected} | {got(g)} {'PASS' if g['passed'] else 'FAIL'} | "
                        f"{got(r)} {'PASS' if r['passed'] else 'FAIL'} | {same} | {r['seconds']} |")
            if r["problems"]:
                rows.append(f"|  | m2 problems: {'; '.join(r['problems'])} |  |  |  |  |")

    print("| id | expected | Groq got | m2 got | same? | m2 s |\n|---|---|---|---|---|---|")
    print("\n".join(rows))
    print()
    for key in ("groq", "m2"):
        t = totals[key]
        print(f"{key}: expect passes {t['pass']}/{len(t['secs'])} · wrong writes {t['ww']} · crashes {t['crash']} · "
              f"leaks {t['leak']} · avg {sum(t['secs']) / len(t['secs']):.1f} s · p95 {p95(t['secs'])} s")
    print(f"m2 trace: {trace_totals}")
    g, m = totals["groq"], totals["m2"]
    # The win rule exactly as fixed in tasks/M2T_test_dali_model_agent_b.md (API calls are a separate hard limit).
    win = m["crash"] == 0 and m["leak"] == 0 and m["ww"] == 0 and m["pass"] >= g["pass"] - 2
    print(f"API calls in the m2 runs (must be 0): {trace_totals['api_calls']}")
    print(f"WIN RULE (0 crashes, 0 leaks, 0 wrong writes, passes >= {g['pass']} - 2 = {g['pass'] - 2}): {win}")


# --- M2T2: three setups ------------------------------------------------------------------------------------------

SETUPS = {1: {"practice": "out/t14c_practice_run1.json", "dev": "out/t14c_heldout.json"},
          2: {"practice": "out/m2t_practice.json", "dev": "out/m2t_dev.json"},
          3: {"practice": "out/m2t2_practice.json", "dev": "out/m2t2_dev.json"}}


def agent_a_counts(trace_path: str) -> dict:
    """From one run's trace: the model of every LLM call made inside an Agent A turn, Agent A tool problems,
    and the models of the "agents" role (Agent A's own turns, Intake LLM fallback, quota pings)."""
    out = {"a_turns": 0, "a_models": Counter(), "agents_role_models": Counter(), "a_tool_errors": 0,
           "a_tool_refused": 0, "a_step_limit": 0, "api_calls": 0}
    in_a = False
    for line in Path(trace_path).read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        step, actor, data = rec["step"], rec.get("actor"), rec.get("data") or {}
        if step == "agent_start" and actor == "agent_A":
            in_a = True
            out["a_turns"] += 1
        elif step == "final_answer" and actor == "agent_A":
            in_a = False
        elif step == "llm_call":
            if data.get("provider") != "ollama":
                out["api_calls"] += 1
            if in_a:
                out["a_models"][data.get("model")] += 1
            if data.get("role") == "agents":
                out["agents_role_models"][data.get("model")] += 1
        elif step == "tool_call" and data.get("agent") == "A" and isinstance(data.get("result"), dict)                 and "error" in data["result"]:
            out["a_tool_errors"] += 1
        elif step == "tool_refused" and data.get("agent") == "A":
            out["a_tool_refused"] += 1
        elif step == "step_limit" and actor in ("A", "agent_A"):
            out["a_step_limit"] += 1
    return out


def main_m2t2() -> None:
    runs = {}   # setup -> {id: result}
    traces = {}  # setup -> list of trace paths
    for n, files in SETUPS.items():
        runs[n], traces[n] = {}, []
        for name in ("practice", "dev"):
            data = load(files[name])
            runs[n].update({r["id"]: r for r in data["results"]})
            traces[n].append(data["summary"].get("trace"))
    expects = {}
    for name in ("practice", "dev"):
        expects.update({m["id"]: m.get("expect", {}) for m in load(MESSAGE_FILES[name])["messages"]})

    print("| id | expected | setup 1 (A local, B Groq) | setup 2 (A local, B m2) | setup 3 (A m2, B m2) |")
    print("|---|---|---|---|---|")
    for mid in runs[3]:
        e = expects[mid]
        cells = [f"{got(runs[n][mid])} {'PASS' if runs[n][mid]['passed'] else 'FAIL'} "
                 f"{runs[n][mid]['seconds']} s" for n in (1, 2, 3)]
        print(f"| {mid} | {e.get('outcome', '?')} {e.get('rule_id', '')} | " + " | ".join(cells) + " |")
    print()

    totals = {}
    for n in (1, 2, 3):
        res = list(runs[n].values())
        secs = [r["seconds"] for r in res]
        t = {"pass": sum(r["passed"] for r in res), "ww": sum(has(r, "WRONG WRITE") for r in res),
             "crash": sum(has(r, "CRASH") for r in res), "leak": sum(has(r, "internal words") for r in res),
             "avg": round(sum(secs) / len(secs), 1), "p95": p95(secs), "n": len(res)}
        if n in (2, 3):   # setup 1's traces are Groq runs from T14c; only the local runs are checked here
            a = {"a_turns": 0, "a_models": Counter(), "agents_role_models": Counter(), "a_tool_errors": 0,
                 "a_tool_refused": 0, "a_step_limit": 0, "api_calls": 0}
            for tp in traces[n]:
                for k, v in agent_a_counts(tp).items():
                    a[k] = a[k] + v
            t.update(a)
        totals[n] = t
        line = (f"setup {n}: expect passes {t['pass']}/{t['n']} · wrong writes {t['ww']} · crashes {t['crash']} · "
                f"leaks {t['leak']} · avg {t['avg']} s · p95 {t['p95']} s")
        if n in (2, 3):
            line += (f" · Agent A turns {t['a_turns']} (models {dict(t['a_models'])}) · 'agents' role calls "
                     f"{dict(t['agents_role_models'])} · Agent A tool errors/refused/step limit "
                     f"{t['a_tool_errors']}/{t['a_tool_refused']}/{t['a_step_limit']} · Groq/API calls {t['api_calls']}")
        print(line)
    s3 = totals[3]
    # The win rule exactly as fixed in tasks/M2T2_all_dali_model.md (before the run).
    win = (s3["crash"] == 0 and s3["leak"] == 0 and s3["ww"] == 0 and s3["pass"] >= totals[1]["pass"]
           and s3["avg"] <= totals[2]["avg"])
    print(f"WIN RULE (setup 3: 0 crashes, 0 leaks, 0 wrong writes, passes >= {totals[1]['pass']}, "
          f"avg s <= {totals[2]['avg']}): {win}")


# --- M2T3: setup L (all cv-qwen3.5-4b) vs setup D (all callverse-m2-v3) on all 60 real messages ------------------

# (set name, message file, Groq reference run saved earlier or None). The Groq runs are REFERENCE ONLY (older code).
M2T3_SETS = [("decline_practice", "tests/dev/decline_practice_messages.json", "out/decline_check_decline_practice_messages.json"),
             ("decline_heldout", "tests/data/decline_heldout_messages.json", "out/decline_check_decline_heldout_messages.json"),
             ("t14b_practice", "tests/dev/t14b_practice_messages.json", "out/t14b_after.json"),
             ("t14c_practice", "tests/dev/t14c_practice_messages.json", "out/t14c_practice_run1.json"),
             ("t14c_heldout", "tests/data/t14c_heldout_messages.json", "out/t14c_heldout.json")]
# Order statuses that are the order's state BEFORE the run (the scripted orders): a different status after the run
# means the run changed the order. An expected "cancelled" is a write the message asks for, so missing it is a FAIL
# but not a wrong write.
UNCHANGED_STATUSES = ("shipped", "delivered", "processing", "stuck_at_depot")


def m2t3_wrong_writes(r: dict, expect: dict) -> list[str]:
    """Wrong writes as the M2T3 rule defines them: the runner's WRONG WRITE (rule false on the data), PLUS any
    refund / compensation row or order / booking status change that the message's expect does not allow."""
    out = [p for p in r["problems"] if p.startswith("WRONG WRITE")]
    for key, rows in (("refund_rows", r.get("refunds") or []), ("compensation_rows", r.get("compensations") or [])):
        if key in expect and len(rows) > expect[key]:
            out.append(f"{key} {len(rows)} > {expect[key]} allowed")
    if "refund_amount" in expect and r.get("refunds") and \
            [round(a, 2) for a in r["refunds"]] != [round(expect["refund_amount"], 2)]:
        out.append(f"refund {r['refunds']} != allowed {expect['refund_amount']}")
    want = expect.get("order_status")
    if want in UNCHANGED_STATUSES and r.get("order_status") != want:
        out.append(f"order status changed to {r.get('order_status')} (must stay {want})")
    return out


def is_leak(r: dict) -> bool:
    """A leak, counted the same way for both runners: run_live_check's "internal words", or one of the hidden-field
    words of run_t14c.py (card, cash, city, payment, source) found by run_decline_check's reply_must_not_contain."""
    hidden = ("card", "cash", "city", "payment", "source")
    return has(r, "internal words") or any(p.startswith("forbidden word in reply: ") and p.split(": ", 1)[1] in hidden
                                           for p in r["problems"])


def own_a_turns(trace_path: str) -> list[dict]:
    """Per message (split at each clock_reset, one per message): the router's agent, Agent A's OWN turns (not the
    "ask Agent A" sub-calls inside an Agent B turn) and the models of their LLM calls."""
    msgs, in_b, in_a_own = [], False, False
    for line in Path(trace_path).read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        step, actor, data = rec["step"], rec.get("actor"), rec.get("data") or {}
        if step == "clock_reset":
            msgs.append({"route": None, "a_own": 0, "a_models": Counter()})
            in_b = in_a_own = False
        elif not msgs:
            continue
        elif step == "route":
            msgs[-1]["route"] = data.get("agent")
        elif step == "agent_start" and actor == "agent_B":
            in_b = True
        elif step == "final_answer" and actor == "agent_B":
            in_b = False
        elif step == "agent_start" and actor == "agent_A" and not in_b:
            in_a_own = True
            msgs[-1]["a_own"] += 1
        elif step == "final_answer" and actor == "agent_A" and not in_b:
            in_a_own = False
        elif step == "llm_call" and in_a_own:
            msgs[-1]["a_models"][data.get("model")] += 1
    return msgs


def main_m2t3(setups: dict | None = None) -> None:
    """setups: column label -> result file prefix (out/<prefix>_<set>.json). Default: M2T3's L and D.
    With "T" (T14d finish: D re-run on top of T14d's code), the win rule is checked on T against M2T3's L."""
    setups = setups or {"L": "m2t3_L", "D": "m2t3_D"}
    labels = list(setups)
    rows, totals = [], {}
    a_lines = {s: [] for s in labels}
    for setup in labels:
        totals[setup] = {"n": 0, "n_expect": 0, "pass": 0, "ww": 0, "crash": 0, "leak": 0, "secs": [],
                         "api_calls": 0, "a_tool_errors": 0, "a_tool_refused": 0, "a_step_limit": 0,
                         "b_tool_errors": 0, "b_tool_refused": 0, "b_step_limit": 0, "a_own": 0, "a_models": Counter()}
    for name, msg_file, groq_file in M2T3_SETS:
        messages = load(msg_file)["messages"]
        runs = {s: load(f"out/{setups[s]}_{name}.json") for s in labels}
        groq = {r["id"]: r for r in load(groq_file)["results"]} if groq_file and Path(groq_file).exists() else {}
        for s, run in runs.items():
            t, tp = totals[s], run["summary"]["trace"]
            for k, v in trace_counts(tp).items():
                if k in t:
                    t[k] += v
            for k, v in agent_a_counts(tp).items():
                if k in ("a_tool_errors", "a_tool_refused", "a_step_limit"):
                    t[k] += v
            per_msg = own_a_turns(tp)
            for m, info in zip(messages, per_msg):
                if info["a_own"]:
                    t["a_own"] += info["a_own"]
                    t["a_models"].update(info["a_models"])
                    a_lines[s].append(f"{name}/{m['id']} ({dict(info['a_models'])})")
        res = {s: {r["id"]: r for r in runs[s]["results"]} for s in runs}
        for m in messages:
            e = m.get("expect") or {}
            has_expect = bool(e)
            expected = (f"{e.get('outcome', '(no outcome key)')} {e.get('rule_id', '')}".strip()
                        if has_expect else "(no expect: review)")
            cells = []
            for s in labels:
                r, t = res[s][m["id"]], totals[s]
                ww = m2t3_wrong_writes(r, e)
                t["n"] += 1
                t["n_expect"] += has_expect
                t["pass"] += has_expect and r["passed"]
                t["ww"] += bool(ww)
                t["crash"] += has(r, "CRASH")
                t["leak"] += is_leak(r)
                t["secs"].append(r["seconds"])
                mark = ("PASS" if r["passed"] else "FAIL") if has_expect else "n/a"
                cells.append(f"{got(r)} {mark}{' **WW**' if ww else ''}")
                r["_ww"] = ww
            g = groq.get(m["id"])
            gcell = f"{got(g)} {'PASS' if g['passed'] else 'FAIL'}" if g else "-"
            secs = " / ".join(str(res[s][m["id"]]["seconds"]) for s in labels)
            rows.append(f"| {m['id']} | {name} | {expected} | {' | '.join(cells)} | {gcell} | {secs} |")
            for s in labels:
                r = res[s][m["id"]]
                if r["problems"] or r["_ww"]:
                    rows.append(f"|  |  | {s} problems | {'; '.join(r['problems'] + r['_ww'])} |" + "  |" * (len(labels) + 1))

    print(f"| id | set | expected | {' | '.join(s + ' got' for s in labels)} | Groq ref | s ({' / '.join(labels)}) |")
    print("|" + "---|" * (len(labels) + 5))
    print("\n".join(rows))
    print()
    for s in labels:
        t = totals[s]
        print(f"setup {s}: expect passes {t['pass']}/{t['n_expect']} (+{t['n'] - t['n_expect']} without expect) · "
              f"wrong writes {t['ww']} · crashes {t['crash']} · leaks {t['leak']} · "
              f"avg {sum(t['secs']) / len(t['secs']):.2f} s · p95 {p95(t['secs'])} s · "
              f"tool problems A err/refused/step-limit {t['a_tool_errors']}/{t['a_tool_refused']}/{t['a_step_limit']}, "
              f"B {t['b_tool_errors']}/{t['b_tool_refused']}/{t['b_step_limit']} · Groq/API calls {t['api_calls']}")
    for s in labels:
        t = totals[s]
        print(f"setup {s}: Agent A OWN turns {t['a_own']} (models {dict(t['a_models'])}) on: "
              f"{', '.join(a_lines[s]) or 'none'}")
    if "T" in totals:
        # T14d finish win rule (tasks/T14d_finish_with_dali_model.md, fixed before the run): same as M2T3, on T.
        L, T = totals["L"], totals["T"]
        win = T["crash"] == 0 and T["leak"] == 0 and T["ww"] == 0 and T["pass"] >= L["pass"]
        print(f"WIN RULE (T = D on T14d code: 0 crashes, 0 leaks, 0 wrong writes, expect passes {T['pass']} >= "
              f"M2T3 L's {L['pass']}): {win}")
        return
    L, D = totals["L"], totals["D"]
    # The win rule exactly as fixed in tasks/M2T3_dali_model_60_and_switch.md (before the run). Speed is not in it.
    win = D["crash"] == 0 and D["leak"] == 0 and D["ww"] == 0 and D["pass"] >= L["pass"]
    print(f"WIN RULE (D: 0 crashes, 0 leaks, 0 wrong writes, expect passes {D['pass']} >= L's {L['pass']}): {win}")


if __name__ == "__main__":
    if "--t14d" in sys.argv:
        main_m2t3({"L": "m2t3_L", "D": "m2t3_D", "T": "t14d_D"})
    elif "--m2t3" in sys.argv:
        main_m2t3()
    else:
        main_m2t2() if "--m2t2" in sys.argv else main()
