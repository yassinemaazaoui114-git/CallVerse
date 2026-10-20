"""ShopNova WRITE functions: the only code that changes ShopNova data.

Rule: only the Coordinator writes. These functions live here, OUTSIDE callverse/tools/, and are
never put in the tool registry or in any agent allow-list, so no agent (and no LLM) can call them.
The Coordinator calls them after its checks; scripts/advance_status.py calls set_order_status
to play the carrier during demo S3.

Each function:
- does basic data checks (order exists, valid codes) plus two safety nets that hold even if the
  Coordinator has a bug: a refund never exceeds what is left to refund, and order statuses only
  move in allowed steps. Policy checks (days late, user confirmation...) are the Coordinator's job;
- returns the new row as a dict, or {"error": ...} if it refuses (it never raises);
- writes one trace line: "db_write" when it wrote, "db_write_refused" when it refused.

Dates use the fixed simulation date (sim_today), so demo runs stay reproducible.
"""

import math
from contextlib import closing

from callverse import trace
from callverse.config import sim_today
from callverse.data.db import connect
from callverse.data.seed import (ALWAYS_ALLOWED, COUNTED_REFUND_STATUSES, NOTIFICATION_EVENTS,
                                 ORDER_STATUSES, STATUS_MOVES)


def _refuse(function: str, args: dict, reason: str) -> dict:
    """Trace a refused write and return the error dict."""
    trace.log("db_write_refused", "platform", {"function": function, "args": args, "reason": reason})
    return {"error": reason}


def _done(function: str, args: dict, result: dict) -> dict:
    """Trace a successful write and return its result."""
    trace.log("db_write", "platform", {"function": function, "args": args, "result": result})
    return result


def is_valid_amount(amount) -> bool:
    """True only for a real, finite number above 0.

    Refused: text ("59.90"), True/False (bool is a kind of int in Python), NaN and infinity.
    NaN matters because json.loads accepts it, so an LLM tool argument could carry it, and
    NaN slips through "amount <= 0" (every comparison with NaN is False).
    """
    return (isinstance(amount, (int, float)) and not isinstance(amount, bool)
            and math.isfinite(amount) and amount > 0)


def _order_exists(con, order_id: int) -> bool:
    return con.execute("SELECT 1 FROM orders WHERE id = ?", (order_id,)).fetchone() is not None


def create_refund(order_id: int, amount: float, rule_id: str, proposal_id: str) -> dict:
    """Record an approved refund (status "approved") and return the new refunds row.

    Safety net (R-REF-05, checked here too, independently of the Coordinator): refused if
    amount > paid - refunded_total, where refunded_total counts approved and completed refunds.
    """
    args = {"order_id": order_id, "amount": amount, "rule_id": rule_id, "proposal_id": proposal_id}
    if not is_valid_amount(amount):
        return _refuse("create_refund", args, "amount must be a finite number above 0")

    with closing(connect()) as con:
        order = con.execute("SELECT paid FROM orders WHERE id = ?", (int(order_id),)).fetchone()
        if order is None:
            return _refuse("create_refund", args, f"order {order_id} not found")
        marks = ", ".join("?" for _ in COUNTED_REFUND_STATUSES)
        refunded_total = con.execute(
            f"SELECT COALESCE(SUM(amount), 0) FROM refunds WHERE order_id = ? AND status IN ({marks})",
            (int(order_id), *COUNTED_REFUND_STATUSES)).fetchone()[0]
        left = round(order["paid"] - refunded_total, 2)
        if round(float(amount), 2) > left:
            return _refuse("create_refund", args,
                           f"safety net R-REF-05: amount {amount} > paid {order['paid']} - refunded {refunded_total}"
                           f" = {left} TND")
        cur = con.execute(
            "INSERT INTO refunds (order_id, amount, status, rule_id, proposal_id, created_at)"
            " VALUES (?, ?, 'approved', ?, ?, ?)",
            (int(order_id), round(float(amount), 2), rule_id, proposal_id, sim_today().isoformat()),
        )
        con.commit()
        row = dict(con.execute("SELECT * FROM refunds WHERE id = ?", (cur.lastrowid,)).fetchone())
    return _done("create_refund", args, row)


def create_subscription(order_id: int, event: str) -> dict:
    """Record that the client wants a notification for `event` (status "waiting").

    Refused if the event is not one of the R-NOT-01 events (shipped, out_for_delivery, delivered).
    """
    args = {"order_id": order_id, "event": event}
    if event not in NOTIFICATION_EVENTS:
        return _refuse("create_subscription", args,
                       f"event '{event}' is not allowed (R-NOT-01: {', '.join(NOTIFICATION_EVENTS)})")

    with closing(connect()) as con:
        if not _order_exists(con, int(order_id)):
            return _refuse("create_subscription", args, f"order {order_id} not found")
        cur = con.execute(
            "INSERT INTO subscriptions (order_id, event, status, created_at) VALUES (?, ?, 'waiting', ?)",
            (int(order_id), event, sim_today().isoformat()),
        )
        con.commit()
        row = dict(con.execute("SELECT * FROM subscriptions WHERE id = ?", (cur.lastrowid,)).fetchone())
    return _done("create_subscription", args, row)


def set_order_status(order_id: int, new_status: str) -> dict:
    """Change an order's status. If the new status is a notification event, also add an `events` row.

    Allowed moves only (STATUS_MOVES in seed.py): processing -> shipped -> out_for_delivery -> delivered,
    stuck_at_depot -> out_for_delivery, and any status -> cancelled or refunded. Anything else is refused.
    Returns {"order_id", "old_status", "new_status", "event"} where event is the new events row or None.
    When the status becomes "delivered", delivered_date is set to sim_today (if it was empty),
    so get_tracking reports the order as delivered.
    """
    args = {"order_id": order_id, "new_status": new_status}
    if new_status not in ORDER_STATUSES:
        return _refuse("set_order_status", args,
                       f"unknown status '{new_status}' (allowed: {', '.join(ORDER_STATUSES)})")

    today = sim_today().isoformat()
    with closing(connect()) as con:
        row = con.execute("SELECT status FROM orders WHERE id = ?", (int(order_id),)).fetchone()
        if row is None:
            return _refuse("set_order_status", args, f"order {order_id} not found")
        old_status = row["status"]
        allowed = new_status in STATUS_MOVES.get(old_status, ()) or new_status in ALWAYS_ALLOWED
        if new_status == old_status or not allowed:
            return _refuse("set_order_status", args,
                           f"move {old_status} -> {new_status} is not allowed")

        con.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, int(order_id)))
        if new_status == "delivered":
            con.execute("UPDATE orders SET delivered_date = ? WHERE id = ? AND delivered_date IS NULL",
                        (today, int(order_id)))

        event = None
        if new_status in NOTIFICATION_EVENTS:
            cur = con.execute("INSERT INTO events (order_id, event, at) VALUES (?, ?, ?)",
                              (int(order_id), new_status, today))
            event = dict(con.execute("SELECT * FROM events WHERE id = ?", (cur.lastrowid,)).fetchone())
        con.commit()

    result = {"order_id": int(order_id), "old_status": old_status, "new_status": new_status, "event": event}
    return _done("set_order_status", args, result)
