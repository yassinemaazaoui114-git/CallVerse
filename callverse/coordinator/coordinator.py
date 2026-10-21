"""The Coordinator: the rule-based safety gate between agent PROPOSALS and the ShopNova database.

Agents never act. They send a proposal, e.g.
    {"agent": "B", "action": "refund", "params": {"order_id": 4512, "amount": 59.90},
     "rule_id": "R-REF-03", "facts_used": {...}, "user_confirmed": True, "user_quote": "..."}
and review(proposal, case) decides what happens. Rules only, NO LLM: the same proposal always gets the
same decision, and every check can be shown to the teacher in the trace.

Why not trust the agent? An LLM can misread a number or cite the wrong rule. So the Coordinator ignores
the agent's facts_used and RE-READS the facts itself (get_order, get_refunds, get_tracking), then checks:
  1. the action is known and the order exists;
  2. the cited rule exists, may justify this action (config: coordinator.allowed_rules) and its
     condition is true on the re-read facts (check_condition, no eval);
  3. refund: R-REF-05 (amount <= paid - refunded_total) is ALWAYS checked;
     subscribe: R-NOT-01 (the event is a notification event) is ALWAYS checked;
  4. the client confirmed (user_confirmed), else ask the client;
  5. refund above R-ESC-01's threshold (300 TND): finance (Layer 3) must approve first.

Outcomes:
  approve        -> decision recorded, then the platform writes (create_refund / create_subscription,
                    and the order becomes "refunded" for an R-REF-03 full refund)
  send_back      -> the agent gets the reason and may correct (max 2 per case; the 3rd becomes escalate)
  ask_user       -> the client must confirm first
  ask_proof      -> R-DMG-01: a photo of the damage is needed first
  layer3_refused -> finance refused (recorded as decision "layer3")
  escalate       -> a human colleague takes over
  refused        -> the proposal was already decided (a proposal is decided once); nothing written
Every check is traced (coordinator_check) and so is the final decision (coordinator_decision).

What the user is told (T08): the decision carries `must_say` (the key fact, copied word for word) and
`next_step`, both written TO THE USER by this file (user_words), plus `facts` in the SLM's format
(docs/decision_format.md). The SLM only chooses the wording around them. Cases without a proposal get an
`info` decision (info_decision), with facts read from get_tracking, never from the agent's text.
"""

from callverse import trace
from callverse.config import load_config
from callverse.data.layer3 import layer3_decide
from callverse.data.writes import (create_refund, create_subscription, is_valid_amount, record_decision,
                                   record_proposal, set_order_status)
from callverse.kb.policies import check_condition, get_policy, layer3_threshold
from callverse.tools.shopnova_tools import get_order, get_refunds, get_tracking

# Outcome -> decision stored in the proposals table (the platform's list of decisions).
RECORDED_AS = {"layer3_refused": "layer3"}

# Outcomes the user never gets a reply for: the loop goes on (send_back) or nothing happened (refused).
INTERNAL_OUTCOMES = ("send_back", "refused")

# How an order status code is said to the user (T08). Unknown codes: underscores become spaces.
STATUS_WORDS = {
    "processing": "being prepared",
    "shipped": "on its way",
    "stuck_at_depot": "delayed at the delivery depot",
    "out_for_delivery": "out for delivery",
    "delivered": "delivered",
    "refunded": "refunded",
    "cancelled": "cancelled",
}


def status_words(code) -> str:
    return STATUS_WORDS.get(code, str(code).replace("_", " "))


def user_words(outcome: str, action, rule_id, facts: dict, order_id) -> tuple[list[str], str]:
    """(must_say, next_step) written TO THE USER for a decision (T08 table).

    Only facts from the data or the policy text: no timing and no payment method (the data has neither).
    The SLM copies must_say word for word and ends with next_step.
    """
    amount = facts.get("amount_tnd")
    if outcome == "approve" and action == "refund":
        if facts.get("layer3_decision") == "approved":
            must = f"Your refund of {amount:.2f} TND is approved after a check by our finance team."
        else:
            must = f"Your refund of {amount:.2f} TND is approved."
        next_step = {"R-REF-03": f"Your order {order_id} is now cancelled.",
                     "R-RET-01": "The refund is paid once we receive the returned item."}.get(rule_id, "")
        return [must], next_step
    if outcome == "approve" and action == "subscribe":
        return [f"You will get a message here when your order is {status_words(facts.get('event'))}."], ""
    if outcome == "layer3_refused":
        return ([f"We cannot approve a refund of {amount:.2f} TND for order {order_id}."],
                "Our finance team reviewed it and did not approve it.")
    if outcome == "ask_user":
        if action == "refund" and amount is not None:
            return [f"Please confirm that you want a refund of {amount:.2f} TND for order {order_id}."], ""
        return [f"Please confirm that you want a message when your order is {status_words(facts.get('event'))}."], ""
    if outcome == "ask_proof":
        return ["Please send us a photo of the damage."], ""
    if outcome == "escalate":
        return ["Your case needs an extra check, so it has been passed on for review."], ""
    return [], ""   # send_back / refused: internal, no words for the user


def slm_facts(checked: dict, action) -> dict:
    """The facts the reply may use (docs/decision_format.md), from the facts the Coordinator re-read."""
    out = {"order_status": checked.get("status"), "days_late": checked.get("days_late")}
    if action == "refund" and checked.get("amount") is not None:
        out["amount_tnd"] = round(float(checked["amount"]), 2) if is_valid_amount(checked["amount"]) else None
    if action == "subscribe":
        out["event"] = checked.get("event")
    if checked.get("layer3_decision"):
        out["layer3_decision"] = checked["layer3_decision"]
        out["threshold_tnd"] = layer3_threshold()
    return {k: v for k, v in out.items() if v is not None}


def info_decision(order_id) -> dict:
    """Decision for a case WITHOUT a proposal (status questions): facts read here with get_tracking,
    never taken from the agent's text."""
    if order_id is None or "error" in (tracking := get_tracking(order_id)):
        decision = {"outcome": "info", "action": "status", "order_id": None, "rule_id": None, "facts": {},
                    "must_say": [], "next_step": "Please tell us your order number so we can check it.",
                    "reason": "no known order", "proposal_id": None}
    else:
        facts = {"order_status": tracking["status"], "days_late": tracking["days_late"],
                 "promised_date": tracking["promised_date"]}
        if tracking.get("carrier"):
            facts["carrier"] = tracking["carrier"]
        # R-DEL-02 case (1 to 5 days late, not delivered): offer the delivery message.
        r_del_02 = 1 <= tracking["days_late"] <= 5 and not tracking["delivered"]
        decision = {"outcome": "info", "action": "status", "order_id": order_id,
                    "rule_id": "R-DEL-02" if r_del_02 else None, "facts": facts,
                    "must_say": [f"Your order {order_id} is {status_words(tracking['status'])}."],
                    "next_step": ("If you like, we can send you a message when it is out for delivery."
                                  if r_del_02 else ""),
                    "reason": "status from get_tracking", "proposal_id": None}
    trace.log("coordinator_decision", "coordinator", decision)
    return decision


def for_user(decision: dict) -> dict:
    """A decision the user may get a reply for. An internal outcome left at the end of the loop
    (the agent did not correct a sent-back proposal) is said as "escalate": a human looks at it."""
    if decision["outcome"] not in INTERNAL_OUTCOMES:
        return decision
    must_say, next_step = user_words("escalate", decision["action"], decision["rule_id"], decision["facts"],
                                     decision["order_id"])
    out = {**decision, "outcome": "escalate", "must_say": must_say, "next_step": next_step,
           "reason": f"internal outcome {decision['outcome']} at the end of the case: {decision['reason']}"}
    trace.log("internal_outcome_to_escalate", "coordinator", {"from": decision["outcome"], "proposal_id": decision["proposal_id"]})
    return out


def new_case(case_id: str) -> dict:
    """State the Coordinator keeps for one client case (one ticket)."""
    return {"case_id": case_id, "send_backs": 0, "proof_received": False}


def _check(name: str, ok: bool, rule_id, facts: dict, detail: str) -> bool:
    """Trace one check (rule, facts, result) and return ok."""
    trace.log("coordinator_check", "coordinator",
              {"check": name, "rule_id": rule_id, "facts": facts, "result": "pass" if ok else "fail",
               "detail": detail})
    return ok


def _read_facts(order_id: int, case: dict) -> dict:
    """The facts the rules need, read from the platform by the Coordinator itself (never from the agent)."""
    order = get_order(order_id)
    tracking = get_tracking(order_id)
    refunds = get_refunds(order_id)
    return {"order_id": order_id, "status": order["status"], "paid": order["paid"],
            "refunded_total": refunds["refunded_total"], "days_late": tracking["days_late"],
            "delivered": tracking["delivered"], "days_since_delivery": tracking["days_since_delivery"],
            "proof_received": bool(case.get("proof_received"))}


def review(proposal: dict, case: dict) -> dict:
    """Check one proposal and return the decision dict:
    {outcome, action, order_id, rule_id, facts (only verified facts), next_step, reason, proposal_id}."""
    cfg = load_config()["coordinator"]
    action = proposal.get("action") if isinstance(proposal, dict) else None
    params = proposal.get("params") if isinstance(proposal, dict) and isinstance(proposal.get("params"), dict) else {}
    rule_id = proposal.get("rule_id") if isinstance(proposal, dict) else None
    order_id = params.get("order_id")
    facts: dict = {}

    # 0. Record the proposal first (audit trail), unless it was already recorded.
    proposal_id = proposal.get("proposal_id") if isinstance(proposal, dict) else None
    if proposal_id is None:
        recorded = record_proposal(proposal)
        proposal_id = recorded.get("id")
        if proposal_id is None:
            return _finish("send_back", case, proposal_id, action, order_id, rule_id, facts,
                           f"proposal could not be recorded: {recorded.get('error')}")

    def done(outcome: str, reason: str) -> dict:
        return _finish(outcome, case, proposal_id, action, order_id, rule_id, facts, reason)

    # 1. Known action, existing order.
    if not _check("action_known", action in cfg["allowed_rules"], None, {"action": action},
                  f"allowed actions: {list(cfg['allowed_rules'])}"):
        return done("send_back", f"unknown action '{action}' (allowed: refund, subscribe)")
    order_ok = isinstance(order_id, int) and not isinstance(order_id, bool) and "error" not in get_order(order_id)
    if not _check("order_exists", order_ok, None, {"order_id": order_id}, "read with get_order"):
        return done("send_back", f"order {order_id} not found")

    # 2. Facts re-read from the data (the agent's facts_used are only kept in the trace, for comparison).
    facts = _read_facts(order_id, case)
    if action == "refund":
        facts["amount"] = params.get("amount")
    else:
        facts["event"] = params.get("event")
    _check("facts_from_data", True, None, facts, f"agent claimed: {proposal.get('facts_used')}")

    # 3. The cited rule: exists, may justify this action, its condition holds.
    rule = get_policy(rule_id) if isinstance(rule_id, str) else None
    if not _check("rule_exists", rule is not None, rule_id, {}, "looked up in the policy file"):
        return done("send_back", f"rule {rule_id} does not exist")
    if not _check("rule_fits_action", rule_id in cfg["allowed_rules"][action], rule_id, {"action": action},
                  f"rules that can justify '{action}': {cfg['allowed_rules'][action]}"):
        return done("send_back", f"rule {rule_id} cannot justify a {action}; "
                                 f"use one of {cfg['allowed_rules'][action]}")
    # Warning only (T07 follow-up): the agent cites a rule it did not look up with search_policy this turn.
    searched = case.get("searched_rules")
    if searched is not None and rule_id not in searched:
        trace.log("rule_not_searched", "coordinator", {"rule_id": rule_id, "searched": sorted(searched),
                                                       "proposal_id": proposal_id})
    try:
        holds = check_condition(rule["condition"], facts)
    except ValueError as e:
        holds = False
        trace.log("coordinator_check", "coordinator", {"check": "rule_condition_error", "rule_id": rule_id,
                                                        "detail": str(e)})
    if not _check("rule_condition", holds, rule_id, facts, rule["condition"]):
        if "proof_received" in rule["condition"] and not facts["proof_received"]:
            return done("ask_proof", f"{rule_id}: a photo of the damage is needed before a refund")
        return done("send_back", f"{rule_id} does not apply: its condition '{rule['condition']}' is false "
                                 f"for the order data (days_late {facts['days_late']}, delivered {facts['delivered']})")

    # 4. The limit that always applies to the action.
    if action == "refund":
        amount = facts["amount"]
        if not _check("amount_valid", is_valid_amount(amount), None, {"amount": amount}, "a number > 0"):
            return done("send_back", "amount must be a number above 0")
        limit = get_policy("R-REF-05")
        if not _check("refund_limit", check_condition(limit["condition"], facts), "R-REF-05", facts,
                      limit["condition"]):
            left = round(facts["paid"] - facts["refunded_total"], 2)
            return done("send_back", f"R-REF-05: amount {amount} TND is more than paid {facts['paid']} - "
                                     f"already refunded {facts['refunded_total']} = {left} TND")
    else:
        events_rule = get_policy("R-NOT-01")
        if not _check("event_allowed", check_condition(events_rule["condition"], facts), "R-NOT-01", facts,
                      events_rule["condition"]):
            return done("send_back", f"R-NOT-01: '{facts['event']}' is not a notification event "
                                     f"(shipped, out_for_delivery, delivered)")

    # 5. The client must have asked for it.
    if not _check("user_confirmed", proposal.get("user_confirmed") is True, None,
                  {"user_quote": proposal.get("user_quote")}, "user_confirmed must be true"):
        return done("ask_user", "the client has not confirmed the request yet")

    # 6. Large refunds: finance (Layer 3) decides first.
    if action == "refund":
        escalation = get_policy("R-ESC-01")
        if check_condition(escalation["condition"], facts):
            finance = layer3_decide(order_id, facts["amount"], f"refund under {rule_id}")
            facts["layer3_decision"] = finance.get("decision")
            if not _check("layer3", finance.get("decision") == "approved", "R-ESC-01", facts,
                          f"finance: {finance}"):
                if finance.get("decision") == "refused":
                    return done("layer3_refused", f"R-ESC-01: finance refused the refund of {facts['amount']} TND")
                return done("escalate", f"Layer 3 error: {finance.get('error')}")

    # 7. Approve, then (only then) the platform writes.
    return done("approve", f"all checks passed under {rule_id}")


def _finish(outcome, case, proposal_id, action, order_id, rule_id, facts, reason) -> dict:
    """Apply the send-back limit, record the decision, write on approve, trace and return the decision."""
    if outcome == "send_back" and case["send_backs"] >= load_config()["coordinator"]["max_send_backs"]:
        outcome, reason = "escalate", f"too many send-backs ({case['send_backs']}); last reason: {reason}"

    if proposal_id is not None:
        stored = record_decision(proposal_id, RECORDED_AS.get(outcome, outcome), reason)
        if "error" in stored:   # e.g. already decided: never decide twice, never write
            outcome, reason = "refused", stored["error"]

    if outcome == "send_back":
        case["send_backs"] += 1

    if outcome == "approve":
        if action == "refund":
            row = create_refund(order_id, facts["amount"], rule_id, proposal_id)
            if "error" not in row and rule_id == "R-REF-03":
                moved = set_order_status(order_id, "refunded")   # full refund for a late order: order is cancelled/refunded
                if "error" not in moved:
                    facts["status"] = moved["new_status"]
        else:
            row = create_subscription(order_id, facts["event"], proposal_id)
        if "error" in row:      # a platform safety net refused the write: a human must look
            outcome, reason = "escalate", f"write refused by the platform: {row['error']}"

    # What the user may be told (T08): only verified facts, sentences written to the user.
    reply_facts = slm_facts(facts, action)
    must_say, next_step = user_words(outcome, action, rule_id, reply_facts, order_id)
    decision = {"outcome": outcome, "action": action, "order_id": order_id, "rule_id": rule_id,
                "facts": reply_facts, "must_say": must_say, "next_step": next_step, "reason": reason,
                "proposal_id": proposal_id}
    # The trace also keeps every fact the checks used (paid, refunded_total, delivered, ...).
    trace.log("coordinator_decision", "coordinator", {**decision, "checked_facts": facts, "case": dict(case)})
    return decision
