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
        "carrier": order["carrier"],
        "tracking_number": order["tracking_number"],
        "checked_on": today.isoformat(),
    }


def get_refunds(order_id: int) -> list[dict] | dict:
    """Return all refund rows of an order (an empty list if it has none).

    Lets an agent or the Coordinator see if an order was already refunded, and how much.
    """
    if _fetch_order(order_id) is None:
        return {"error": f"order {order_id} not found"}
    with closing(_connect()) as con:
        rows = con.execute("SELECT * FROM refunds WHERE order_id = ? ORDER BY id",
                           (int(order_id),)).fetchall()
    return [dict(r) for r in rows]


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
            "description": "Get the delivery status of an order and how many days late it is (computed by the system).",
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
            "description": "List the refunds already recorded for a ShopNova order (amount, status, rule). Empty list = no refund yet.",
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
