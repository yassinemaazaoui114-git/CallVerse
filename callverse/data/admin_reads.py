"""Read-only views of ShopNova data for the ShopNova ADMIN pages (T18): the dashboard and the Manage tables.

Like shop_reads.py and reports.py: NOT agent tools, nothing here writes (the admin's writes are in writes.py).

Dashboard period: the last 7 / 30 / 90 days, counted back from the simulation clock's today (sim_today), so the
numbers follow the demo date, never the computer's date. An order belongs to the period by its order_date.
"""

import json
from contextlib import closing
from datetime import date, timedelta

from callverse.config import sim_today
from callverse.data.db import connect
from callverse.data.seed import COUNTED_REFUND_STATUSES
from callverse.kb.policies import get_policy
from callverse.tools.shopnova_tools import get_company_profile, get_refunds, get_tracking

PERIODS = (7, 30, 90)
DEFAULT_PERIOD = 30
LOW_STOCK = 5          # active products with stock <= 5 are listed as "low stock"
PAGE_SIZE = 50         # rows per page in the Manage tables (item 11)
NOT_LATE_STATUSES = ("cancelled", "refunded")   # an order that will not be delivered is not "late"


def period_start(days: int) -> date:
    """First day of the period: the last `days` days, today included."""
    if days not in PERIODS:
        raise ValueError(f"period must be one of {PERIODS} days")
    return sim_today() - timedelta(days=days - 1)


def _orders_in(days: int) -> list[dict]:
    start, today = period_start(days).isoformat(), sim_today().isoformat()
    with closing(connect()) as con:
        rows = con.execute("SELECT * FROM orders WHERE order_date BETWEEN ? AND ? ORDER BY order_date, id",
                           (start, today)).fetchall()
    return [{**dict(r), "items": json.loads(r["items"])} for r in rows]


def is_late(order: dict, today: date) -> bool:
    """Delivered after its promised date, or not delivered (and not cancelled / refunded) and past it."""
    if not order["promised_date"]:
        return False
    if order["delivered_date"]:
        return order["delivered_date"] > order["promised_date"]
    return order["status"] not in NOT_LATE_STATUSES and today.isoformat() > order["promised_date"]


def dashboard(days: int = DEFAULT_PERIOD) -> dict:
    """Everything the Admin dashboard shows for the period (docs/ui_design.md section 5, T18 item 3)."""
    start, today = period_start(days), sim_today()
    orders = _orders_in(days)
    sold = [o for o in orders if o["status"] != "cancelled"]

    # Sales in TND per day (every day of the period, 0 when nothing was sold).
    per_day = {(start + timedelta(days=i)).isoformat(): 0.0 for i in range(days)}
    for o in sold:
        per_day[o["order_date"]] = round(per_day[o["order_date"]] + o["total"], 2)

    by_status: dict[str, int] = {}
    for o in orders:
        by_status[o["status"]] = by_status.get(o["status"], 0) + 1

    # Top products and categories by quantity sold (the "Delivery" line has no product and is not counted).
    with closing(connect()) as con:
        categories = {r["id"]: r["category"] or "other" for r in con.execute("SELECT id, category FROM products")}
        names = {r["id"]: r["name"] for r in con.execute("SELECT id, name FROM products")}
        marks = ", ".join("?" for _ in COUNTED_REFUND_STATUSES)
        refunds = con.execute(f"SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM refunds WHERE status IN ({marks})"
                              " AND created_at BETWEEN ? AND ?",
                              (*COUNTED_REFUND_STATUSES, start.isoformat(), today.isoformat())).fetchone()
        reviews = con.execute("SELECT score, COUNT(*) AS n FROM reviews WHERE created_at BETWEEN ? AND ?"
                              " GROUP BY score", (start.isoformat(), today.isoformat())).fetchall()
        low_stock = [dict(r) for r in con.execute(
            "SELECT id, name, category, stock FROM products WHERE active = 1 AND stock <= ? ORDER BY stock, id",
            (LOW_STOCK,)).fetchall()]
    qty_product: dict[int, int] = {}
    qty_category: dict[str, int] = {}
    for o in sold:
        for item in o["items"]:
            pid = item.get("product_id")
            if pid is None:
                continue
            qty_product[pid] = qty_product.get(pid, 0) + int(item["qty"])
            cat = categories.get(pid, "other")
            qty_category[cat] = qty_category.get(cat, 0) + int(item["qty"])
    top_products = sorted(qty_product.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    top_categories = sorted(qty_category.items(), key=lambda kv: (-kv[1], kv[0]))

    scores = {s: 0 for s in range(1, 6)}
    for r in reviews:
        scores[r["score"]] = r["n"]
    count = sum(scores.values())

    late = [o for o in orders if is_late(o, today)]
    return {
        "days": days, "start": start.isoformat(), "today": today.isoformat(),
        "orders": len(orders), "sales_tnd": round(sum(o["total"] for o in sold), 2),
        "sales_per_day": [{"day": d, "sales_tnd": v} for d, v in per_day.items()],
        "orders_by_status": [{"status": s, "orders": n} for s, n in sorted(by_status.items(), key=lambda kv: -kv[1])],
        "late": len(late),
        "late_orders": [{"id": o["id"], "status": o["status"], "promised_date": o["promised_date"],
                         "delivered_date": o["delivered_date"]} for o in late],
        "stuck": sum(1 for o in orders if o["status"] == "stuck_at_depot"),
        "refunds_paid": {"count": refunds[0], "tnd": round(refunds[1], 2)},
        "top_products": [{"product_id": pid, "name": names.get(pid, f"product {pid}"), "qty": q}
                         for pid, q in top_products],
        "top_categories": [{"category": c, "qty": q} for c, q in top_categories],
        "review_scores": [{"score": s, "count": n} for s, n in scores.items()],
        "review_average": round(sum(s * n for s, n in scores.items()) / count, 2) if count else None,
        "review_count": count,
        "low_stock": low_stock,
    }


# ---------- Manage tables (search box + 50 rows per page) ----------

def _page(rows: list[dict], page: int) -> dict:
    """One page of rows: {items, total, page, pages}."""
    pages = max(1, -(-len(rows) // PAGE_SIZE))
    page = min(max(1, int(page)), pages)
    start = (page - 1) * PAGE_SIZE
    return {"items": rows[start:start + PAGE_SIZE], "total": len(rows), "page": page, "pages": pages}


def _matches(search: str, *values) -> bool:
    """True when `search` (any case) is part of one of the values, or the search is empty."""
    s = (search or "").strip().lower()
    return not s or any(s in str(v).lower() for v in values if v is not None)


def products_page(search: str = "", page: int = 1) -> dict:
    """All products, active or not (the admin sees deactivated ones too)."""
    with closing(connect()) as con:
        rows = [dict(r) for r in con.execute(
            "SELECT id, name, category, price, stock, active, source FROM products ORDER BY id").fetchall()]
    return _page([r for r in rows if _matches(search, r["id"], r["name"], r["category"])], page)


def orders_page(search: str = "", page: int = 1) -> dict:
    """Orders, newest first, with the client's name. Search: order id, client name or status."""
    with closing(connect()) as con:
        rows = [dict(r) for r in con.execute(
            "SELECT o.id, o.user_id, u.name AS user_name, o.status, o.total, o.paid, o.payment, o.order_date,"
            " o.promised_date, o.delivered_date, o.source FROM orders o LEFT JOIN users u ON u.id = o.user_id"
            " ORDER BY o.order_date DESC, o.id DESC").fetchall()]
    return _page([r for r in rows if _matches(search, r["id"], r["user_name"], r["status"])], page)


def users_page(search: str = "", page: int = 1) -> dict:
    with closing(connect()) as con:
        rows = [dict(r) for r in con.execute(
            "SELECT id, name, email, phone, city, source FROM users ORDER BY id").fetchall()]
    return _page([r for r in rows if _matches(search, r["id"], r["name"], r["email"], r["phone"], r["city"])], page)


def refunds_page(search: str = "", page: int = 1) -> dict:
    """Refunds, newest first (view only). Search: refund id, order id, status or rule."""
    with closing(connect()) as con:
        rows = [dict(r) for r in con.execute(
            "SELECT id, order_id, amount, status, rule_id, proposal_id, created_at, source FROM refunds"
            " ORDER BY id DESC").fetchall()]
    return _page([r for r in rows if _matches(search, r["id"], r["order_id"], r["status"], r["rule_id"])], page)


def admin_log(limit: int = 50) -> list[dict]:
    """The last admin actions, newest first."""
    with closing(connect()) as con:
        return [dict(r) for r in con.execute("SELECT * FROM admin_actions ORDER BY id DESC LIMIT ?",
                                             (int(limit),)).fetchall()]


def product_categories() -> list[str]:
    with closing(connect()) as con:
        return [r[0] for r in con.execute("SELECT DISTINCT category FROM products WHERE category IS NOT NULL"
                                          " ORDER BY category").fetchall()]


def cities() -> list[str]:
    return get_company_profile().get("cities_served", [])


def product_row(product_id: int) -> dict | None:
    with closing(connect()) as con:
        row = con.execute("SELECT * FROM products WHERE id = ?", (int(product_id),)).fetchone()
    return dict(row) if row else None


def user_row(user_id: int) -> dict | None:
    with closing(connect()) as con:
        row = con.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone()
    return dict(row) if row else None


def order_row(order_id: int) -> dict | None:
    with closing(connect()) as con:
        row = con.execute("SELECT * FROM orders WHERE id = ?", (int(order_id),)).fetchone()
    return {**dict(row), "items": json.loads(row["items"])} if row else None


def proposal(proposal_id: str | None) -> dict | None:
    """One proposals row with params / facts_used turned back into dicts, or None."""
    with closing(connect()) as con:
        row = con.execute("SELECT * FROM proposals WHERE id = ?", (str(proposal_id),)).fetchone()
    if row is None:
        return None
    return {**dict(row), "params": json.loads(row["params"]), "facts_used": json.loads(row["facts_used"])}


def approval_facts(order_id: int, proposal_id: str | None) -> dict:
    """What the Refund approvals page shows next to a pending approval: the order's status, paid, already
    refunded, days late, the client's name, and the agent's proposal (rule id + title, facts_used)."""
    order = order_row(order_id) or {}
    tracking = get_tracking(order_id)
    refunds = get_refunds(order_id)
    with closing(connect()) as con:
        user = con.execute("SELECT name FROM users WHERE id = ?", (order.get("user_id"),)).fetchone()
        proposal = con.execute("SELECT * FROM proposals WHERE id = ?", (str(proposal_id),)).fetchone()
    rule_id = proposal["rule_id"] if proposal else None
    rule = get_policy(rule_id) if rule_id else None
    return {"order_status": order.get("status"), "paid": order.get("paid"),
            "refunded_total": refunds.get("refunded_total"), "days_late": tracking.get("days_late"),
            "user_name": user["name"] if user else None, "rule_id": rule_id,
            "rule_title": rule["title"] if rule else None,
            "facts_used": json.loads(proposal["facts_used"]) if proposal else {},
            "proposal_decision": proposal["decision"] if proposal else None}
