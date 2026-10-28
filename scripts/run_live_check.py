"""Live-typing check (T10): run free-typed messages through the whole system and check every reply and write.

Usage (from the repo root):
    python -m scripts.run_live_check --file tests/dev/live_dev_messages.json

File format: {"messages": [{"id", "text", "expect": {...}}], "global_checks": [...] (text, optional)}.

For EACH message: the demo data and the clock are reset, pipeline.handle() runs, and the database is
compared before / after (new refund rows, new subscriptions). Then:
  - global checks (every message): no crash; reply not empty and <= 120 words; no internal word
    (coordinator, agent, proposal, P-0, R-digits, "sent for checking", tool names); every new refund row is
    allowed by the rules (amount <= paid - refunded and the rule's condition true on the data before the
    run); "approved" only when the decision outcome is approve; no rude word of the user repeated back.
  - the message's own `expect` (see EXPECT_CHECKS below).
One line per message (id, route, outcome, writes, PASS/FAIL, reason), a summary, and the full results in
out/live_check_<file>.json (git-ignored).
"""

import argparse
import json
import re
import sys
import time
import traceback
from pathlib import Path

from callverse import llm, pipeline, trace
from callverse.data import clock, reports
from callverse.data.seed import seed
from callverse.intake import intake
from callverse.kb.policies import check_condition, get_policy
from callverse.slm.writer import warm_up
from callverse.tools.shopnova_tools import get_order, get_refunds, get_tracking
from scripts.quota_check import check_models

OUT_DIR = Path("out")
MAX_WORDS = 120
# T13c (R3): pause between messages with the default (Groq) agents, to stay under the per-minute token limits.
# The local test models (CALLVERSE_AGENTS_SET=local) have no such limit: no pause.
PAUSE_SECONDS_GROQ = 5
TOOL_NAMES = ("get_user", "get_order", "get_tracking", "get_refunds", "get_company_profile", "search_policy",
              "propose_refund", "propose_subscription", "ask_agent")
LEAK_RE = re.compile(r"coordinator|agent|proposal|P-0|\bR-[A-Z]{0,3}-?\d|sent for checking|"
                     + "|".join(TOOL_NAMES), re.IGNORECASE)
RUDE_WORDS = ("idiot", "idiots", "stupid", "useless", "scam", "scammers", "crap", "damn", "shit", "liars",
              "incompetent", "morons", "moron", "garbage", "trash", "pathetic")


def leaks(text: str) -> list[str]:
    return [m.group(0) for m in LEAK_RE.finditer(text or "")]


def refund_rows() -> list[dict]:
    return reports.list_rows("refunds", limit=500)


def subscription_rows() -> list[dict]:
    return reports.list_rows("subscriptions", limit=500)


def refund_allowed(row: dict, before: dict) -> tuple[bool, str]:
    """Is a NEW refund row allowed by the rules, judged on the data BEFORE the run?"""
    order_id = row["order_id"]
    paid = before["paid"].get(order_id)
    refunded = before["refunded"].get(order_id, 0.0)
    if paid is None or row["amount"] > round(paid - refunded, 2) + 1e-9:
        return False, f"refund {row['amount']} > paid {paid} - refunded {refunded}"
    rule = get_policy(row["rule_id"]) if row.get("rule_id") else None
    if rule is None or not rule.get("condition"):
        return False, f"refund row cites no checkable rule ({row.get('rule_id')})"
    tracking = before["tracking"][order_id]
    facts = {"days_late": tracking["days_late"], "delivered": tracking["delivered"],
             "days_since_delivery": tracking["days_since_delivery"], "amount": row["amount"], "paid": paid,
             "refunded_total": refunded, "proof_received": False}
    try:
        ok = check_condition(rule["condition"], facts)
    except ValueError as e:
        return False, f"rule {row['rule_id']} cannot be checked: {e}"
    return ok, "" if ok else f"rule {row['rule_id']} condition false on the data"


def global_checks(text: str, out: dict, new_refunds: list, before: dict) -> list[str]:
    """Problems found by the global checks (empty list = all passed)."""
    problems = []
    reply = out.get("final_reply") or ""
    words = len(reply.split())
    if not reply.strip():
        problems.append("empty reply")
    if words > MAX_WORDS:
        problems.append(f"reply too long ({words} words)")
    if found := leaks(reply):
        problems.append(f"internal words: {found}")
    for row in new_refunds:
        ok, why = refund_allowed(row, before)
        if not ok:
            problems.append(f"WRONG WRITE: {why}")
    outcome = (out.get("decision") or {}).get("outcome")
    if re.search(r"\bapproved?\b", reply, re.IGNORECASE) and outcome != "approve":
        problems.append(f"says 'approved' but outcome is {outcome}")
    user_rude = {w for w in RUDE_WORDS if re.search(rf"\b{w}\b", text, re.IGNORECASE)}
    echoed = [w for w in user_rude if re.search(rf"\b{w}\b", reply, re.IGNORECASE)]
    if echoed:
        problems.append(f"rude words repeated: {echoed}")
    return problems


def _has(reply: str, phrase: str) -> bool:
    return phrase.lower() in reply.lower()


def expect_checks(expect: dict, out: dict, new_refunds: list, new_subs: list) -> list[str]:
    """Problems against the message's own expectations."""
    reply = out.get("final_reply") or ""
    p = []
    if "refund_rows" in expect and len(new_refunds) != expect["refund_rows"]:
        p.append(f"refund rows {len(new_refunds)} != {expect['refund_rows']}")
    if "refund_rows_max" in expect and len(new_refunds) > expect["refund_rows_max"]:
        p.append(f"refund rows {len(new_refunds)} > max {expect['refund_rows_max']}")
    amounts = [round(r["amount"], 2) for r in new_refunds]
    if "refund_amount" in expect and amounts != [round(expect["refund_amount"], 2)]:
        p.append(f"refund amounts {amounts} != [{expect['refund_amount']}]")
    if "refund_amount_if_any" in expect and any(a != round(expect["refund_amount_if_any"], 2) for a in amounts):
        p.append(f"refund amounts {amounts} != {expect['refund_amount_if_any']}")
    if "refund_order_if_any" in expect and any(r["order_id"] != expect["refund_order_if_any"] for r in new_refunds):
        p.append(f"refund for order {[r['order_id'] for r in new_refunds]} != {expect['refund_order_if_any']}")
    if "if_refund_reply_contains" in expect and new_refunds and not _has(reply, expect["if_refund_reply_contains"]):
        p.append(f"refund written but reply lacks '{expect['if_refund_reply_contains']}'")
    if "subscriptions" in expect and len(new_subs) != expect["subscriptions"]:
        p.append(f"subscriptions {len(new_subs)} != {expect['subscriptions']}")
    if "subscriptions_max" in expect and len(new_subs) > expect["subscriptions_max"]:
        p.append(f"subscriptions {len(new_subs)} > max {expect['subscriptions_max']}")
    if "subscription_event_if_any" in expect and any(s["event"] != expect["subscription_event_if_any"] for s in new_subs):
        p.append(f"subscription events {[s['event'] for s in new_subs]} != {expect['subscription_event_if_any']}")
    if "if_subscription_reply_contains" in expect and new_subs and not _has(reply, expect["if_subscription_reply_contains"]):
        p.append(f"subscription written but reply lacks '{expect['if_subscription_reply_contains']}'")
    if "reply_contains_any" in expect and not any(_has(reply, x) for x in expect["reply_contains_any"]):
        p.append(f"reply has none of {expect['reply_contains_any']}")
    for x in expect.get("reply_not_contains", []):
        if _has(reply, x):
            p.append(f"reply contains '{x}'")
    if "reply_starts_with" in expect and not reply.lower().startswith(expect["reply_starts_with"].lower()):
        p.append(f"reply does not start with '{expect['reply_starts_with']}'")
    return p


def snapshot() -> dict:
    """Data before a run: paid, refunded and tracking per scripted order (for the refund rule check)."""
    data = {"paid": {}, "refunded": {}, "tracking": {}}
    for oid in [o["id"] for o in reports.list_orders(limit=500)]:
        order = get_order(oid)
        if "error" in order:
            continue
        data["paid"][oid] = order["paid"]
        data["refunded"][oid] = get_refunds(oid)["refunded_total"]
        data["tracking"][oid] = get_tracking(oid)
    return data


def pause_seconds() -> int:
    """Seconds to wait between two messages: 5 with the default (Groq) agents set, 0 with the local one."""
    return PAUSE_SECONDS_GROQ if llm.model_set("agents") == "default" else 0


def run_one(message: dict) -> dict:
    """Reset, run one message, check it. Never raises."""
    seed()
    clock.reset()
    before = snapshot()
    refunds_before = {r["id"] for r in refund_rows()}
    subs_before = {s["id"] for s in subscription_rows()}
    start = time.perf_counter()
    try:
        out = pipeline.handle(message["text"])
        error = None
    except Exception as e:  # a crash is a FAIL, never a stop of the whole check
        out, error = {}, f"{type(e).__name__}: {e}"
        trace.log("live_check_crash", "live_check", {"id": message["id"], "error": error,
                                                     "traceback": traceback.format_exc()})
    seconds = round(time.perf_counter() - start, 1)
    new_refunds = [r for r in refund_rows() if r["id"] not in refunds_before]
    new_subs = [s for s in subscription_rows() if s["id"] not in subs_before]

    problems = [f"CRASH: {error}"] if error else []
    if not error:
        problems += global_checks(message["text"], out, new_refunds, before)
        problems += expect_checks(message.get("expect") or {}, out, new_refunds, new_subs)
    return {"id": message["id"], "text": message["text"], "route": (out.get("route") or {}).get("agent"),
            "outcome": (out.get("decision") or {}).get("outcome"), "reply": out.get("final_reply"),
            "reply_source": out.get("reply_source"),
            "refunds": [{"order_id": r["order_id"], "amount": r["amount"], "rule_id": r["rule_id"]} for r in new_refunds],
            "subscriptions": [{"order_id": s["order_id"], "event": s["event"]} for s in new_subs],
            "seconds": seconds, "passed": not problems, "problems": problems}


def abort(path: Path, reason: str, done: int) -> None:
    """Stop the whole run WITHOUT scoring (T10b): an aborted run does not count as the one held-out run."""
    print(f"\nABORTED, NOT SCORED: {reason}. Messages finished before the stop: {done} (results not shown).")
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / f"live_check_{path.stem}_aborted.json").write_text(
        json.dumps({"aborted": True, "reason": reason, "finished_before_stop": done}, indent=1), encoding="utf-8")
    trace.log("live_check_aborted", "live_check", {"reason": reason, "finished_before_stop": done})
    sys.exit(2)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    args = parser.parse_args()
    path = Path(args.file)
    messages = json.loads(path.read_text(encoding="utf-8"))["messages"]

    trace_path = trace.start_run()
    intake.load_models()
    warm = warm_up()
    if not warm["ok"]:
        print(f"Warning: {warm['warning']} ({warm['error']})")

    # T10b quota guard: a daily-limit error (before or during the run) ABORTS the run without scoring,
    # so answers made while the main models were out of quota never count as the result.
    quota = check_models()
    if any(q["status"] == "daily_limit" for q in quota):
        abort(path, f"daily limit before the start: {[q['model'] for q in quota if q['status'] == 'daily_limit']}", 0)

    results = []
    for i, m in enumerate(messages):
        if i > 0:
            time.sleep(pause_seconds())   # not counted in the message's seconds (run_one starts its own timer)
        hits_before = len(llm.DAILY_LIMIT_HITS)
        r = run_one(m)
        if len(llm.DAILY_LIMIT_HITS) > hits_before:
            abort(path, f"daily limit during message {m['id']}: {llm.DAILY_LIMIT_HITS[hits_before:]}", len(results))
        results.append(r)

    for r in results:   # printed only when the run finished (an aborted run shows no scores)
        writes = [f"refund {x['order_id']} {x['amount']}" for x in r["refunds"]] + \
                 [f"subscribe {x['order_id']} {x['event']}" for x in r["subscriptions"]]
        print(f"{r['id']:<5} route {r['route'] or '-'}  {str(r['outcome']):<14} writes {writes or '-'}  "
              f"{'PASS' if r['passed'] else 'FAIL'}  {'; '.join(r['problems'])}  ({r['seconds']} s)")
        print(f"      reply [{r['reply_source']}]: {r['reply']}")

    passed = sum(r["passed"] for r in results)
    crashes = sum(any(p.startswith("CRASH") for p in r["problems"]) for r in results)
    leak_count = sum(any(p.startswith("internal words") for p in r["problems"]) for r in results)
    wrong = sum(any(p.startswith("WRONG WRITE") for p in r["problems"]) for r in results)
    secs = [r["seconds"] for r in results]
    summary = {"file": str(path), "messages": len(results), "passed": passed, "crashes": crashes, "leaks": leak_count,
               "wrong_writes": wrong, "avg_seconds": round(sum(secs) / len(secs), 1) if secs else 0,
               "max_seconds": max(secs) if secs else 0, "trace": str(trace_path)}
    print(f"\nSUMMARY: {passed}/{len(results)} passed · crashes {crashes} · leaks {leak_count} · wrong writes {wrong}"
          f" · avg {summary['avg_seconds']} s · max {summary['max_seconds']} s")
    OUT_DIR.mkdir(exist_ok=True)
    out_path = OUT_DIR / f"live_check_{path.stem}.json"
    out_path.write_text(json.dumps({"summary": summary, "results": results}, indent=1, ensure_ascii=False),
                        encoding="utf-8")
    print(f"Results: {out_path}   Trace: {trace_path}")


if __name__ == "__main__":
    main()
