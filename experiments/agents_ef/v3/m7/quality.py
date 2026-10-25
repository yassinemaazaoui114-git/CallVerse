"""M7 responsibility 2: review the quality of each CLOSED conversation with deterministic checks (no model).

    review(conv) -> {"conversation_id", "resolution", "grade", "flags": [{code, severity, what, evidence}]}

Every flag carries its evidence: values and the trace line(s) (file:line) they come from, so the owner can check
it. The checks only READ the trace; facts are compared with the tool results recorded in the same trace (the
data the platform gave at that moment), so a review can be repeated later and gives the same answer.

Why rules and not a model here: each check has a precise definition taken from the prototype itself (the
Coordinator's checks, the policy file, the SLM leak rule). A model would add cost and errors for no gain.
"""

import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))      # repository root
from callverse.kb.policies import check_condition, get_policy  # noqa: E402

# Internal words that must never reach the client. Same pattern as the prototype's T08 leak check
# (scripts/run_scenario.py LEAK_RE); copied, because importing that script starts the whole demo.
LEAK_RE = re.compile(r"coordinator|agent|proposal|P-0|\bR-[A-Z]{0,3}-?\d|sent for checking", re.IGNORECASE)
FR_WORDS = re.compile(r"\b(bonjour|commande|je|vous|ma|mon|est|pas|merci|livr\w*|rembours\w*|retard)\b", re.I)

SEVERITY_ORDER = {"high": 3, "medium": 2, "low": 1}
# Outcome -> resolution class for the owner.
RESOLUTION = {"approve": "resolved", "info": "resolved", "off_topic": "resolved",
              "ask_user": "waiting_on_client", "ask_proof": "waiting_on_client",
              "layer3": "waiting_on_finance", "escalate": "escalated", "layer3_refused": "resolved",
              "refused": "escalated"}
FACT_KEYS = ("days_late", "delivered", "paid", "refunded_total")


def known_facts(conv: dict) -> dict:
    """Facts the platform's tools returned in this conversation: {fact: (value, trace ref)}."""
    facts = {}
    for c in conv["tool_calls"]:
        r = c.get("result") if isinstance(c.get("result"), dict) else {}
        if c["tool"] == "get_tracking":
            for k in ("days_late", "delivered", "days_since_delivery", "status"):
                if k in r:
                    facts.setdefault(k, (r[k], c["ref"]))
        elif c["tool"] == "get_order":
            for k in ("paid", "status"):
                if k in r:
                    facts.setdefault(k, (r[k], c["ref"]))
        elif c["tool"] == "get_refunds" and "refunded_total" in r:
            facts.setdefault("refunded_total", (r["refunded_total"], c["ref"]))
    return facts


def _same(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < 0.01
    return a == b


def _claims(conv: dict) -> list[tuple[dict, str]]:
    """Facts the agent CLAIMED in its proposals (accepted or refused by the proposal tool)."""
    out = []
    for p in conv["proposals"]:
        if isinstance(p.get("facts_used"), dict):
            out.append((p["facts_used"], p["ref"]))
    for p in conv["proposal_refusals"]:
        f = (p.get("fields") or {}).get("facts_used")
        if isinstance(f, dict):
            out.append((f, p["ref"]))
    for c in conv["checks"]:              # also in the Coordinator's facts_from_data check ("agent claimed: {...}")
        if c.get("check") == "facts_from_data" and isinstance(c.get("detail"), str):
            try:
                f = ast.literal_eval(c["detail"].split("agent claimed:", 1)[1].strip())
            except (ValueError, SyntaxError, IndexError):
                continue
            if isinstance(f, dict):
                out.append((f, c["ref"]))
    return out


def review(conv: dict) -> dict:
    flags = []

    def flag(code, severity, what, evidence):
        flags.append({"code": code, "severity": severity, "what": what, "evidence": evidence})

    decision = conv.get("decision") or {}
    outcome = decision.get("outcome")
    ticket = conv.get("ticket") or {}
    ev = {e["step"]: e for e in conv["events"]}

    # Q1 the agents' LLM failed: the client got the "extra check" answer.
    for e in conv["events"]:
        if e["step"] == "pipeline_error":
            flag("pipeline_error", "high", "the agents failed; the client was told the case needs an extra check",
                 {"error": e.get("error"), "ref": e["ref"]})

    # Q2 a fact the agent claimed contradicts what the platform's tools returned (ungrounded claim).
    data = known_facts(conv)
    seen = set()
    for claimed, ref in _claims(conv):
        for k in FACT_KEYS:
            if k in claimed and k in data and not _same(claimed[k], data[k][0]) and (k, str(claimed[k])) not in seen:
                seen.add((k, str(claimed[k])))
                flag("claim_contradicts_data", "high", f"agent claimed {k}={claimed[k]}, the data says {data[k][0]}",
                     {"claim_ref": ref, "data_ref": data[k][1], "fact": k, "claimed": claimed[k], "data": data[k][0]})

    # Q3 the agent cited a rule id that is not in the policy file (stale knowledge in the agent).
    #    Seen by the Coordinator (rule_exists check) or earlier, in a proposal the proposal tool refused.
    missing = {}
    for c in conv["checks"]:
        if c.get("check") == "rule_exists" and c.get("result") == "fail":
            missing.setdefault(c.get("rule_id"), c["ref"])
    for p in conv["proposals"] + [{**(x.get("fields") or {}), "ref": x["ref"]} for x in conv["proposal_refusals"]]:
        rid = p.get("rule_id")
        if isinstance(rid, str) and get_policy(rid) is None:
            missing.setdefault(rid, p["ref"])
    for rid, ref in missing.items():
        flag("cited_missing_rule", "medium", f"agent cited rule {rid}, which does not exist",
             {"rule_id": rid, "ref": ref})

    # Q4 corrections by the Coordinator.
    if conv["send_backs"]:
        reasons = [d.get("reason") for d in conv["decisions"] if d.get("outcome") == "send_back"]
        flag("sent_back", "medium" if len(conv["send_backs"]) == 1 else "high",
             f"the Coordinator sent the proposal back {len(conv['send_backs'])} time(s)",
             {"reasons": reasons, "refs": [s["ref"] for s in conv["send_backs"]]})
    if outcome == "escalate":
        flag("escalated", "medium", "case escalated to a human", {"reason": decision.get("reason"),
                                                                  "ref": conv.get("done_ref")})

    # Q5 process slips the prototype already traces.
    if "rule_not_searched" in ev:
        e = ev["rule_not_searched"]
        flag("rule_not_searched", "low", f"agent cited {e.get('rule_id')} without searching the policies",
             {"rule_id": e.get("rule_id"), "ref": e["ref"]})
    if "agent_retry" in ev:
        flag("agent_answered_without_tools", "low", "agent answered without using a tool; the pipeline re-ran it",
             {"first_answer": ev["agent_retry"].get("first_answer"), "ref": ev["agent_retry"]["ref"]})
    for p in conv["proposal_refusals"]:
        flag("proposal_malformed", "medium", "the proposal tool refused the agent's proposal",
             {"problems": p.get("problems"), "ref": p["ref"]})

    # Q6 entitlement: the data show the client was entitled to a refund under R-REF-03, the client asked
    # for money back, and no refund was approved or sent to finance (a missed entitlement).
    if ticket.get("main_reason") == "refund_request" and outcome not in ("approve", "layer3", "escalate"):
        f = {k: v[0] for k, v in data.items()}
        if all(k in f for k in ("days_late", "delivered", "paid", "refunded_total", "status")) \
                and f["status"] not in ("cancelled", "refunded"):
            rule = get_policy("R-REF-03")
            try:
                due = check_condition(rule["condition"], f) and f["paid"] - f["refunded_total"] > 0
            except ValueError:
                due = False
            if due:
                flag("missed_entitlement", "high", "client asked for a refund the data show is due (R-REF-03), "
                     "but none was approved", {"facts": f, "outcome": outcome, "ref": conv.get("done_ref")})

    # Q7 the reply the client received.
    reply = conv.get("final_reply") or ""
    leaks = [m.group(0) for m in LEAK_RE.finditer(reply)]
    if leaks:
        flag("reply_leak", "high", "internal words reached the client", {"words": leaks, "ref": conv.get("done_ref")})
    if conv.get("reply_source") == "template":
        flag("slm_fallback_template", "low", "the SLM gave no passing reply; the fixed template was sent",
             {"slm_problems": [c.get("problems") for c in conv["slm_checks"]], "ref": conv.get("done_ref")})
    fr_in, fr_out = len(FR_WORDS.findall(conv.get("client_text") or "")), len(FR_WORDS.findall(reply))
    if fr_in >= 3 and fr_out == 0:
        flag("reply_language_mismatch", "medium", "client wrote in French, the reply is not in French",
             {"client_fr_words": fr_in, "ref": conv.get("done_ref")})
    if "handover_ignored" in ev:
        flag("handover_ignored", "low", ev["handover_ignored"].get("reason"), {"ref": ev["handover_ignored"]["ref"]})

    worst = max((SEVERITY_ORDER[f["severity"]] for f in flags), default=0)
    return {"conversation_id": conv.get("conversation_id"), "file": conv.get("file"),
            "ticket_id": ticket.get("ticket_id"), "order_id": ticket.get("order_id"),
            "main_reason": ticket.get("main_reason"), "priority": ticket.get("priority_label"),
            "route": (conv.get("route") or {}).get("agent"), "outcome": outcome,
            "rule_id": decision.get("rule_id"), "resolution": RESOLUTION.get(outcome, "unknown"),
            "reply_source": conv.get("reply_source"), "seconds": conv.get("seconds"),
            "grade": {3: "fail", 2: "review", 1: "ok_minor", 0: "ok"}[worst], "flags": flags}
