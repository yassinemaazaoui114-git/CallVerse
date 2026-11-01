"""ShopNova customer reads for the API (step 2): wrappers around the functions the Streamlit "My orders" page uses.

- the list: callverse.data.shop_reads.user_orders(user_id) (the user's OWN orders, newest first, with lines and
  refunds) — the user id comes from the accounts file, never from the browser (see app.py);
- one order: the same list filtered on the id, so an order of another user is simply "not found" (the same
  answer as a missing order: nothing tells a client whether an id exists);
- then, and only for an owned order, the two read tools the agents use: shopnova_tools.get_tracking (days late
  against the fixed simulation date) and shopnova_tools.get_refunds (refunded total).
No SQL and no business rule here; statuses and dates are passed through as the database holds them.
"""

from callverse.config import sim_today
from callverse.data import shop_reads
from callverse.data.seed import ORDER_STATUSES, PAYMENT_METHODS, REFUND_STATUSES
from callverse.tools import shopnova_tools


def _summary(order: dict) -> dict:
    """The fields the My orders list shows (the full lines and refunds are on the detail page)."""
    return {
        "id": order["id"], "status": order["status"], "order_date": order["order_date"],
        "promised_date": order["promised_date"], "delivered_date": order["delivered_date"],
        "total": order["total"], "paid": order["paid"], "payment": order["payment"],
        "carrier": order["carrier"], "tracking_number": order["tracking_number"],
        "items_count": sum(int(i.get("qty") or 0) for i in order["items"]),
        "items_preview": [i.get("name") for i in order["items"][:3]],
        "refunds_count": len(order["refunds"]),
    }


def orders(user_id: int) -> dict:
    """The customer's orders (summaries), newest first, with the simulation date the shop lives in."""
    rows = shop_reads.user_orders(user_id)
    return {"orders": [_summary(o) for o in rows], "count": len(rows), "sim_today": sim_today().isoformat(),
            "known": {"order_statuses": list(ORDER_STATUSES), "refund_statuses": list(REFUND_STATUSES),
                      "payment_methods": list(PAYMENT_METHODS)}}


def order_summary(user_id: int, order_id: int) -> dict | None:
    """One OWNED order's row (no tracking / refunds read), or None: the ownership check of the chat."""
    return next((o for o in shop_reads.user_orders(user_id) if o["id"] == int(order_id)), None)


def order(user_id: int, order_id: int) -> dict | None:
    """One OWNED order with its tracking and refunds, or None (missing or another user's: same answer)."""
    owned = next((o for o in shop_reads.user_orders(user_id) if o["id"] == int(order_id)), None)
    if owned is None:
        return None
    tracking = shopnova_tools.get_tracking(owned["id"])   # ownership checked above, before any detail is read
    refunds = shopnova_tools.get_refunds(owned["id"])
    return {"order": owned, "tracking": None if "error" in tracking else tracking,
            "refunds": None if "error" in refunds else refunds, "sim_today": sim_today().isoformat()}
