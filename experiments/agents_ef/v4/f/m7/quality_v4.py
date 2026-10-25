"""M7 v4 responsibility 2: quality review of a CLOSED conversation (deterministic checks, no model).

    review_v4(conv) -> V3 review dict, with three changes (everything else is V3's `quality.review`):

1. V3's single `claim_contradicts_data` is split in two different failures:
     claim_false        (high)   a fact the agent claimed CONTRADICTS the platform's data in the same trace
                                 (a tool result, or the facts the Coordinator re-read for that proposal).
     claim_unsupported  (medium) the agent claimed a fact that NO tool had returned TO THAT AGENT RUN before
                                 the claim (the rule "facts come from tools, never from model memory" was broken),
                                 whether or not the value happens to be right. Evidence says if later data agree.
   Why: a guess that happens to be right is still a process failure (next time it may be wrong); a value that
   contradicts the data is a correctness failure. The owner needs to tell them apart.
   Which run: an agent run starts at its `agent_start` line and has no memory of earlier runs (a send-back
   starts a new run). Agent B's facts from Agent A arrive as the `ask_agent` tool result, so they count for B.
   Facts checked: days_late, delivered, paid, refunded_total, days_since_delivery (claimed value None = no claim).
2. reply_leak is V3's check unchanged (the prototype's T08 pattern). A word-boundary variant was tried and
   dropped: its motivating case ("agency") is not matched by V3 either; only substrings such as "reagent" differ.
3. Every flag's evidence refs can be checked against the raw trace lines with verify_refs().
5. (v4.1, after the held-out run) numbers and booleans written as strings by the agent ("8", "false") are
   compared as numbers / booleans: the DEV stress test (m7_stress.py) showed 16/120 false claim_false otherwise.
4. missed_entitlement is not raised when the refund was offered and the client was asked to confirm it
   (outcome ask_user, action refund): V3 counted that as "missed" (false positive found on the dev corpus).

The 14 flag codes after v4: pipeline_error, claim_false, claim_unsupported, cited_missing_rule, sent_back,
escalated, rule_not_searched, agent_answered_without_tools, proposal_malformed, missed_entitlement, reply_leak,
slm_fallback_template, reply_language_mismatch, handover_ignored.
NOT checked (documented limits): claims inside the agent's free text (agent_text never reaches the client by
design; it would need language understanding), and facts outside the five above.
"""

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))          # experiments/agents_ef
from v3.m7 import quality as q3  # noqa: E402
from v4.f.m7.conversations_v4 import line_no  # noqa: E402

CLAIM_KEYS = ("days_late", "delivered", "paid", "refunded_total", "days_since_delivery")
# Which tool result carries which fact (as the agents receive them).
TOOL_FACTS = {"get_tracking": ("days_late", "delivered", "days_since_delivery", "status"),
              "get_order": ("paid", "status"), "get_refunds": ("refunded_total",)}
CODES = ("pipeline_error", "claim_false", "claim_unsupported", "cited_missing_rule", "sent_back", "escalated",
         "rule_not_searched", "agent_answered_without_tools", "proposal_malformed", "missed_entitlement",
         "reply_leak", "slm_fallback_template", "reply_language_mismatch", "handover_ignored")


def norm(v):
    """v4.1: an LLM often writes numbers / booleans as strings in JSON ("8", "59.90", "false"). They are the same
    claim, so they are compared as numbers / booleans (found by the benign-mutation stress test on DEV:
    16 of 120 conversations got a false claim_false). Other strings are left as they are."""
    if isinstance(v, str):
        t = v.strip()
        if t.lower() in ("true", "false"):
            return t.lower() == "true"
        try:
            return int(t) if t.lstrip("-").isdigit() else float(t)
        except ValueError:
            return v
    return v


def same(a, b) -> bool:
    return q3._same(norm(a), norm(b))


def facts_in_result(tool: str, result) -> dict:
    """Facts a tool result gives its caller: {fact: value}."""
    if not isinstance(result, dict) or "error" in result:
        return {}
    if tool == "ask_agent":                                   # Agent A's facts, handed to Agent B
        f = result.get("facts") if isinstance(result.get("facts"), dict) else {}
        return {k: f[k] for k in ("days_late", "delivered", "days_since_delivery", "status") if k in f}
    return {k: result[k] for k in TOOL_FACTS.get(tool, ()) if k in result}


def claims(conv: dict) -> list[dict]:
    """Every fact the agent claimed: {fact, value, ref, line, agent}. Earliest line per (fact, value)."""
    lines = conv.get("lines") or {}
    out = {}

    def agent_after(n):
        """The agent that submitted the proposal logged at line n (the propose_* tool_call that follows it)."""
        for m in sorted(x for x in lines if x > n):
            step, data, _ = lines[m]
            if step == "tool_call" and str(data.get("tool", "")).startswith("propose_"):
                return data.get("agent")
            if step in ("proposal", "proposal_refused", "agent_start"):
                break
        runs = [r for r in conv.get("agent_runs", []) if r["start_line"] < n]
        return runs[-1]["agent"] if runs else None

    def add(facts, ref, agent):
        n = line_no(ref)
        for k in CLAIM_KEYS:
            if isinstance(facts, dict) and k in facts and facts[k] is not None:
                key = (k, str(facts[k]))
                if key not in out or out[key]["line"] > n:
                    out[key] = {"fact": k, "value": facts[k], "ref": ref, "line": n, "agent": agent}

    for p in conv["proposals"]:
        add(p.get("facts_used"), p["ref"], agent_after(line_no(p["ref"])))
    for p in conv["proposal_refusals"]:
        add((p.get("fields") or {}).get("facts_used"), p["ref"], agent_after(line_no(p["ref"])))
    for c in conv["checks"]:
        if c.get("check") == "facts_from_data" and isinstance(c.get("detail"), str) and "agent claimed:" in c["detail"]:
            try:
                f = ast.literal_eval(c["detail"].split("agent claimed:", 1)[1].strip())
            except (ValueError, SyntaxError):
                continue
            n = line_no(c["ref"])
            props = [line_no(p["ref"]) for p in conv["proposals"] if line_no(p["ref"]) < n]
            add(f, c["ref"], agent_after(max(props)) if props else None)
    return sorted(out.values(), key=lambda x: (x["line"], x["fact"]))


def agent_sources(conv: dict, agent: str, before: int) -> dict:
    """Facts returned by tools to `agent` during its run that was active at line `before`: {fact: (value, ref)}
    (latest value wins)."""
    runs = [r["start_line"] for r in conv.get("agent_runs", []) if r["agent"] == agent and r["start_line"] < before]
    start = max(runs) if runs else 0
    src = {}
    for t in conv["tool_calls"]:
        n = line_no(t["ref"])
        if t.get("agent") == agent and start < n < before:
            for k, v in facts_in_result(t.get("tool"), t.get("result")).items():
                src[k] = (v, t["ref"])
    return src


def coordinator_reread_after(conv: dict, n: int) -> dict:
    """Facts the Coordinator re-read itself (facts_from_data check) for the first proposal at or after line n."""
    for c in sorted(conv["checks"], key=lambda c: line_no(c["ref"])):
        if c.get("check") == "facts_from_data" and line_no(c["ref"]) >= n and isinstance(c.get("facts"), dict):
            return {k: (v, c["ref"]) for k, v in c["facts"].items()}
    return {}


def any_tool_before(conv: dict, n: int) -> dict:
    """Facts from any tool call (any agent, Intake) before line n (latest wins)."""
    src = {}
    for t in sorted(conv["tool_calls"], key=lambda t: line_no(t["ref"])):
        if line_no(t["ref"]) < n:
            for k, v in facts_in_result(t.get("tool"), t.get("result")).items():
                src[k] = (v, t["ref"])
    return src


def claim_flags(conv: dict) -> list[dict]:
    flags = []
    for c in claims(conv):
        k, v, n = c["fact"], c["value"], c["line"]
        own = agent_sources(conv, c["agent"], n) if c["agent"] else {}
        later = coordinator_reread_after(conv, n)
        other = any_tool_before(conv, n)
        # the data to compare with: what the agent itself was told; else the Coordinator's re-read; else any tool
        data = own.get(k) or later.get(k) or other.get(k)
        if data is not None and not same(v, data[0]):
            flags.append({"code": "claim_false", "severity": "high",
                          "what": f"agent {c['agent']} claimed {k}={v}, the data say {data[0]}",
                          "evidence": {"fact": k, "claimed": v, "data": data[0], "claim_ref": c["ref"],
                                       "data_ref": data[1], "agent": c["agent"],
                                       "agent_had_this_fact": k in own,
                                       "claimed_as_string": isinstance(v, str)}})
        if k not in own:
            agrees = None if k not in later else same(v, later[k][0])
            flags.append({"code": "claim_unsupported", "severity": "medium",
                          "what": f"agent {c['agent']} claimed {k}={v} but no tool had returned {k} to it",
                          "evidence": {"fact": k, "claimed": v, "claim_ref": c["ref"], "agent": c["agent"],
                                       "later_data": later[k][0] if k in later else None,
                                       "later_data_ref": later[k][1] if k in later else None,
                                       "later_data_agrees": agrees}})
    return flags


def review_v4(conv: dict) -> dict:
    r = q3.review(conv)
    decision = conv.get("decision") or {}
    # Change 4 (found on the DEV corpus, 2 of 2 dev flags): V3 raised missed_entitlement when the outcome was
    # ask_user for a refund, i.e. the refund WAS offered and the client was asked to confirm it. Not missed.
    pending = decision.get("outcome") == "ask_user" and decision.get("action") == "refund"
    flags = [f for f in r["flags"] if f["code"] != "claim_contradicts_data"
             and not (f["code"] == "missed_entitlement" and pending)]
    flags += claim_flags(conv)
    worst = max((q3.SEVERITY_ORDER[f["severity"]] for f in flags), default=0)
    return {**r, "flags": flags, "grade": {3: "fail", 2: "review", 1: "ok_minor", 0: "ok"}[worst],
            "checks_version": "m7-v4"}


# ---------------- evidence verification ----------------
# flag code -> {evidence key: allowed trace steps at that line}
REF_STEPS = {
    "pipeline_error": {"ref": {"pipeline_error"}},
    "claim_false": {"claim_ref": {"proposal", "proposal_refused", "coordinator_check"},
                    "data_ref": {"tool_call", "coordinator_check"}},
    "claim_unsupported": {"claim_ref": {"proposal", "proposal_refused", "coordinator_check"},
                          "later_data_ref": {"coordinator_check"}},
    "cited_missing_rule": {"ref": {"coordinator_check", "proposal", "proposal_refused"}},
    "sent_back": {"refs": {"send_back_to_agent"}},
    "escalated": {"ref": {"pipeline_done"}},
    "rule_not_searched": {"ref": {"rule_not_searched"}},
    "agent_answered_without_tools": {"ref": {"agent_retry"}},
    "proposal_malformed": {"ref": {"proposal_refused"}},
    "missed_entitlement": {"ref": {"pipeline_done"}},
    "reply_leak": {"ref": {"pipeline_done"}},
    "slm_fallback_template": {"ref": {"pipeline_done"}},
    "reply_language_mismatch": {"ref": {"pipeline_done"}},
    "handover_ignored": {"ref": {"handover_ignored"}},
}


def _contains(obj, value) -> bool:
    """True if `value` appears somewhere in obj (dict / list / str) — for checking a ref's line holds the value."""
    if isinstance(obj, dict):
        return any(_contains(v, value) for v in obj.values())
    if isinstance(obj, list):
        return any(_contains(v, value) for v in obj)
    if isinstance(obj, str):
        return str(value) in obj
    return q3._same(obj, value) if isinstance(obj, (int, float, bool)) and isinstance(value, (int, float, bool)) \
        else obj == value


def verify_refs(conv: dict, review: dict) -> list[dict]:
    """For every evidence ref of every flag: is it in this conversation's span and file, does the line have the
    expected step, and (claims) does that line contain the claimed / data value? Returns one row per ref."""
    rows = []
    lines = conv.get("lines") or {}
    for f in review["flags"]:
        for key, steps in REF_STEPS.get(f["code"], {}).items():
            refs = f["evidence"].get(key)
            if refs is None:
                continue
            for ref in (refs if isinstance(refs, list) else [refs]):
                ok_file = str(ref).rsplit(":", 1)[0] == conv.get("file")
                n = line_no(ref)
                step = lines.get(n, (None,))[0]
                ok = ok_file and n in lines and step in steps
                if ok and f["code"] in ("claim_false", "claim_unsupported"):
                    val = f["evidence"]["claimed"] if key == "claim_ref" else \
                        f["evidence"]["data"] if key == "data_ref" else f["evidence"]["later_data"]
                    ok = _contains(lines[n][1], val)
                rows.append({"conversation_id": conv["conversation_id"], "code": f["code"], "key": key, "ref": ref,
                             "step_at_ref": step, "ok": bool(ok)})
    return rows
