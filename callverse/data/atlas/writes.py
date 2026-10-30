"""Atlas Travel WRITE functions (T21): the only code that changes Atlas data at run time.

Same rule as ShopNova's callverse/data/writes.py: these functions live OUTSIDE callverse/tools/, in no agent
allow-list, so no agent (and no LLM) can call them. Only the Atlas Coordinator and the finance decision call them.

Coordinator order: record_proposal -> checks -> set_proposal_amount -> record_decision("approve") -> one write.
The amount is never the agent's: the Coordinator computes it from the rules and stores it on the proposal, and every
write checks that it pays exactly that amount.

Safety nets, which hold even if the Coordinator has a bug:
- a write needs an approved proposal of the same action, the same booking and the same amount, used once;
- a refund never exceeds paid - refunded, and one rule pays one booking once (the 20 % of AT-HOT-04 cannot be
  claimed twice just because money is still left to refund);
- a compensation is paid once per booking;
- a hotel cancellation and its refund are ONE transaction: both are written, or neither.

Each function returns the new row as a dict, or {"error": ...} if it refuses (it never raises), and writes one trace
line, "db_write" or "db_write_refused" (the same helpers as ShopNova).
"""

import json
from contextlib import closing
from datetime import date

from callverse.config import sim_today
from callverse.data.atlas.db import connect
from callverse.data.seed import COUNTED_REFUND_STATUSES, DECISIONS
from callverse.data.writes import _done, _proposal_row, _refuse, is_valid_amount

ACTIONS = ("refund", "compensation", "cancel_hotel")
COUNTED = ", ".join(f"'{s}'" for s in COUNTED_REFUND_STATUSES)   # our own fixed codes, never from a client


def record_proposal(proposal: dict) -> dict:
    """Save an agent proposal (not decided yet) and return {"id": "AP-0001"}. Its own prefix: ShopNova's proposals
    are numbered P-0001, ... in another database, and the two lists must never be confused."""
    args = {"proposal": proposal}
    if not isinstance(proposal, dict):
        return _refuse("atlas.record_proposal", args, "proposal must be a dict")
    if not isinstance(proposal.get("agent"), str) or not proposal["agent"]:
        return _refuse("atlas.record_proposal", args, "proposal needs an 'agent' (e.g. 'B')")
    if not isinstance(proposal.get("action"), str) or not proposal["action"]:
        return _refuse("atlas.record_proposal", args, "proposal needs an 'action' (e.g. 'refund')")
    if not isinstance(proposal.get("params", {}), dict) or not isinstance(proposal.get("facts_used", {}), dict):
        return _refuse("atlas.record_proposal", args, "'params' and 'facts_used' must be dicts")
    try:
        params = json.dumps(proposal.get("params", {}), allow_nan=False)
        facts = json.dumps(proposal.get("facts_used", {}), allow_nan=False)
    except (TypeError, ValueError) as e:
        return _refuse("atlas.record_proposal", args, f"proposal is not storable as JSON: {e}")

    with closing(connect()) as con:
        con.execute("BEGIN IMMEDIATE")   # the count and the new row together: two proposals cannot take one number
        count = con.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
        proposal_id = f"AP-{count + 1:04d}"
        con.execute("INSERT INTO proposals (id, agent, action, params, rule_id, facts_used, user_confirmed, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (proposal_id, proposal["agent"], proposal["action"], params, proposal.get("rule_id"), facts,
                     1 if proposal.get("user_confirmed") is True else 0, sim_today().isoformat()))
        con.commit()
    return _done("atlas.record_proposal", args, {"id": proposal_id})


def get_proposal(proposal_id: str) -> dict | None:
    """One proposal as a dict (JSON columns turned back into values), or None. A read: it changes nothing."""
    with closing(connect()) as con:
        row = con.execute("SELECT * FROM proposals WHERE id = ?", (str(proposal_id),)).fetchone()
    return _proposal_row(row) if row else None


def set_proposal_amount(proposal_id: str, amount: float) -> dict:
    """Store the amount the Coordinator computed on a proposal that is not decided yet. Returns the proposal."""
    args = {"proposal_id": proposal_id, "amount": amount}
    with closing(connect()) as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT * FROM proposals WHERE id = ?", (str(proposal_id),)).fetchone()
        if row is None:
            return _refuse("atlas.set_proposal_amount", args, f"proposal {proposal_id} not found")
        if row["decision"] is not None:
            return _refuse("atlas.set_proposal_amount", args, f"proposal {proposal_id} already decided: {row['decision']}")
        params = {**json.loads(row["params"]), "amount": round(float(amount), 2)}
        con.execute("UPDATE proposals SET params = ? WHERE id = ?", (json.dumps(params), str(proposal_id)))
        con.commit()
    return _done("atlas.set_proposal_amount", args, get_proposal(proposal_id))


def record_decision(proposal_id: str, decision: str, reason: str) -> dict:
    """Store the Coordinator's decision. A proposal is decided once: a corrected proposal is a NEW proposal."""
    args = {"proposal_id": proposal_id, "decision": decision, "reason": reason}
    if decision not in DECISIONS:
        return _refuse("atlas.record_decision", args, f"unknown decision '{decision}'")
    with closing(connect()) as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT decision FROM proposals WHERE id = ?", (str(proposal_id),)).fetchone()
        if row is None:
            return _refuse("atlas.record_decision", args, f"proposal {proposal_id} not found")
        if row["decision"] is not None:
            return _refuse("atlas.record_decision", args, f"proposal {proposal_id} already decided: {row['decision']}")
        con.execute("UPDATE proposals SET decision = ?, decision_reason = ?, decided_at = ? WHERE id = ?",
                    (decision, reason, sim_today().isoformat(), str(proposal_id)))
        con.commit()
    return _done("atlas.record_decision", args, get_proposal(proposal_id))


# ---------- the safety nets (on the caller's connection, so they share its transaction) ----------

def _approved_proposal(con, proposal_id, action: str, booking_type: str, booking_id) -> tuple[dict | None, str | None]:
    """(proposal, None), or (None, reason to refuse): it exists, is approved, and is this action on this booking."""
    if not proposal_id:
        return None, "safety net: a proposal_id is required"
    row = con.execute("SELECT * FROM proposals WHERE id = ?", (str(proposal_id),)).fetchone()
    if row is None:
        return None, f"safety net: proposal {proposal_id} not found"
    if row["decision"] != "approve":
        return None, f"safety net: proposal {proposal_id} is not approved (decision: {row['decision']})"
    if row["action"] != action:
        return None, f"safety net: proposal {proposal_id} is a '{row['action']}' proposal, not '{action}'"
    params = json.loads(row["params"])
    if params.get("booking_type") != booking_type or params.get("booking_id") != booking_id:
        return None, (f"safety net: proposal {proposal_id} is for {params.get('booking_type')} booking "
                      f"{params.get('booking_id')}, not {booking_type} booking {booking_id}")
    return {"id": row["id"], "params": params, "rule_id": row["rule_id"]}, None


def _same_amount(proposal: dict, amount) -> str | None:
    """None if `amount` is exactly the amount the Coordinator stored on the proposal, else the reason to refuse."""
    approved = proposal["params"].get("amount")
    if approved is None or round(float(approved), 2) != round(float(amount), 2):
        return f"safety net: amount {amount} does not match the approved amount {approved} of proposal {proposal['id']}"
    return None


def _left_to_refund(con, booking_type: str, booking_id: int) -> float | None:
    """paid - refunded for this booking (AT-REF-01), or None if the booking does not exist."""
    table = "hotel_bookings" if booking_type == "hotel" else "flight_bookings"   # our own two names
    booking = con.execute(f"SELECT paid_tnd FROM {table} WHERE id = ?", (int(booking_id),)).fetchone()
    if booking is None:
        return None
    refunded = con.execute(f"SELECT COALESCE(SUM(amount), 0) FROM refunds WHERE booking_type = ? AND booking_id = ?"
                           f" AND status IN ({COUNTED})", (booking_type, int(booking_id))).fetchone()[0]
    return round(booking["paid_tnd"] - refunded, 2)


def _refund_problem(con, booking_type: str, booking_id: int, amount, proposal_id: str) -> str | None:
    """create_refund's safety nets. None = the refund may be written."""
    if not is_valid_amount(amount):
        return "amount must be a finite number above 0"
    proposal, reason = _approved_proposal(con, proposal_id, "refund", booking_type, booking_id)
    if reason:
        return reason
    if con.execute("SELECT 1 FROM refunds WHERE proposal_id = ?", (str(proposal_id),)).fetchone():
        return f"safety net: proposal {proposal_id} was already used for a refund"
    if reason := _same_amount(proposal, amount):
        return reason
    if con.execute(f"SELECT 1 FROM refunds WHERE booking_type = ? AND booking_id = ? AND rule_id = ?"
                   f" AND status IN ({COUNTED})", (booking_type, int(booking_id), proposal["rule_id"])).fetchone():
        return f"safety net: rule {proposal['rule_id']} was already paid for this booking"
    left = _left_to_refund(con, booking_type, booking_id)
    if left is None:
        return f"{booking_type} booking {booking_id} not found"
    if round(float(amount), 2) > left:
        return f"safety net AT-REF-01: amount {amount} > {left} TND left to refund"
    return None


def _compensation_problem(con, booking_type: str, booking_id: int, amount, proposal_id: str) -> str | None:
    """create_compensation's safety nets. None = the compensation may be written."""
    if not is_valid_amount(amount):
        return "amount must be a finite number above 0"
    proposal, reason = _approved_proposal(con, proposal_id, "compensation", booking_type, booking_id)
    if reason:
        return reason
    if con.execute("SELECT 1 FROM compensations WHERE proposal_id = ?", (str(proposal_id),)).fetchone():
        return f"safety net: proposal {proposal_id} was already used for a compensation"
    if reason := _same_amount(proposal, amount):
        return reason
    if con.execute(f"SELECT 1 FROM compensations WHERE booking_type = ? AND booking_id = ? AND status IN ({COUNTED})",
                   (booking_type, int(booking_id))).fetchone():
        return f"safety net: {booking_type} booking {booking_id} already has a compensation"
    return None


def _cancel_problem(con, booking_id: int, proposal_id: str) -> tuple[dict | None, str | None]:
    """cancel_hotel_booking's safety nets: (the proposal, None), or (None, reason to refuse)."""
    proposal, reason = _approved_proposal(con, proposal_id, "cancel_hotel", "hotel", booking_id)
    if reason:
        return None, reason
    booking = con.execute("SELECT status, arrival_date FROM hotel_bookings WHERE id = ?", (int(booking_id),)).fetchone()
    if booking is None:
        return None, f"hotel booking {booking_id} not found"
    if booking["status"] != "confirmed":
        return None, f"only a confirmed booking can be cancelled; booking {booking_id} is {booking['status']}"
    if date.fromisoformat(booking["arrival_date"]) <= sim_today():
        return None, f"booking {booking_id} arrives on {booking['arrival_date']}: too late to cancel"
    amount = proposal["params"].get("amount")
    if amount is None or amount < 0:
        return None, f"safety net: proposal {proposal_id} has no amount"
    if amount > 0 and amount > _left_to_refund(con, "hotel", booking_id):
        return None, f"safety net AT-REF-01: amount {amount} is more than what is left to refund"
    return proposal, None


def _insert_money(con, table: str, booking_type: str, booking_id: int, amount: float, rule_id: str,
                  proposal_id: str) -> dict:
    """Insert a refunds or compensations row (status "approved") on the caller's connection, no commit."""
    cur = con.execute(f"INSERT INTO {table} (booking_type, booking_id, amount, status, rule_id, proposal_id, created_at)"
                      f" VALUES (?, ?, ?, 'approved', ?, ?, ?)",   # table: our own two names
                      (booking_type, int(booking_id), round(float(amount), 2), rule_id, proposal_id,
                       sim_today().isoformat()))
    return dict(con.execute(f"SELECT * FROM {table} WHERE id = ?", (cur.lastrowid,)).fetchone())


def _apply_cancel(con, booking_id: int, proposal: dict) -> dict:
    """Cancel the booking and insert its refund if there is one, on the caller's transaction (no commit)."""
    con.execute("UPDATE hotel_bookings SET status = 'cancelled', cancelled_date = ? WHERE id = ?",
                (sim_today().isoformat(), int(booking_id)))
    amount = proposal["params"]["amount"]
    refund = None
    if amount > 0:
        refund = _insert_money(con, "refunds", "hotel", booking_id, amount, proposal["rule_id"], proposal["id"])
    return {"booking_id": int(booking_id), "status": "cancelled", "cancelled_date": sim_today().isoformat(),
            "refund": refund}


# ---------- the writes ----------

def create_refund(booking_type: str, booking_id: int, amount: float, rule_id: str, proposal_id: str) -> dict:
    """Record an approved refund (status "approved") and return the new refunds row."""
    args = {"booking_type": booking_type, "booking_id": booking_id, "amount": amount, "rule_id": rule_id,
            "proposal_id": proposal_id}
    with closing(connect()) as con:
        con.execute("BEGIN IMMEDIATE")   # the checks and the row together: two refunds cannot both pass the limit
        if reason := _refund_problem(con, booking_type, booking_id, amount, proposal_id):
            return _refuse("atlas.create_refund", args, reason)
        row = _insert_money(con, "refunds", booking_type, booking_id, amount, rule_id, proposal_id)
        con.commit()
    return _done("atlas.create_refund", args, row)


def create_compensation(booking_type: str, booking_id: int, amount: float, rule_id: str, proposal_id: str) -> dict:
    """Record an approved compensation (status "approved") and return the new compensations row."""
    args = {"booking_type": booking_type, "booking_id": booking_id, "amount": amount, "rule_id": rule_id,
            "proposal_id": proposal_id}
    with closing(connect()) as con:
        con.execute("BEGIN IMMEDIATE")
        if reason := _compensation_problem(con, booking_type, booking_id, amount, proposal_id):
            return _refuse("atlas.create_compensation", args, reason)
        row = _insert_money(con, "compensations", booking_type, booking_id, amount, rule_id, proposal_id)
        con.commit()
    return _done("atlas.create_compensation", args, row)


def cancel_hotel_booking(booking_id: int, proposal_id: str) -> dict:
    """Cancel a confirmed hotel booking (cancelled_date = sim today) and write its refund, in ONE transaction.
    The refund's amount and rule are the proposal's (the Coordinator's), 0 = nothing to pay back."""
    args = {"booking_id": booking_id, "proposal_id": proposal_id}
    with closing(connect()) as con:
        con.execute("BEGIN IMMEDIATE")
        proposal, reason = _cancel_problem(con, booking_id, proposal_id)
        if reason:
            return _refuse("atlas.cancel_hotel_booking", args, reason)
        row = _apply_cancel(con, booking_id, proposal)
        con.commit()
    return _done("atlas.cancel_hotel_booking", args, row)


def admin_decide(admin: str, proposal_id: str, approve: bool, reason: str = "", approval_id: int | None = None) -> dict:
    """Finance's decision on a proposal that waits for it, written in ONE transaction: if any part fails, NOTHING is
    written (like ShopNova's admin_decide_refund). The safety nets above run again here, on the same transaction.

    Approve: the decision "approve" + the refund, the compensation, or the cancellation with its refund.
    Refuse (reason required): the decision "layer3"; nothing is paid. The admin's name and reason stay in the
    proposal's decision_reason (Atlas has no admin_actions table yet).
    Returns {"proposal_id", "decision", "refund", "compensation", "booking_status"}.
    """
    function = "atlas.admin_decide"
    args = {"admin": admin, "proposal_id": proposal_id, "approve": approve, "reason": reason,
            "approval_id": approval_id}
    if not isinstance(admin, str) or not admin.strip():
        return _refuse(function, args, "admin (username) is required")
    reason = (reason or "").strip()
    if not approve and not reason:
        return _refuse(function, args, "a reason is required to refuse")
    decision = "approve" if approve else "layer3"
    note = (f"AT-ESC-01: {'approved' if approve else 'refused'} by the Atlas admin ({admin})"
            + (f": {reason}" if reason else ""))
    try:
        with closing(connect()) as con:
            con.execute("BEGIN IMMEDIATE")   # everything below is committed together, or not at all
            row = con.execute("SELECT * FROM proposals WHERE id = ?", (str(proposal_id),)).fetchone()
            if row is None:
                return _refuse(function, args, f"proposal {proposal_id} not found")
            if row["decision"] is not None:
                return _refuse(function, args, f"proposal {proposal_id} already decided: {row['decision']}")
            if row["action"] not in ACTIONS:
                return _refuse(function, args, f"proposal {proposal_id} is a '{row['action']}' proposal")
            params = json.loads(row["params"])
            booking_type, booking_id, amount = params.get("booking_type"), params.get("booking_id"), params.get("amount")
            con.execute("UPDATE proposals SET decision = ?, decision_reason = ?, decided_at = ? WHERE id = ?",
                        (decision, note, sim_today().isoformat(), str(proposal_id)))
            refund, compensation, status = None, None, None
            if approve and row["action"] == "refund":
                if problem := _refund_problem(con, booking_type, booking_id, amount, proposal_id):
                    return _refuse(function, args, problem)                  # closing without commit = rollback
                refund = _insert_money(con, "refunds", booking_type, booking_id, amount, row["rule_id"], proposal_id)
            elif approve and row["action"] == "compensation":
                if problem := _compensation_problem(con, booking_type, booking_id, amount, proposal_id):
                    return _refuse(function, args, problem)
                compensation = _insert_money(con, "compensations", booking_type, booking_id, amount, row["rule_id"],
                                             proposal_id)
            elif approve:
                proposal, problem = _cancel_problem(con, booking_id, proposal_id)
                if problem:
                    return _refuse(function, args, problem)
                cancelled = _apply_cancel(con, booking_id, proposal)
                refund, status = cancelled["refund"], cancelled["status"]
            con.commit()
    except Exception as e:   # any failure: the transaction is not committed, so nothing is written
        return _refuse(function, args, f"nothing was written: {type(e).__name__}: {e}")
    return _done(function, args, {"proposal_id": str(proposal_id), "decision": decision, "refund": refund,
                                  "compensation": compensation, "booking_status": status})
