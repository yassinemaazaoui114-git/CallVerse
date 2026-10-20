"""Read-only case data for the Client Simulator (the AI that plays a ShopNova client).

The simulated client must know only what a real client knows about THEIR OWN order: their name and
email, what they ordered, the status they can see, the promised date, how late it is, what they paid.
It never sees policies, other clients, refunds tables or internal fields.

These functions are NOT agent tools and are on no allow-list; they are not exposed over HTTP either.
"""

from callverse.tools.shopnova_tools import get_order, get_tracking, get_user

# The scripted demo cases and the scenario each one plays (tags are short, stable names).
SCENARIO_CASES = [
    {"order_id": 4512, "scenario": "late_refund",
     "description": "6 days late, stuck at the depot, never delivered: the client wants a refund (S1, S2)."},
    {"order_id": 4506, "scenario": "already_refunded",
     "description": "Already refunded 189 TND: the client asks again; a second refund must be refused."},
    {"order_id": 4510, "scenario": "on_time",
     "description": "Shipped and on time: the client is impatient; no refund applies, a notification can be offered."},
    {"order_id": 4507, "scenario": "damaged",
     "description": "Delivered (2 days late): the client says the item arrived damaged; photo proof is needed."},
    {"order_id": 4515, "scenario": "layer3",
     "description": "378 TND, 8 days late: a full refund is above 300 TND and needs finance approval (Layer 3)."},
]


def read_own_case(order_id: int) -> dict:
    """What the simulated client knows about their own order, or {"error": ...}."""
    order = get_order(order_id)
    if "error" in order:
        return order
    tracking = get_tracking(order_id)
    user = get_user(user_id=order["user_id"])
    return {
        "order_id": order["id"],
        "user": {"name": user["name"], "email": user["email"]},
        "items": [{"name": i["name"], "qty": i["qty"], "price": i["price"]} for i in order["items"]],
        "status": order["status"],
        "promised_date": order["promised_date"],
        "days_late": tracking["days_late"],
        "paid": order["paid"],
    }


def list_scenario_cases() -> list[dict]:
    """The scripted cases with their scenario tag and a one-line description."""
    return [dict(case) for case in SCENARIO_CASES]
