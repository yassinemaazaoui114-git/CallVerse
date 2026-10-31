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
T14a, a cancel proposal (rule R-CAN-01): it must be about the ticket's own order; an order that is not "processing"
gets a decline, not a send-back; the amount is computed here (paid - refunded_total); the confirmation is decided by
code (cancel_confirmed), like Atlas in T21, because a cancellation cannot be undone.

Outcomes:
  approve        -> decision recorded, then the platform writes (create_refund / create_subscription,
                    and the order becomes "refunded" for an R-REF-03 full refund)
  send_back      -> the agent gets the reason and may correct (max 2 per case; the 3rd becomes escalate)
  ask_user       -> the client must confirm first
  ask_proof      -> R-DMG-01: a photo of the damage is needed first
  layer3_refused -> finance refused (recorded as decision "layer3")
  layer3_pending -> T18, layer3 mode "queue" only: the refund waits for the ShopNova admin. NOTHING is recorded
                    as decision (the proposal stays undecided, so the admin's decision is the one recorded later,
                    by callverse/channels/approvals.py) and nothing is written
  escalate       -> a human colleague takes over
  decline        -> T14a: the rules say no. The reason is written here, by code (decline_words), never by an LLM
  refused        -> the proposal was already decided (a proposal is decided once); nothing written
Every check is traced (coordinator_check) and so is the final decision (coordinator_decision).

What the user is told (T08): the decision carries `must_say` (the key fact, copied word for word) and
`next_step`, both written TO THE USER by this file (user_words), plus `facts` in the SLM's format
(docs/decision_format.md). The SLM only chooses the wording around them. Cases without a proposal get an
`info` decision (info_decision), with facts read from get_tracking, never from the agent's text.
T14a: before that, no_proposal_decision re-reads the order: if a rule says no, the client gets a `decline` with the
reason, not only the status.
"""

import re

from callverse import trace
from callverse.config import load_config
from callverse.data.layer3 import layer3_decide, layer3_mode
from callverse.data.writes import (cancel_order_by_user, create_refund, create_subscription, is_valid_amount,
                                   record_decision, record_proposal, set_order_status)
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


# T14a: a cancel request said in the negative ("do not cancel", "I don't want to cancel"): the client is asked first.
# Only around the word "cancel": real messages often have "didn't arrive so please cancel", which IS a request.
NOT_CANCEL_RE = re.compile(r"\b(?:not|don't|dont|never|no longer)\b(?:\s+\w+){0,3}?\s+cancel", re.IGNORECASE)
SENTENCE_ENDS = ".!?\n"
# Main reason -> the action a decline is about (T14a).
DECLINE_ACTIONS = {"return_item": "return", "refund_request": "refund", "cancel_order": "cancel"}
# Finished orders have no delivery date left to talk about: R-REF-03's "not late" sentence would be wrong for them.
CLOSED_STATUSES = ("refunded", "cancelled")
ON_THE_WAY_STATUSES = ("shipped", "out_for_delivery", "stuck_at_depot")   # R-CAN-01's next step


def status_words(code) -> str:
    return STATUS_WORDS.get(code, str(code).replace("_", " "))


def decline_words(rule_id, facts: dict, order_id) -> tuple[list[str], str]:
    """(must_say, next_step) of a decline (T14a table): the rule and the reason, from the facts re-read here.
    One item per sentence: the reply writer removes a sentence that is only a part of a longer must_say item."""
    status = status_words(facts.get("order_status"))
    if rule_id == "R-RET-01":
        return ["Returns are possible within 14 days of delivery.",
                f"Order {order_id} was delivered {facts.get('days_since_delivery')} days ago, so it can no longer be returned."], ""
    if rule_id == "R-REF-05":
        return [f"Order {order_id} has already been fully refunded ({facts.get('amount_tnd'):.2f} TND), "
                "so no further refund is possible."], ""
    if rule_id == "R-REF-03":
        return [f"Order {order_id} is {status} and is not late: it is due by {facts.get('promised_date')}.",
                "A refund for a late delivery is possible when an order is more than 5 days late."], ""
    must = [f"Order {order_id} is already {status}, so it can no longer be cancelled.",
            "An order can be cancelled only while it is being processed."]
    if facts.get("order_status") in ON_THE_WAY_STATUSES:
        return must, "Once it is delivered, you can return it within 14 days."
    days = facts.get("days_since_delivery")
    if facts.get("order_status") == "delivered" and days is not None and days <= 14:
        return must, "You can still return it within 14 days of delivery."
    return must, ""


def user_words(outcome: str, action, rule_id, facts: dict, order_id) -> tuple[list[str], str]:
    """(must_say, next_step) written TO THE USER for a decision (T08 table).

    Only facts from the data or the policy text: no timing and no payment method (the data has neither).
    The SLM copies must_say word for word and ends with next_step.
    """
    amount = facts.get("amount_tnd")
    if outcome == "decline":
        return decline_words(rule_id, facts, order_id)
    if outcome == "approve" and action == "cancel":
        must = [f"Your order {order_id} is now cancelled."]
        if amount:
            must.append(f"Your refund of {amount:.2f} TND is approved" + (" after a check by our finance team."
                        if facts.get("layer3_decision") == "approved" else "."))
        return must, ""
    if outcome == "approve" and action == "refund":
        if facts.get("layer3_decision") == "approved":
            must = f"Your refund of {amount:.2f} TND is approved after a check by our finance team."
        else:
            must = f"Your refund of {amount:.2f} TND is approved."
        # T17 follow-up (F3): the order's NEW status is said from the facts (the status _finish read back after
        # set_order_status), never a fixed word. Before, R-REF-03 always said "cancelled" while the data said
        # "refunded". If the status did not move, nothing is said about it.
        status = facts.get("order_status")
        moved = f"Your order {order_id} is now {status_words(status)}." if status in ("refunded", "cancelled") else ""
        next_step = {"R-REF-03": moved,
                     "R-RET-01": "The refund is paid once we receive the returned item."}.get(rule_id, "")
        return [must], next_step
    if outcome == "approve" and action == "subscribe":
        return [f"You will get a message here when your order is {status_words(facts.get('event'))}."], ""
    if outcome == "layer3_refused":
        return ([f"We cannot approve a refund of {amount:.2f} TND for order {order_id}."],
                "Our finance team reviewed it and did not approve it.")
    if outcome == "layer3_pending":   # T18: no time promise
        return ([f"Your refund of {amount:.2f} TND for order {order_id} needs approval from our finance team."],
                "We will reply here as soon as it has been reviewed.")
    if outcome == "ask_user":
        if action == "cancel":
            return [f"Please confirm that you want to cancel order {order_id}."], ""
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
    if action in ("refund", "cancel") and checked.get("amount"):
        out["amount_tnd"] = round(float(checked["amount"]), 2) if is_valid_amount(checked["amount"]) else None
    if action == "subscribe":
        out["event"] = checked.get("event")
    if action == "cancel":     # T14a: R-CAN-01's next step depends on it (None for an order not delivered)
        out["days_since_delivery"] = checked.get("days_since_delivery")
    if checked.get("layer3_decision"):
        out["layer3_decision"] = checked["layer3_decision"]
        out["threshold_tnd"] = layer3_threshold()
    return {k: v for k, v in out.items() if v is not None}


def info_decision(order_id) -> dict:
    """Decision for a case WITHOUT a proposal (status questions): facts read here with get_tracking,
    never taken from the agent's text."""
    if order_id is None:
        decision = {"outcome": "info", "action": "status", "order_id": None, "rule_id": None, "facts": {},
                    "must_say": [], "next_step": "Please tell us your order number so we can check it.",
                    "reason": "no order number", "proposal_id": None}
    elif "error" in (tracking := get_tracking(order_id)):
        # T10: an order number that does not exist is said plainly (no facts are invented about it).
        decision = {"outcome": "info", "action": "status", "order_id": order_id, "rule_id": None, "facts": {},
                    "must_say": [f"We could not find order {order_id}."],
                    "next_step": "Please check the order number and send it again.",
                    "reason": "unknown order", "proposal_id": None}
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


def no_proposal_decision(main_reason, order_id) -> dict | None:
    """T14a: a ShopNova case that ends WITHOUT a proposal. The order is re-read and, by Intake's main reason, the rules
    may say no (decline, with the reason) or a cancel request may need a confirmation. None = nothing to say here:
    the caller gives today's status reply (info_decision)."""
    action = DECLINE_ACTIONS.get(main_reason)
    if action is None or order_id is None or "error" in get_order(order_id):
        return None
    facts = _read_facts(order_id, {})
    out = {"order_status": facts["status"]}
    rule_id, outcome = None, "decline"
    too_late_to_return = facts["delivered"] and facts["days_since_delivery"] > 14
    if main_reason == "return_item" and too_late_to_return:
        rule_id = "R-RET-01"
    elif main_reason == "refund_request" and facts["paid"] > 0 and facts["refunded_total"] >= facts["paid"]:
        rule_id = "R-REF-05"
        out["amount_tnd"] = round(float(facts["refunded_total"]), 2)
    elif main_reason == "refund_request" and too_late_to_return:
        # Money back on a delivered order can only come from a return, and Intake often says "refund" for those.
        rule_id = "R-RET-01"
    elif (main_reason == "refund_request" and not facts["delivered"] and facts["days_late"] <= 0
          and facts["status"] not in CLOSED_STATUSES):
        rule_id = "R-REF-03"
        out.update(days_late=facts["days_late"], promised_date=facts["promised_date"])
    elif main_reason == "cancel_order" and facts["status"] != "processing":
        rule_id = "R-CAN-01"
    elif main_reason == "cancel_order":
        outcome = "ask_user"      # still processing, but no proposal: the client is asked, nothing is cancelled
    else:
        return None
    if rule_id in ("R-RET-01", "R-CAN-01") and facts["delivered"]:
        out["days_since_delivery"] = facts["days_since_delivery"]
    must_say, next_step = user_words(outcome, action, rule_id, out, order_id)
    decision = {"outcome": outcome, "action": action, "order_id": order_id, "rule_id": rule_id, "facts": out,
                "must_say": must_say, "next_step": next_step, "reason": f"no proposal: {rule_id or 'confirm first'}",
                "proposal_id": None}
    trace.log("coordinator_decision", "coordinator", decision)
    return decision


def off_topic_decision() -> dict:
    """Not about an order (T10): a polite redirect to what ShopNova support can do. No facts at all."""
    decision = {"outcome": "info", "action": "redirect", "order_id": None, "rule_id": None, "facts": {},
                "must_say": ["I can help with your ShopNova orders: delivery, refunds, returns and damaged items."],
                "next_step": "If your question is about an order, please send us the order number.",
                "reason": "off topic", "proposal_id": None}
    trace.log("coordinator_decision", "coordinator", decision)
    return decision


def escalate_decision(order_id, reason: str) -> dict:
    """Something went wrong before a decision (e.g. an error in the agents' part, T10): a human looks at it."""
    must_say, next_step = user_words("escalate", None, None, {}, order_id)
    decision = {"outcome": "escalate", "action": None, "order_id": None, "rule_id": None, "facts": {},
                "must_say": must_say, "next_step": next_step, "reason": reason, "proposal_id": None}
    trace.log("coordinator_decision", "coordinator", decision)
    return decision


def proof_decision(order_id) -> dict:
    """Damaged item and no proposal yet (T09): R-DMG-01 needs a photo before any refund or replacement,
    so the user is asked for it (not given the order status). Facts from get_tracking."""
    tracking = get_tracking(order_id) if order_id is not None else {"error": "no order"}
    facts = {} if "error" in tracking else {"order_status": tracking["status"]}
    must_say, next_step = user_words("ask_proof", "refund", "R-DMG-01", facts, order_id)
    decision = {"outcome": "ask_proof", "action": "refund", "order_id": order_id if facts else None,
                "rule_id": "R-DMG-01", "facts": facts, "must_say": must_say, "next_step": next_step,
                "reason": "damaged item, no photo yet (R-DMG-01)", "proposal_id": None}
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
            "promised_date": tracking["promised_date"], "proof_received": bool(case.get("proof_received"))}


def cancel_refund(facts: dict) -> float:
    """What a cancellation pays back: paid - refunded_total, so 0 for cash on delivery. Computed here, never by an agent."""
    return max(round(facts["paid"] - facts["refunded_total"], 2), 0.0)


def _sentence_around(quote: str, message: str) -> str | None:
    """The whole sentence of the message around the quote, or None if the quote is not in the message. The whole
    sentence, because a quote of "cancel order 4511" must not hide the "Do not" just before it."""
    start = message.find(quote)
    if start < 0:
        return None
    end = start + len(quote)
    before = max(message.rfind(mark, 0, start) for mark in SENTENCE_ENDS)
    after = [i for i in (message.find(mark, end - 1) for mark in SENTENCE_ENDS) if i >= 0]
    return message[before + 1:min(after, default=len(message))]


def cancel_confirmed(proposal: dict, case: dict) -> tuple[bool, str]:
    """(confirmed, short reason), decided by code like Atlas in T21: Intake's main reason is cancel_order, the agent's
    user_quote is really in the client's message, and that sentence is not a negative one."""
    quote = proposal.get("user_quote")
    if case.get("main_reason") != "cancel_order":
        return False, "the main reason is not cancel_order"
    if not isinstance(quote, str) or not quote.strip():
        return False, "no quote"
    sentence = _sentence_around(quote.strip().lower(), (case.get("user_message") or "").lower())
    if sentence is None:
        return False, "quote not in the message"
    if NOT_CANCEL_RE.search(sentence.replace("\u2019", "'")):
        return False, "negative sentence"
    return True, "cancel request + quote found"


def review(proposal: dict, case: dict) -> dict:
    """Check one proposal and return the decision dict:
    {outcome, action, order_id, rule_id, facts (only verified facts), next_step, reason, proposal_id}."""
    cfg = load_config()["coordinator"]
    action = proposal.get("action") if isinstance(proposal, dict) else None
    params = proposal.get("params") if isinstance(proposal, dict) and isinstance(proposal.get("params"), dict) else {}
    rule_id = proposal.get("rule_id") if isinstance(proposal, dict) else None
    order_id = params.get("order_id")
    facts: dict = {}

    # T14a: for a cancellation the code decides whether the client asked (the proposal is stored with the result).
    confirmation = cancel_confirmed(proposal, case) if action == "cancel" else None
    if confirmation:
        proposal = {**proposal, "user_confirmed": confirmation[0]}

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
        return done("send_back", f"unknown action '{action}' (allowed: {', '.join(cfg['allowed_rules'])})")
    order_ok = isinstance(order_id, int) and not isinstance(order_id, bool) and "error" not in get_order(order_id)
    if not _check("order_exists", order_ok, None, {"order_id": order_id}, "read with get_order"):
        return done("send_back", f"order {order_id} not found")
    if action == "cancel" and not _check("own_order", order_id == case.get("order_id"), None,
                                         {"order_id": order_id, "ticket_order": case.get("order_id")},
                                         "a cancellation is only for the order of the ticket"):
        return done("send_back", f"order {order_id} is not the order of this ticket ({case.get('order_id')})")

    # 2. Facts re-read from the data (the agent's facts_used are only kept in the trace, for comparison).
    facts = _read_facts(order_id, case)
    if action == "refund":
        facts["amount"] = params.get("amount")
    elif action == "subscribe":
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
        if action == "cancel":   # T14a: the order has left: a final no with the reason, not a correction for the agent
            return done("decline", f"R-CAN-01: order {order_id} is {facts['status']}, not processing")
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
    elif action == "cancel":
        facts["amount"] = cancel_refund(facts)     # computed from the data: 0 for cash on delivery
    else:
        events_rule = get_policy("R-NOT-01")
        if not _check("event_allowed", check_condition(events_rule["condition"], facts), "R-NOT-01", facts,
                      events_rule["condition"]):
            return done("send_back", f"R-NOT-01: '{facts['event']}' is not a notification event "
                                     f"(shipped, out_for_delivery, delivered)")

    # 5. The client must have asked for it.
    if not _check("user_confirmed", proposal.get("user_confirmed") is True, None,
                  {"user_quote": proposal.get("user_quote")},
                  confirmation[1] if confirmation else "user_confirmed must be true"):
        return done("ask_user", "the client has not confirmed the request yet")

    # 6. Large refunds: finance (Layer 3) decides first.
    if action in ("refund", "cancel"):
        escalation = get_policy("R-ESC-01")
        if check_condition(escalation["condition"], facts):
            if layer3_mode() == "queue":
                # T18: the ShopNova admin decides later (Refund approvals). The stub is not called.
                facts["layer3_decision"] = "pending"
                trace.log("coordinator_check", "coordinator",
                          {"check": "layer3", "rule_id": "R-ESC-01", "facts": facts, "result": "pending",
                           "detail": "layer3 mode queue: waiting for the ShopNova admin"})
                return done("layer3_pending", f"R-ESC-01: the refund of {facts['amount']} TND waits for the "
                                              "ShopNova admin (Refund approvals)")
            finance = layer3_decide(order_id, facts["amount"], f"{action} under {rule_id}")
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

    if proposal_id is not None and outcome != "layer3_pending":   # T18: pending = not decided yet
        stored = record_decision(proposal_id, RECORDED_AS.get(outcome, outcome), reason)
        if "error" in stored:   # e.g. already decided: never decide twice, never write
            outcome, reason = "refused", stored["error"]

    if outcome == "send_back":
        case["send_backs"] += 1

    if outcome == "approve":
        if action == "cancel":
            row = cancel_order_by_user(order_id, proposal_id, facts["amount"])
            if "error" not in row:
                facts["status"] = row["order"]["status"]
        elif action == "refund":
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
