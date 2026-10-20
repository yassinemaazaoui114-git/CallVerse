"""Read-only views of the ShopNova database for people (dashboard, summary script, local server).

These are NOT agent tools: agents only use the tools in callverse/tools/ through the registry.
Nothing here writes. Both scripts/data_summary.py and the local server (callverse/server/app.py)
use summary(), so the numbers are computed in one place only.
"""

import json
from contextlib import closing

from callverse.data.db import connect
from callverse.tools.shopnova_tools import get_company_profile, get_tracking

TABLES = ("users", "products", "orders", "refunds", "subscriptions", "events")
# Tables the dashboard may list (users/products are not listed in bulk).
LISTABLE = ("refunds", "subscriptions", "events", "proposals")


def summary() -> dict:
    """Counts shown to the professor: rows per table with AI-generated / scripted labels, orders per status,
    scripted vs generated orders, late orders, cash on delivery, total paid, refunds."""
    with closing(connect()) as con:
        tables = {}
        for t in TABLES:
            total, ai, scripted = con.execute(
                f"SELECT COUNT(*), COALESCE(SUM(ai_generated), 0), COALESCE(SUM(scripted), 0) FROM {t}").fetchone()
            tables[t] = {"total": total, "ai_generated": ai, "scripted": scripted}

        statuses = dict(con.execute(
            "SELECT status, COUNT(*) FROM orders GROUP BY status ORDER BY COUNT(*) DESC, status").fetchall())
        scripted = con.execute("SELECT COUNT(*), MIN(id), MAX(id) FROM orders WHERE scripted = 1").fetchone()
        generated = con.execute("SELECT COUNT(*), MIN(id), MAX(id) FROM orders WHERE scripted = 0").fetchone()
        ids = [r[0] for r in con.execute("SELECT id FROM orders WHERE status != 'cancelled'")]
        cod = con.execute("SELECT COUNT(*) FROM orders WHERE paid = 0 AND status != 'cancelled'").fetchone()[0]
        paid = con.execute("SELECT COALESCE(SUM(paid), 0) FROM orders").fetchone()[0]
        refunds = con.execute("SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM refunds").fetchone()

    tracking = [get_tracking(i) for i in ids]  # days_late is computed by the tool, as agents see it
    return {
        "tables": tables,
        "orders_per_status": statuses,
        "orders_total": tables["orders"]["total"],
        "scripted_orders": {"count": scripted[0], "first_id": scripted[1], "last_id": scripted[2]},
        "generated_orders": {"count": generated[0], "first_id": generated[1], "last_id": generated[2]},
        "late_not_delivered": sum(1 for t in tracking if t["days_late"] > 0 and not t["delivered"]),
        "late_delivered": sum(1 for t in tracking if t["days_late"] > 0 and t["delivered"]),
        "late_over_5_not_delivered": sum(1 for t in tracking if t["days_late"] > 5 and not t["delivered"]),
        "cash_on_delivery_unpaid": cod,
        "total_paid_tnd": round(paid, 2),
        "refunds": {"count": refunds[0], "total_tnd": round(refunds[1], 2)},
        "company": get_company_profile(),
    }


def list_orders(status: str | None = None, scripted: int | None = None, limit: int = 50) -> list[dict]:
    """Orders sorted by id, optionally filtered by status and by the scripted label (0/1). limit: 1-500."""
    sql, args = "SELECT * FROM orders WHERE 1 = 1", []
    if status:
        sql += " AND status = ?"
        args.append(status)
    if scripted is not None:
        sql += " AND scripted = ?"
        args.append(int(scripted))
    sql += " ORDER BY id LIMIT ?"
    args.append(max(1, min(int(limit), 500)))
    with closing(connect()) as con:
        rows = [dict(r) for r in con.execute(sql, args).fetchall()]
    for r in rows:
        r["items"] = json.loads(r["items"])
    return rows


def list_rows(table: str, limit: int = 100) -> list[dict]:
    """Last rows of refunds / subscriptions / events (newest first)."""
    if table not in LISTABLE:
        raise ValueError(f"table '{table}' cannot be listed")
    with closing(connect()) as con:
        # table comes from the fixed LISTABLE list above, never from the user as-is.
        rows = [dict(r) for r in con.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?",
                                              (max(1, min(int(limit), 500)),)).fetchall()]
    if table == "proposals":  # JSON columns back to Python values
        for r in rows:
            r["params"], r["facts_used"] = json.loads(r["params"]), json.loads(r["facts_used"])
            r["user_confirmed"] = bool(r["user_confirmed"])
    return rows


def get_pending_notifications() -> list[dict]:
    """Notifications to send: events that match a subscription still "waiting" (read-only).

    A subscription matches an event of the same order and the same event name that happened on or
    after the day the client subscribed. One item per subscription (its first matching event).
    The notifier sends the message, then calls writes.mark_subscription_sent(subscription_id).
    Returns [{subscription_id, order_id, event, event_at, user: {id, name, email, phone}}].
    """
    with closing(connect()) as con:
        rows = con.execute(
            "SELECT s.id AS subscription_id, s.order_id, s.event, MIN(e.id) AS event_id"
            " FROM subscriptions s JOIN events e ON e.order_id = s.order_id AND e.event = s.event"
            " AND e.at >= s.created_at WHERE s.status = 'waiting' GROUP BY s.id ORDER BY s.id").fetchall()
        result = []
        for r in rows:
            event_at = con.execute("SELECT at FROM events WHERE id = ?", (r["event_id"],)).fetchone()["at"]
            user = con.execute("SELECT u.id, u.name, u.email, u.phone FROM users u JOIN orders o"
                               " ON o.user_id = u.id WHERE o.id = ?", (r["order_id"],)).fetchone()
            result.append({"subscription_id": r["subscription_id"], "order_id": r["order_id"],
                           "event": r["event"], "event_at": event_at, "user": dict(user)})
    return result
