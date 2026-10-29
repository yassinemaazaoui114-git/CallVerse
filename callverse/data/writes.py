"""ShopNova WRITE functions: the only code that changes ShopNova data.

Rule: only the Coordinator writes. These functions live here, OUTSIDE callverse/tools/, and are
never put in the tool registry or in any agent allow-list, so no agent (and no LLM) can call them.
The Coordinator calls them after its checks; scripts/advance_status.py calls set_order_status
to play the carrier during demo S3. T17: create_order is called by the ShopNova app (a client buys),
for the logged-in user only.

Coordinator order: record_proposal -> checks -> record_decision("approve") -> create_refund / create_subscription.
Both writes refuse unless their proposal_id is a recorded, approved proposal whose action and params match
EXACTLY what is being written (same order, same amount / same event), used only once.

Each function:
- does basic data checks (order exists, valid codes) plus two safety nets that hold even if the
  Coordinator has a bug: a refund never exceeds what is left to refund, and order statuses only
  move in allowed steps. Policy checks (days late, user confirmation...) are the Coordinator's job;
- returns the new row as a dict, or {"error": ...} if it refuses (it never raises);
- writes one trace line: "db_write" when it wrote, "db_write_refused" when it refused.

Dates use the fixed simulation date (sim_today), so demo runs stay reproducible.
"""

import json
import math
from contextlib import closing
from datetime import timedelta

from callverse import trace
from callverse.config import sim_today
from callverse.data.db import connect
from callverse.data.seed import (ALWAYS_ALLOWED, COUNTED_REFUND_STATUSES, DECISIONS, NOTIFICATION_EVENTS,
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


def _proposal_row(row) -> dict:
    """A proposals row as a dict, with the JSON columns turned back into Python values."""
    p = dict(row)
    p["params"], p["facts_used"] = json.loads(p["params"]), json.loads(p["facts_used"])
    p["user_confirmed"] = bool(p["user_confirmed"])
    return p


def record_proposal(proposal: dict) -> dict:
    """Save an agent proposal (not decided yet) and return {"id": "P-0001"} (then "P-0002", ...).

    proposal = {"agent": "B", "action": "refund", "params": {"order_id": 4512, "amount": 59.90},
                "rule_id": "R-REF-03", "facts_used": {...}, "user_confirmed": true}
    Other keys (e.g. "user_quote") are ignored. Returns {"error": ...} if a required field is wrong.
    Always a dict, never a bare string.
    """
    args = {"proposal": proposal}
    if not isinstance(proposal, dict):
        return _refuse("record_proposal", args, "proposal must be a dict")
    if not isinstance(proposal.get("agent"), str) or not proposal["agent"]:
        return _refuse("record_proposal", args, "proposal needs an 'agent' (e.g. 'B')")
    if not isinstance(proposal.get("action"), str) or not proposal["action"]:
        return _refuse("record_proposal", args, "proposal needs an 'action' (e.g. 'refund')")
    if not isinstance(proposal.get("params", {}), dict) or not isinstance(proposal.get("facts_used", {}), dict):
        return _refuse("record_proposal", args, "'params' and 'facts_used' must be dicts")
    try:
        params = json.dumps(proposal.get("params", {}), allow_nan=False)
        facts = json.dumps(proposal.get("facts_used", {}), allow_nan=False)
    except (TypeError, ValueError) as e:  # e.g. NaN or an object JSON cannot store
        return _refuse("record_proposal", args, f"proposal is not storable as JSON: {e}")

    with closing(connect()) as con:
        count = con.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
        proposal_id = f"P-{count + 1:04d}"   # rows are never deleted, so the count gives the next number
        con.execute(
            "INSERT INTO proposals (id, agent, action, params, rule_id, facts_used, user_confirmed, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (proposal_id, proposal["agent"], proposal["action"], params, proposal.get("rule_id"), facts,
             1 if proposal.get("user_confirmed") is True else 0, sim_today().isoformat()),
        )
        con.commit()
    return _done("record_proposal", args, {"id": proposal_id})


def record_decision(proposal_id: str, decision: str, reason: str) -> dict:
    """Store the Coordinator's decision on a proposal and return the updated proposals row.

    decision: approve | send_back | ask_user | ask_proof | layer3 | escalate.
    A proposal is decided once (the audit trail is never rewritten): a corrected proposal is a NEW proposal.
    """
    args = {"proposal_id": proposal_id, "decision": decision, "reason": reason}
    if decision not in DECISIONS:
        return _refuse("record_decision", args, f"unknown decision '{decision}' (allowed: {', '.join(DECISIONS)})")
    with closing(connect()) as con:
        row = con.execute("SELECT * FROM proposals WHERE id = ?", (str(proposal_id),)).fetchone()
        if row is None:
            return _refuse("record_decision", args, f"proposal {proposal_id} not found")
        if row["decision"] is not None:
            return _refuse("record_decision", args, f"proposal {proposal_id} already decided: {row['decision']}")
        con.execute("UPDATE proposals SET decision = ?, decision_reason = ?, decided_at = ? WHERE id = ?",
                    (decision, reason, sim_today().isoformat(), str(proposal_id)))
        con.commit()
        result = _proposal_row(con.execute("SELECT * FROM proposals WHERE id = ?", (str(proposal_id),)).fetchone())
    return _done("record_decision", args, result)


def _approved_proposal(con, proposal_id, action: str, order_id) -> tuple[dict | None, str | None]:
    """Find the proposal behind a write and check it. Returns (proposal, None) or (None, reason to refuse).

    Checks: it exists, its decision is "approve", its action is `action`, and its params.order_id is order_id.
    """
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
    if params.get("order_id") is None or int(params["order_id"]) != int(order_id):
        return None, f"safety net: proposal {proposal_id} is for order {params.get('order_id')}, not {order_id}"
    return {"id": row["id"], "params": params}, None


def create_refund(order_id: int, amount: float, rule_id: str, proposal_id: str) -> dict:
    """Record an approved refund (status "approved") and return the new refunds row.

    Safety nets (checked here too, independently of the Coordinator's own checks):
    - proposal_id must be a recorded proposal, decided "approve", with action "refund", for this same
      order, for this same amount (rounded to 2 decimals), and not used already by another refund.
      So an approval for 10.00 TND can never pay 378.00 TND (which would also skip Layer 3);
    - R-REF-05: refused if amount > paid - refunded_total (approved and completed refunds count).
    """
    args = {"order_id": order_id, "amount": amount, "rule_id": rule_id, "proposal_id": proposal_id}
    if not is_valid_amount(amount):
        return _refuse("create_refund", args, "amount must be a finite number above 0")

    with closing(connect()) as con:
        proposal, reason = _approved_proposal(con, proposal_id, "refund", order_id)
        if reason:
            return _refuse("create_refund", args, reason)
        if con.execute("SELECT 1 FROM refunds WHERE proposal_id = ?", (str(proposal_id),)).fetchone():
            return _refuse("create_refund", args, f"safety net: proposal {proposal_id} was already used for a refund")
        approved_amount = proposal["params"].get("amount")
        if not is_valid_amount(approved_amount) or round(float(approved_amount), 2) != round(float(amount), 2):
            return _refuse("create_refund", args,
                           f"safety net: amount {amount} does not match the approved amount {approved_amount}"
                           f" of proposal {proposal_id}")

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


def mark_subscription_sent(subscription_id: int) -> dict:
    """The notifier sent the message: set the subscription to "sent" and return the updated row.

    Refused if the subscription does not exist or is not "waiting" (a notification is sent once).
    """
    args = {"subscription_id": subscription_id}
    with closing(connect()) as con:
        row = con.execute("SELECT status FROM subscriptions WHERE id = ?", (int(subscription_id),)).fetchone()
        if row is None:
            return _refuse("mark_subscription_sent", args, f"subscription {subscription_id} not found")
        if row["status"] != "waiting":
            return _refuse("mark_subscription_sent", args,
                           f"subscription {subscription_id} is '{row['status']}', not 'waiting'")
        con.execute("UPDATE subscriptions SET status = 'sent' WHERE id = ?", (int(subscription_id),))
        con.commit()
        result = dict(con.execute("SELECT * FROM subscriptions WHERE id = ?", (int(subscription_id),)).fetchone())
    return _done("mark_subscription_sent", args, result)


def create_subscription(order_id: int, event: str, proposal_id: str | None = None) -> dict:
    """Record that the client wants a notification for `event` (status "waiting").

    Refused if the event is not one of the R-NOT-01 events (shipped, out_for_delivery, delivered).
    Safety net, like create_refund: proposal_id must be a recorded proposal, decided "approve", with action
    "subscribe", params.order_id = order_id, params.event = event, and not used already for a subscription.
    """
    args = {"order_id": order_id, "event": event, "proposal_id": proposal_id}
    if event not in NOTIFICATION_EVENTS:
        return _refuse("create_subscription", args,
                       f"event '{event}' is not allowed (R-NOT-01: {', '.join(NOTIFICATION_EVENTS)})")

    with closing(connect()) as con:
        proposal, reason = _approved_proposal(con, proposal_id, "subscribe", order_id)
        if reason:
            return _refuse("create_subscription", args, reason)
        if proposal["params"].get("event") != event:
            return _refuse("create_subscription", args,
                           f"safety net: event '{event}' does not match the approved event"
                           f" '{proposal['params'].get('event')}' of proposal {proposal_id}")
        if con.execute("SELECT 1 FROM subscriptions WHERE proposal_id = ?", (str(proposal_id),)).fetchone():
            return _refuse("create_subscription", args,
                           f"safety net: proposal {proposal_id} was already used for a subscription")
        if not _order_exists(con, int(order_id)):
            return _refuse("create_subscription", args, f"order {order_id} not found")
        cur = con.execute(
            "INSERT INTO subscriptions (order_id, event, status, created_at, proposal_id)"
            " VALUES (?, ?, 'waiting', ?, ?)",
            (int(order_id), event, sim_today().isoformat(), str(proposal_id)),
        )
        con.commit()
        row = dict(con.execute("SELECT * FROM subscriptions WHERE id = ?", (cur.lastrowid,)).fetchone())
    return _done("create_subscription", args, row)


PAYMENT_METHODS = ("card", "cash_on_delivery")   # company_profile.json payment_methods
MAX_ORDER_QTY = 10


def create_order(user_id: int, product_id: int, quantity: int, payment: str) -> dict:
    """A client buys one product in the ShopNova app (T17): a new "processing" order; the stock goes down.

    NOT a Coordinator write and never in an agent allow-list: only the ShopNova app calls it, for the user
    who is logged in (the app checks the login first). Checks: the user exists; the product exists and has
    enough stock; quantity is a whole number 1-10; payment is card or cash_on_delivery.
    - paid = total for card, 0 for cash on delivery (paid when delivered, like order 4514). The payment
      method itself is not stored: the orders table has no column for it (paid = 0 says cash on delivery);
    - order_date = sim today, promised_date = today + the profile's median delivery promise (25 days);
    - items = one line {product_id, name, qty, price} like the other orders, price = the unit price. No
      "Delivery" line: the shop's delivery fee is 0 for now (the real Olist orders carry their real freight);
    - labels: ai_generated = 0, scripted = 0, source NULL (= written at run time, docs/platform_contract.md).
    """
    args = {"user_id": user_id, "product_id": product_id, "quantity": quantity, "payment": payment}
    if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= MAX_ORDER_QTY:
        return _refuse("create_order", args, f"quantity must be a whole number from 1 to {MAX_ORDER_QTY}")
    if payment not in PAYMENT_METHODS:
        return _refuse("create_order", args, f"payment '{payment}' is not allowed ({', '.join(PAYMENT_METHODS)})")
    for name in ("user_id", "product_id"):
        if isinstance(args[name], bool) or not isinstance(args[name], int):
            return _refuse("create_order", args, f"{name} must be a whole number")

    from callverse.tools.shopnova_tools import get_company_profile   # imported here like clock._apply
    promise_days = get_company_profile().get("delivery_promise_days", {}).get("median")
    if not isinstance(promise_days, int):
        return _refuse("create_order", args, "company profile has no delivery promise (median days)")
    today = sim_today()

    with closing(connect()) as con:
        con.execute("BEGIN IMMEDIATE")   # stock check and stock decrease happen together
        if con.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
            return _refuse("create_order", args, f"user {user_id} not found")
        product = con.execute("SELECT id, name, price, stock FROM products WHERE id = ?", (product_id,)).fetchone()
        if product is None:
            return _refuse("create_order", args, f"product {product_id} not found")
        if product["stock"] < quantity:
            return _refuse("create_order", args,
                           f"not enough stock for product {product_id}: {product['stock']} left, {quantity} asked")
        total = round(product["price"] * quantity, 2)
        items = [{"product_id": product["id"], "name": product["name"], "qty": quantity, "price": product["price"]}]
        order_id = con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM orders").fetchone()[0]
        con.execute(
            "INSERT INTO orders (id, user_id, items, total, paid, status, order_date, promised_date, delivered_date,"
            " carrier, tracking_number, source, source_id, ai_generated, scripted)"
            " VALUES (?, ?, ?, ?, ?, 'processing', ?, ?, NULL, NULL, NULL, NULL, NULL, 0, 0)",
            (order_id, user_id, json.dumps(items), total, total if payment == "card" else 0.0,
             today.isoformat(), (today + timedelta(days=promise_days)).isoformat()))
        con.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (quantity, product_id))
        con.commit()
        row = dict(con.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone())
    row["items"] = json.loads(row["items"])
    return _done("create_order", args, row)


def set_order_status(order_id: int, new_status: str) -> dict:
    """Change an order's status. If the new status is a notification event, also add an `events` row.

    Allowed moves only (STATUS_MOVES in seed.py): processing -> shipped -> out_for_delivery -> delivered,
    shipped -> stuck_at_depot -> out_for_delivery, and any status -> cancelled or refunded. Anything else is refused.
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
