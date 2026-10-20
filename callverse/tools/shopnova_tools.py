"""ShopNova READ tools: they look up facts in the database. They never change anything.

Agents get their facts ONLY from these functions (rule: facts come from tools, never from
model memory). Each tool returns a plain dict; if nothing is found it returns {"error": ...}
so the model can tell the client instead of guessing.

SCHEMAS describes each tool in the JSON format used for tool calling, so the LLM knows
the tool's name, what it does and which arguments it takes.
"""

import json
from contextlib import closing
from datetime import date

from callverse.config import sim_today
from callverse.data.db import connect as _connect  # opens the DB in use (real one, or a test copy)
from callverse.data.seed import COUNTED_REFUND_STATUSES


def _fetch_order(order_id: int) -> dict | None:
    """Read one order row as a dict, with `items` turned back from JSON text into a list."""
    # closing() makes sure the file is closed after use (important on Windows).
    with closing(_connect()) as con:
        row = con.execute("SELECT * FROM orders WHERE id = ?", (int(order_id),)).fetchone()
    if row is None:
        return None
    order = dict(row)
    order["items"] = json.loads(order["items"])
    return order


def get_user(email: str | None = None, phone: str | None = None, user_id: int | None = None) -> dict:
    """Find a client by email, phone or user id (give one of them)."""
    if user_id is not None:
        column, value = "id", int(user_id)
    elif email:
        column, value = "email", email.strip().lower()
    elif phone:
        column, value = "phone", phone.strip()
    else:
        return {"error": "give an email, a phone or a user_id"}

    with closing(_connect()) as con:
        # column comes from our own fixed list above, never from the user, so this is safe.
        row = con.execute(f"SELECT * FROM users WHERE {column} = ?", (value,)).fetchone()
    return dict(row) if row else {"error": "user not found"}


def get_order(order_id: int) -> dict:
    """Return the full order: items, total, paid, status, dates, carrier, tracking number."""
    order = _fetch_order(order_id)
    return order if order else {"error": f"order {order_id} not found"}


def get_tracking(order_id: int) -> dict:
    """Return the delivery status of an order and how many days late it is.

    Days late is computed against the fixed simulation date (sim_today), not the real clock:
    - delivered order: delivered_date - promised_date
    - not delivered:   sim_today - promised_date
    (never negative: an order that is on time is 0 days late)

    days_since_delivery = sim_today - delivered_date for a delivered order, None otherwise
    (used by the 14-day return rule R-RET-01).
    """
    order = _fetch_order(order_id)
    if order is None:
        return {"error": f"order {order_id} not found"}

    today = sim_today()
    delivered = order["delivered_date"] is not None
    days_late = 0
    if order["promised_date"]:
        promised = date.fromisoformat(order["promised_date"])
        reference = date.fromisoformat(order["delivered_date"]) if delivered else today
        days_late = max(0, (reference - promised).days)

    return {
        "order_id": order["id"],
        "status": order["status"],
        "delivered": delivered,
        "promised_date": order["promised_date"],
        "delivered_date": order["delivered_date"],
        "days_late": days_late,
        "days_since_delivery": (today - date.fromisoformat(order["delivered_date"])).days if delivered else None,
        "carrier": order["carrier"],
        "tracking_number": order["tracking_number"],
        "checked_on": today.isoformat(),
    }




def get_refunds(order_id: int) -> dict:
    """Return the refunds of an order and how much was already given back.

    {"order_id": 4512, "refunds": [rows...], "refunded_total": 0.0}
    refunded_total = sum of refunds with status approved or completed. Rule R-REF-05 uses it,
    so an order cannot be refunded twice.
    """
    if _fetch_order(order_id) is None:
        return {"error": f"order {order_id} not found"}
    with closing(_connect()) as con:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM refunds WHERE order_id = ? ORDER BY id", (int(order_id),)).fetchall()]
    total = sum(r["amount"] for r in rows if r["status"] in COUNTED_REFUND_STATUSES)
    return {"order_id": int(order_id), "refunds": rows, "refunded_total": round(total, 2)}


# JSON schemas for tool calling (OpenAI "tools" format).
SCHEMAS = {
    "get_user": {
        "type": "function",
        "function": {
            "name": "get_user",
            "description": "Find a ShopNova client by email, phone or user id. Give exactly one of them.",
            "parameters": {
                "type": "object",
                "properties": {
                    "email": {"type": "string", "description": "Client email"},
                    "phone": {"type": "string", "description": "Client phone number"},
                    "user_id": {"type": "integer", "description": "Client id"},
                },
            },
        },
    },
    "get_order": {
        "type": "function",
        "function": {
            "name": "get_order",
            "description": "Get a ShopNova order: items, total, amount paid, status, order/promised/delivered dates, carrier, tracking number.",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "integer", "description": "Order number, e.g. 4512"}},
                "required": ["order_id"],
            },
        },
    },
    "get_tracking": {
        "type": "function",
        "function": {
            "name": "get_tracking",
            "description": "Get the delivery status of an order, how many days late it is, and days since delivery (null if not delivered). All computed by the system.",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "integer", "description": "Order number, e.g. 4512"}},
                "required": ["order_id"],
            },
        },
    },
    "get_refunds": {
        "type": "function",
        "function": {
            "name": "get_refunds",
            "description": "List the refunds of a ShopNova order (amount, status, rule) and refunded_total, the amount already refunded or approved (TND). Empty list = no refund yet.",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "integer", "description": "Order number, e.g. 4512"}},
                "required": ["order_id"],
            },
        },
    },
}

# Name -> Python function, used by the registry to actually run a tool.
# Being listed here does NOT give an agent access: the allow-lists in registry.py decide that.
FUNCTIONS = {
    "get_user": get_user,
    "get_order": get_order,
    "get_tracking": get_tracking,
    "get_refunds": get_refunds,
}
