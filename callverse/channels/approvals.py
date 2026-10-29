"""The ShopNova admin's refund decision (T18): the REAL Layer 3 queue, used when layer3 mode = "queue".

    decide(approval_id, admin, approve, reason) -> {approval, outcome, reply, reply_source, refund} or {"error": ...}

How a big refund (> 300 TND, rule R-ESC-01) gets here: the Coordinator returned "layer3_pending" (the proposal
stays UNDECIDED in the proposals table) and the web chat channel created an `approvals` row (pending) and set the
ticket to "Waiting for finance". The Refund approvals page then calls decide():

1. the approval must still be pending (one decision at a time: a lock; and close_approval only closes a PENDING
   row; and a proposal is decided once), so two clicks can never decide twice;
2. Approve: the Coordinator's own checks run AGAIN on fresh data before anything is written (the order exists,
   the cited rule still fits a refund and its condition still holds, R-REF-05 amount <= paid - already refunded).
   If one fails: NOTHING is written, the approval stays pending, the reason is returned (the admin can Refuse);
3. Approve: record_decision(proposal, "approve") -> create_refund (its own safety net runs again) -> for R-REF-03
   the order becomes "refunded" (same as the Coordinator's path) -> an admin_actions row.
   Refuse: a reason is required; record_decision(proposal, "layer3"); nothing is paid; an admin_actions row;
4. the approval row: approved / refused, decided_by, decided_at (simulation clock), reason;
5. a NEW assistant message on the ticket, written by the SLM from the decision (pipeline.final_reply, the same
   reply writer as every other reply) in the style Intake saved in the ticket's steps (neutral if missing).
   The admin's reason is NEVER given to the SLM: it is only stored (approval row, proposal, admin log);
6. the ticket becomes Solved with user_unread = 1 (the "New reply" notice). If create_refund still refuses
   (rare), the user gets the "extra check" (escalate) message, the ticket stays Open and the approval is
   marked refused with the platform's reason.
The trace lines of a decision are saved as steps of the ticket (like the channel does), for the Console.
"""

import threading

from callverse import pipeline, trace
from callverse.channels.web_chat import step_row
# The Coordinator's own fact reader and reply sentences: the re-check and the message use exactly its rules.
from callverse.coordinator.coordinator import _read_facts, slm_facts, user_words
from callverse.config import load_config
from callverse.data import admin_reads, writes
from callverse.kb.policies import check_condition, get_policy
from callverse.tickets import store
from callverse.tools.shopnova_tools import get_order

_lock = threading.Lock()   # one decision at a time (two clicks on Approve cannot both run)


def recheck(proposal: dict) -> tuple[dict, str | None]:
    """The Coordinator's checks for this refund proposal, again, on fresh data. Returns (facts, None) if they
    all pass, or (facts, reason in plain words) for the first one that fails."""
    params = proposal.get("params") or {}
    order_id, rule_id = params.get("order_id"), proposal.get("rule_id")
    if proposal.get("action") != "refund":
        return {}, f"proposal {proposal.get('id')} is not a refund"
    if not isinstance(order_id, int) or "error" in get_order(order_id):
        return {}, f"order {order_id} does not exist any more"
    facts = {**_read_facts(order_id, {"proof_received": False}), "amount": params.get("amount")}
    rule = get_policy(rule_id) if isinstance(rule_id, str) else None
    if rule is None or rule_id not in load_config()["coordinator"]["allowed_rules"]["refund"]:
        return facts, f"rule {rule_id} cannot justify a refund"
    try:
        holds = check_condition(rule["condition"], facts)
    except ValueError:
        holds = False
    if not holds:
        return facts, (f"rule {rule_id} does not apply any more: its condition '{rule['condition']}' is false now "
                       f"(order status {facts['status']}, days late {facts['days_late']}, "
                       f"delivered {facts['delivered']})")
    if not writes.is_valid_amount(facts["amount"]) or not check_condition(get_policy("R-REF-05")["condition"], facts):
        left = round(facts["paid"] - facts["refunded_total"], 2)
        return facts, (f"R-REF-05: the amount {facts['amount']} TND is more than paid {facts['paid']} - already "
                       f"refunded {facts['refunded_total']} = {left} TND")
    return facts, None


def _reply_ticket(ticket_id: str, order_id) -> dict:
    """The ticket as the reply writer needs it: the style Intake saved in the ticket's last intake step."""
    intake = next((s["data"] for s in reversed(store.steps(ticket_id)) if s["step"] == "intake"), {})
    return {"ticket_id": ticket_id, "order_id": order_id, "main_reason": intake.get("main_reason"),
            "style": intake.get("style"), "emotion": intake.get("emotion"), "sentiment": intake.get("sentiment")}


def decide(approval_id: int, admin: str, approve: bool, reason: str | None = None, slm_chat_fn=None) -> dict:
    """The admin approves or refuses a pending refund (see the steps at the top of this file).
    slm_chat_fn: a fake SLM for the tests (None = the real reply writer)."""
    reason = (reason or "").strip()
    with _lock:
        approval = store.get_approval(approval_id)
        if approval is None:
            return {"error": f"approval {approval_id} not found"}
        if approval["status"] != "pending":
            return {"error": f"approval {approval_id} is already {approval['status']}"}
        if not approve and not reason:
            return {"error": "a reason is required to refuse"}
        proposal = admin_reads.proposal(approval["proposal_id"])
        if proposal is None:
            return {"error": f"proposal {approval['proposal_id']} not found"}
        if proposal["decision"] is not None:
            return {"error": f"proposal {proposal['id']} is already decided: {proposal['decision']}"}

        records = []
        trace.add_listener(records.append)
        try:
            out = _decide(approval, proposal, admin, approve, reason, slm_chat_fn)
        finally:
            trace.remove_listener(records.append)
        if "error" not in out:   # a refused re-check writes nothing, not even steps
            message_id = next((m["id"] for m in reversed(store.messages(approval["ticket_id"]))
                               if m["sender"] == "user"), None)
            for record in records:
                row = step_row(record)
                if row:
                    store.add_step(approval["ticket_id"], message_id, *row)
        return out


def _decide(approval: dict, proposal: dict, admin: str, approve: bool, reason: str, slm_chat_fn) -> dict:
    order_id, rule_id, pid = approval["order_id"], proposal["rule_id"], proposal["id"]
    refund = None
    if approve:
        facts, problem = recheck(proposal)
        if problem:
            trace.log("layer3_recheck_failed", "layer3", {"approval_id": approval["id"], "reason": problem})
            return {"error": problem, "recheck_failed": True}   # nothing written; the approval stays pending
        stored = writes.record_decision(pid, "approve", f"R-ESC-01: approved by the ShopNova admin ({admin})"
                                                        + (f": {reason}" if reason else ""))
        if "error" in stored:
            return {"error": stored["error"]}
        refund = writes.create_refund(order_id, facts["amount"], rule_id, pid)
        if "error" in refund:
            # The platform's safety net refused: a human must look (like the Coordinator's own path).
            store.close_approval(approval["id"], "refused", admin, f"refund refused by the platform: {refund['error']}")
            writes.log_admin_action(admin, "approve_refund_failed", "proposals", pid, None,
                                    {"approval_id": approval["id"], "error": refund["error"]})
            outcome, refund = "escalate", None
        else:
            if rule_id == "R-REF-03":   # full refund of a late order: the order becomes "refunded"
                moved = writes.set_order_status(order_id, "refunded")
                if "error" not in moved:
                    facts["status"] = moved["new_status"]
            facts["layer3_decision"] = "approved"
            writes.log_admin_action(admin, "approve_refund", "refunds", refund["id"], None,
                                    {"refund": refund, "approval_id": approval["id"], "proposal_id": pid,
                                     "reason": reason or None})
            store.close_approval(approval["id"], "approved", admin, reason or None)
            outcome = "approve"
    else:
        facts = _read_facts(order_id, {"proof_received": False}) if "error" not in get_order(order_id) else {}
        facts.update(amount=approval["amount"], layer3_decision="refused")
        stored = writes.record_decision(pid, "layer3", f"R-ESC-01: refused by the ShopNova admin ({admin}): {reason}")
        if "error" in stored:
            return {"error": stored["error"]}
        writes.log_admin_action(admin, "refuse_refund", "proposals", pid, None,
                                {"approval_id": approval["id"], "amount": approval["amount"], "reason": reason})
        store.close_approval(approval["id"], "refused", admin, reason)
        outcome = "layer3_refused"

    # The new assistant message: the decision's own sentences (user_words), written by the reply writer.
    # decision["reason"] is a fixed text: the admin's reason never reaches the SLM or the user.
    reply_facts = slm_facts(facts, "refund")
    must_say, next_step = user_words(outcome, "refund", rule_id, reply_facts, order_id)
    decision = {"outcome": outcome, "action": "refund", "order_id": order_id, "rule_id": rule_id,
                "facts": reply_facts, "must_say": must_say, "next_step": next_step,
                "reason": "decided by the ShopNova admin (Layer 3)", "proposal_id": pid}
    trace.log("layer3_decision", "layer3", {**decision, "approval_id": approval["id"], "admin": admin,
                                            "by": "ShopNova admin"})
    _, reply, source = pipeline.final_reply(_reply_ticket(approval["ticket_id"], order_id), decision, slm_chat_fn)
    store.add_message(approval["ticket_id"], "assistant", reply)
    store.update_ticket(approval["ticket_id"], status="Open" if outcome == "escalate" else "Solved")
    store.set_unread(approval["ticket_id"], True)
    return {"approval": store.get_approval(approval["id"]), "outcome": outcome, "reply": reply,
            "reply_source": source, "refund": refund, "ticket": store.get_ticket(approval["ticket_id"])}
