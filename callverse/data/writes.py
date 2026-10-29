"""ShopNova WRITE functions: the only code that changes ShopNova data.

Rule: only the Coordinator writes. These functions live here, OUTSIDE callverse/tools/, and are
never put in the tool registry or in any agent allow-list, so no agent (and no LLM) can call them.
The Coordinator calls them after its checks; scripts/advance_status.py calls set_order_status
to play the carrier during demo S3. T17: create_order is called by the ShopNova app (a client buys),
for the logged-in user only. T18: the ShopNova ADMIN's writes (products, order status, users, the refund
decisions of Refund approvals) are at the end of this file; the app calls them after require_permission. Each one adds an
`admin_actions` row (who, when, before, after) in the SAME transaction as the change, so a change without its
log line cannot happen. Nothing is ever deleted (a product is deactivated, an order cancelled).

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
import re
from contextlib import closing
from datetime import timedelta

from callverse import trace
from callverse.config import sim_today
from callverse.data import clock
from callverse.data.db import connect
from callverse.data.seed import (ALWAYS_ALLOWED, COUNTED_REFUND_STATUSES, DECISIONS, NOTIFICATION_EVENTS,
                                 ORDER_STATUSES, PAYMENT_METHODS, STATUS_MOVES)


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
    with closing(connect()) as con:
        reason = _refund_problem(con, order_id, amount, proposal_id)
        if reason:
            return _refuse("create_refund", args, reason)
        row = _insert_refund(con, order_id, amount, rule_id, proposal_id)
        con.commit()
    return _done("create_refund", args, row)


def _refund_problem(con, order_id: int, amount: float, proposal_id: str) -> str | None:
    """create_refund's safety nets (see above), on the caller's connection. None = the refund may be written.
    Also used by admin_decide_refund (T18 follow-up), inside its single transaction."""
    if not is_valid_amount(amount):
        return "amount must be a finite number above 0"
    proposal, reason = _approved_proposal(con, proposal_id, "refund", order_id)
    if reason:
        return reason
    if con.execute("SELECT 1 FROM refunds WHERE proposal_id = ?", (str(proposal_id),)).fetchone():
        return f"safety net: proposal {proposal_id} was already used for a refund"
    approved_amount = proposal["params"].get("amount")
    if not is_valid_amount(approved_amount) or round(float(approved_amount), 2) != round(float(amount), 2):
        return (f"safety net: amount {amount} does not match the approved amount {approved_amount}"
                f" of proposal {proposal_id}")
    order = con.execute("SELECT paid FROM orders WHERE id = ?", (int(order_id),)).fetchone()
    if order is None:
        return f"order {order_id} not found"
    marks = ", ".join("?" for _ in COUNTED_REFUND_STATUSES)
    refunded_total = con.execute(
        f"SELECT COALESCE(SUM(amount), 0) FROM refunds WHERE order_id = ? AND status IN ({marks})",
        (int(order_id), *COUNTED_REFUND_STATUSES)).fetchone()[0]
    left = round(order["paid"] - refunded_total, 2)
    if round(float(amount), 2) > left:
        return f"safety net R-REF-05: amount {amount} > paid {order['paid']} - refunded {refunded_total} = {left} TND"
    return None


def _insert_refund(con, order_id: int, amount: float, rule_id: str, proposal_id: str) -> dict:
    """Insert the refunds row (status "approved") on the caller's connection, no commit. Returns the row."""
    cur = con.execute("INSERT INTO refunds (order_id, amount, status, rule_id, proposal_id, created_at)"
                      " VALUES (?, ?, 'approved', ?, ?, ?)",
                      (int(order_id), round(float(amount), 2), rule_id, proposal_id, sim_today().isoformat()))
    return dict(con.execute("SELECT * FROM refunds WHERE id = ?", (cur.lastrowid,)).fetchone())


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


MAX_ORDER_QTY = 10


def create_order(user_id: int, product_id: int, quantity: int, payment: str) -> dict:
    """A client buys one product in the ShopNova app (T17): a new "processing" order; the stock goes down.

    NOT a Coordinator write and never in an agent allow-list: only the ShopNova app calls it, for the user
    who is logged in (the app checks the login first). Checks: the user exists; the product exists and has
    enough stock; quantity is a whole number 1-10; payment is card or cash_on_delivery.
    - paid = total for card, 0 for cash on delivery (paid when delivered, like order 4514); the method is
      stored in the `payment` column (T17 follow-up Q2);
    - order_date = sim today, promised_date = today + the profile's median delivery promise (25 days);
    - items = one line {product_id, name, qty, price} like the other orders, price = the unit price. No
      "Delivery" line: the shop's delivery fee is 0 for now (the real Olist orders carry their real freight);
    - labels: ai_generated = 0, scripted = 0, source = 'app' (T17 follow-up Q1, docs/platform_contract.md).
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
        product = con.execute("SELECT id, name, price, stock, active FROM products WHERE id = ?",
                              (product_id,)).fetchone()
        if product is None:
            return _refuse("create_order", args, f"product {product_id} not found")
        if not product["active"]:   # T18: removed from the shop by the admin
            return _refuse("create_order", args, f"product {product_id} is not on sale any more")
        if product["stock"] < quantity:
            return _refuse("create_order", args,
                           f"not enough stock for product {product_id}: {product['stock']} left, {quantity} asked")
        total = round(product["price"] * quantity, 2)
        items = [{"product_id": product["id"], "name": product["name"], "qty": quantity, "price": product["price"]}]
        order_id = con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM orders").fetchone()[0]
        con.execute(
            "INSERT INTO orders (id, user_id, items, total, paid, status, order_date, promised_date, delivered_date,"
            " carrier, tracking_number, payment, source, source_id, ai_generated, scripted)"
            " VALUES (?, ?, ?, ?, ?, 'processing', ?, ?, NULL, NULL, NULL, ?, 'app', NULL, 0, 0)",
            (order_id, user_id, json.dumps(items), total, total if payment == "card" else 0.0,
             today.isoformat(), (today + timedelta(days=promise_days)).isoformat(), payment))
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

        event = _apply_status(con, int(order_id), new_status, today)
        con.commit()

    result = {"order_id": int(order_id), "old_status": old_status, "new_status": new_status, "event": event}
    return _done("set_order_status", args, result)


def _apply_status(con, order_id: int, new_status: str, today: str) -> dict | None:
    """Write a status change already checked by the caller (no commit). Returns the new events row or None.
    Used by set_order_status and by the admin's admin_set_order_status (T18), so both write it the same way."""
    con.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))
    if new_status == "delivered":
        con.execute("UPDATE orders SET delivered_date = ? WHERE id = ? AND delivered_date IS NULL",
                    (today, order_id))
    if new_status not in NOTIFICATION_EVENTS:
        return None
    cur = con.execute("INSERT INTO events (order_id, event, at) VALUES (?, ?, ?)", (order_id, new_status, today))
    return dict(con.execute("SELECT * FROM events WHERE id = ?", (cur.lastrowid,)).fetchone())


# ---------------------------------------------------------------------------
# T18: the ShopNova ADMIN's writes. Called only by the ShopNova app's admin pages (after require_permission)
# and by callverse/channels/approvals.py. Never in an agent allow-list (tests/test_admin_writes.py checks it).
# All take `admin` = the admin's username, return the new row or {"error": ...}, and log an admin_actions row.
# ---------------------------------------------------------------------------

MAX_NAME_LEN = 100
MAX_PRICE_TND = 100_000
MAX_STOCK = 100_000
PRODUCT_FIELDS = ("name", "category", "price", "stock")
USER_FIELDS = ("name", "email", "phone", "city")
# The admin may move an order like the carrier does (STATUS_MOVES), and cancel it while it is not shipped yet.
# "refunded" is never set by hand: a refund goes only through Refund approvals (or the Coordinator).
ADMIN_CANCEL_FROM = ("processing",)
PAID_CANCEL_MESSAGE = "This order is paid: it must be refunded first."


def _log_action(con, admin: str, action: str, table: str, target_id, before: dict | None, after: dict | None) -> None:
    """Add the admin_actions row on the SAME connection (same transaction) as the change it describes."""
    con.execute("INSERT INTO admin_actions (at, admin, action, target_table, target_id, before, after)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (clock.now().isoformat(timespec="seconds"), admin, action, table, str(target_id),
                 None if before is None else json.dumps(before, ensure_ascii=False),
                 None if after is None else json.dumps(after, ensure_ascii=False)))


def _bad_admin(admin) -> str | None:
    return None if isinstance(admin, str) and admin.strip() else "admin (username) is required"


def _clean_name(name) -> tuple[str | None, str | None]:
    """(name trimmed, None) or (None, reason): not empty, at most MAX_NAME_LEN characters."""
    if not isinstance(name, str) or not name.strip():
        return None, "name must not be empty"
    if len(name.strip()) > MAX_NAME_LEN:
        return None, f"name must be at most {MAX_NAME_LEN} characters"
    return name.strip(), None


def _clean_price(price) -> tuple[float | None, str | None]:
    """A price in TND: a number > 0 and <= 100,000 with at most 2 decimals."""
    if not is_valid_amount(price) or price > MAX_PRICE_TND:
        return None, f"price must be a number above 0 and at most {MAX_PRICE_TND:,} TND"
    if abs(round(float(price), 2) - float(price)) > 1e-9:
        return None, "price must have at most 2 decimals"
    return round(float(price), 2), None


def _clean_stock(stock) -> tuple[int | None, str | None]:
    if isinstance(stock, bool) or not isinstance(stock, int) or not 0 <= stock <= MAX_STOCK:
        return None, f"stock must be a whole number from 0 to {MAX_STOCK:,}"
    return stock, None


def _clean_phone(phone) -> tuple[str | None, str | None]:
    """8 Tunisian digits (spaces, dashes and a +216 / 216 prefix are allowed), stored as "+216 XX XXX XXX"."""
    digits = re.sub(r"[\s\-]", "", phone) if isinstance(phone, str) else ""
    digits = re.sub(r"^\+?216(?=\d{8}$)", "", digits)
    if not re.fullmatch(r"\d{8}", digits):
        return None, "phone must be 8 digits (e.g. 20 123 456)"
    return f"+216 {digits[:2]} {digits[2:5]} {digits[5:]}", None


def _clean_email(email) -> tuple[str | None, str | None]:
    if not isinstance(email, str) or "@" not in email.strip() or len(email.strip()) > MAX_NAME_LEN:
        return None, "email must contain '@'"
    return email.strip(), None


def _categories(con) -> list[str]:
    """The existing product categories (an admin product must use one of them)."""
    return [r[0] for r in con.execute("SELECT DISTINCT category FROM products WHERE category IS NOT NULL"
                                      " ORDER BY category").fetchall()]


def _cities() -> list[str]:
    from callverse.tools.shopnova_tools import get_company_profile   # imported here like create_order
    return get_company_profile().get("cities_served", [])


def _check_product_fields(con, fields: dict) -> tuple[dict, str | None]:
    """Check and clean the given product fields. Returns (clean fields, None) or ({}, reason)."""
    clean = {}
    for name, value in fields.items():
        if name == "name":
            value, reason = _clean_name(value)
        elif name == "price":
            value, reason = _clean_price(value)
        elif name == "stock":
            value, reason = _clean_stock(value)
        elif name == "category":
            reason = None if value in _categories(con) else f"category '{value}' is not one of the shop's categories"
        else:
            reason = f"field '{name}' cannot be changed (allowed: {', '.join(PRODUCT_FIELDS)})"
        if reason:
            return {}, reason
        clean[name] = value
    return clean, None


def _check_user_fields(con, fields: dict, user_id: int | None) -> tuple[dict, str | None]:
    """Check and clean the given user fields (email and phone unique among the OTHER users)."""
    clean = {}
    for name, value in fields.items():
        if name == "name":
            value, reason = _clean_name(value)
        elif name == "email":
            value, reason = _clean_email(value)
            if not reason and con.execute("SELECT 1 FROM users WHERE lower(email) = lower(?) AND id IS NOT ?",
                                          (value, user_id)).fetchone():
                reason = f"email {value} is already used by another user"
        elif name == "phone":
            value, reason = _clean_phone(value)
            if not reason and con.execute("SELECT 1 FROM users WHERE phone = ? AND id IS NOT ?",
                                          (value, user_id)).fetchone():
                reason = f"phone {value} is already used by another user"
        elif name == "city":
            reason = None if value in _cities() else f"city '{value}' is not a city ShopNova serves"
        else:
            reason = f"field '{name}' cannot be changed (allowed: {', '.join(USER_FIELDS)})"
        if reason:
            return {}, reason
        clean[name] = value
    return clean, None


def _row(con, table: str, row_id) -> dict | None:
    row = con.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()   # table: our own names only
    return dict(row) if row else None


def create_product(admin: str, name: str, category: str, price: float, stock: int) -> dict:
    """Add a product to the shop (active). New id = max + 1; source 'app', ai_generated 0, scripted 0."""
    function, args = "create_product", {"admin": admin, "name": name, "category": category, "price": price,
                                        "stock": stock}
    if reason := _bad_admin(admin):
        return _refuse(function, args, reason)
    with closing(connect()) as con:
        con.execute("BEGIN IMMEDIATE")   # the new id, the row and its log line are written together
        clean, reason = _check_product_fields(con, {"name": name, "category": category, "price": price,
                                                    "stock": stock})
        if reason:
            return _refuse(function, args, reason)
        product_id = con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM products").fetchone()[0]
        con.execute("INSERT INTO products (id, name, price, stock, category, active, source, ai_generated, scripted)"
                    " VALUES (?, ?, ?, ?, ?, 1, 'app', 0, 0)",
                    (product_id, clean["name"], clean["price"], clean["stock"], clean["category"]))
        row = _row(con, "products", product_id)
        _log_action(con, admin, function, "products", product_id, None, row)
        con.commit()
    return _done(function, args, row)


def update_product(admin: str, product_id: int, **fields) -> dict:
    """Change a product's name / category / price / stock. Old orders keep the price stored in their items."""
    function, args = "update_product", {"admin": admin, "product_id": product_id, **fields}
    if reason := _bad_admin(admin):
        return _refuse(function, args, reason)
    if not fields:
        return _refuse(function, args, "nothing to change")
    with closing(connect()) as con:
        con.execute("BEGIN IMMEDIATE")
        before = _row(con, "products", product_id)
        if before is None:
            return _refuse(function, args, f"product {product_id} not found")
        clean, reason = _check_product_fields(con, fields)
        if reason:
            return _refuse(function, args, reason)
        sets = ", ".join(f"{name} = ?" for name in clean)   # names checked against PRODUCT_FIELDS above
        con.execute(f"UPDATE products SET {sets} WHERE id = ?", (*clean.values(), product_id))
        row = _row(con, "products", product_id)
        _log_action(con, admin, function, "products", product_id, before, row)
        con.commit()
    return _done(function, args, row)


def _set_active(function: str, admin: str, product_id: int, active: int) -> dict:
    args = {"admin": admin, "product_id": product_id}
    if reason := _bad_admin(admin):
        return _refuse(function, args, reason)
    with closing(connect()) as con:
        con.execute("BEGIN IMMEDIATE")
        before = _row(con, "products", product_id)
        if before is None:
            return _refuse(function, args, f"product {product_id} not found")
        if before["active"] == active:
            return _refuse(function, args, f"product {product_id} is already {'active' if active else 'inactive'}")
        con.execute("UPDATE products SET active = ? WHERE id = ?", (active, product_id))
        row = _row(con, "products", product_id)
        _log_action(con, admin, function, "products", product_id, before, row)
        con.commit()
    return _done(function, args, row)


def deactivate_product(admin: str, product_id: int) -> dict:
    """Remove a product from the shop (soft delete: the row stays, old orders still show it)."""
    return _set_active("deactivate_product", admin, product_id, 0)


def reactivate_product(admin: str, product_id: int) -> dict:
    """Put a deactivated product back in the shop."""
    return _set_active("reactivate_product", admin, product_id, 1)


def admin_set_order_status(admin: str, order_id: int, new_status: str) -> dict:
    """The admin moves an order: only the moves in STATUS_MOVES, or "cancelled" while it is "processing"
    (not shipped yet; the stock goes back) AND nothing was paid (T18 follow-up: a paid order must be refunded
    first, so cancelling never keeps a client's money). "refunded" is never set by hand. Returns the order row."""
    function, args = "admin_set_order_status", {"admin": admin, "order_id": order_id, "new_status": new_status}
    if reason := _bad_admin(admin):
        return _refuse(function, args, reason)
    if new_status == "refunded":
        return _refuse(function, args, "'refunded' is never set by hand: refunds go through Refund approvals")
    if new_status not in ORDER_STATUSES:
        return _refuse(function, args, f"unknown status '{new_status}' (allowed: {', '.join(ORDER_STATUSES)})")
    with closing(connect()) as con:
        con.execute("BEGIN IMMEDIATE")   # status, stock back and the log line together
        before = _row(con, "orders", order_id)
        if before is None:
            return _refuse(function, args, f"order {order_id} not found")
        old = before["status"]
        if new_status == "cancelled":
            if old not in ADMIN_CANCEL_FROM:
                return _refuse(function, args, f"only an order that is not shipped yet ({', '.join(ADMIN_CANCEL_FROM)})"
                                               f" can be cancelled; order {order_id} is {old}")
            if before["paid"] > 0:
                return _refuse(function, args, PAID_CANCEL_MESSAGE)
        elif new_status not in STATUS_MOVES.get(old, ()):
            return _refuse(function, args, f"move {old} -> {new_status} is not allowed")
        _apply_status(con, int(order_id), new_status, sim_today().isoformat())
        if new_status == "cancelled":
            for item in json.loads(before["items"]):
                if item.get("product_id") is not None:   # the "Delivery" line has no product
                    con.execute("UPDATE products SET stock = stock + ? WHERE id = ?",
                                (int(item["qty"]), item["product_id"]))
        row = _row(con, "orders", order_id)
        _log_action(con, admin, function, "orders", order_id, before, row)
        con.commit()
    return _done(function, args, row)


def create_user(admin: str, name: str, email: str, phone: str, city: str) -> dict:
    """Add a ShopNova client (no login is created). New id = max + 1; source 'app', ai_generated 0, scripted 0."""
    function, args = "create_user", {"admin": admin, "name": name, "email": email, "phone": phone, "city": city}
    if reason := _bad_admin(admin):
        return _refuse(function, args, reason)
    with closing(connect()) as con:
        con.execute("BEGIN IMMEDIATE")
        clean, reason = _check_user_fields(con, {"name": name, "email": email, "phone": phone, "city": city}, None)
        if reason:
            return _refuse(function, args, reason)
        user_id = con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM users").fetchone()[0]
        con.execute("INSERT INTO users (id, name, email, phone, city, source, ai_generated, scripted)"
                    " VALUES (?, ?, ?, ?, ?, 'app', 0, 0)",
                    (user_id, clean["name"], clean["email"], clean["phone"], clean["city"]))
        row = _row(con, "users", user_id)
        _log_action(con, admin, function, "users", user_id, None, row)
        con.commit()
    return _done(function, args, row)


def update_user(admin: str, user_id: int, **fields) -> dict:
    """Change a client's name / email / phone / city (same checks as create_user)."""
    function, args = "update_user", {"admin": admin, "user_id": user_id, **fields}
    if reason := _bad_admin(admin):
        return _refuse(function, args, reason)
    if not fields:
        return _refuse(function, args, "nothing to change")
    with closing(connect()) as con:
        con.execute("BEGIN IMMEDIATE")
        before = _row(con, "users", user_id)
        if before is None:
            return _refuse(function, args, f"user {user_id} not found")
        clean, reason = _check_user_fields(con, fields, before["id"])
        if reason:
            return _refuse(function, args, reason)
        sets = ", ".join(f"{name} = ?" for name in clean)   # names checked against USER_FIELDS above
        con.execute(f"UPDATE users SET {sets} WHERE id = ?", (*clean.values(), before["id"]))
        row = _row(con, "users", before["id"])
        _log_action(con, admin, function, "users", before["id"], before, row)
        con.commit()
    return _done(function, args, row)


def admin_decide_refund(admin: str, proposal_id: str, approve: bool, reason: str = "",
                        approval_id: int | None = None) -> dict:
    """The admin's Layer 3 decision on a refund proposal, written in ONE transaction (T18 follow-up): if any part
    fails, NOTHING is written.

    Approve: the proposal's decision "approve" + the refund (create_refund's own safety nets, run here on the same
    transaction) + for R-REF-03 the order status "refunded" + the admin_actions row "approve_refund".
    Refuse (reason required): the decision "layer3" + the admin_actions row "refuse_refund"; nothing is paid.
    Returns {"proposal_id", "decision", "refund" (row or None), "order_status" (new status or None), "log" (row)}.
    """
    function = "admin_decide_refund"
    args = {"admin": admin, "proposal_id": proposal_id, "approve": approve, "reason": reason,
            "approval_id": approval_id}
    if bad := _bad_admin(admin):
        return _refuse(function, args, bad)
    reason = (reason or "").strip()
    if not approve and not reason:
        return _refuse(function, args, "a reason is required to refuse")
    decision = "approve" if approve else "layer3"
    note = (f"R-ESC-01: {'approved' if approve else 'refused'} by the ShopNova admin ({admin})"
            + (f": {reason}" if reason else ""))
    try:
        with closing(connect()) as con:
            con.execute("BEGIN IMMEDIATE")   # everything below is committed together, or not at all
            row = con.execute("SELECT * FROM proposals WHERE id = ?", (str(proposal_id),)).fetchone()
            if row is None:
                return _refuse(function, args, f"proposal {proposal_id} not found")
            if row["decision"] is not None:
                return _refuse(function, args, f"proposal {proposal_id} already decided: {row['decision']}")
            if row["action"] != "refund":
                return _refuse(function, args, f"proposal {proposal_id} is not a refund")
            params = json.loads(row["params"])
            order_id, amount = params.get("order_id"), params.get("amount")
            con.execute("UPDATE proposals SET decision = ?, decision_reason = ?, decided_at = ? WHERE id = ?",
                        (decision, note, sim_today().isoformat(), str(proposal_id)))
            refund, status = None, None
            if approve:
                problem = _refund_problem(con, order_id, amount, proposal_id)   # sees the "approve" just set
                if problem:
                    return _refuse(function, args, problem)               # closing without commit = rollback
                refund = _insert_refund(con, order_id, amount, row["rule_id"], proposal_id)
                if row["rule_id"] == "R-REF-03":   # full refund of a late order, as the Coordinator's path
                    if _row(con, "orders", order_id)["status"] != "refunded":
                        _apply_status(con, int(order_id), "refunded", sim_today().isoformat())
                    status = "refunded"
                _log_action(con, admin, "approve_refund", "refunds", refund["id"], None,
                            {"refund": refund, "order_status": status, "proposal_id": proposal_id,
                             "approval_id": approval_id, "reason": reason or None})
            else:
                _log_action(con, admin, "refuse_refund", "proposals", proposal_id, None,
                            {"decision": decision, "amount": amount, "order_id": order_id,
                             "approval_id": approval_id, "reason": reason})
            log = dict(con.execute("SELECT * FROM admin_actions ORDER BY id DESC LIMIT 1").fetchone())
            con.commit()
    except Exception as e:   # any failure: the transaction is not committed, so nothing is written
        return _refuse(function, args, f"nothing was written: {type(e).__name__}: {e}")
    return _done(function, args, {"proposal_id": str(proposal_id), "decision": decision, "refund": refund,
                                  "order_status": status, "log": log})
