"""Stock READ tools (P20): what Agent C reads about availability, and what Agent D's rules use.

Read only, like shopnova_tools.py: nothing here changes data.

Demand = units sold in the last DEMAND_DAYS days (orders placed in that window, cancelled orders not counted).
    daily_rate     = units_sold_30d / 30
    days_of_cover  = stock / daily_rate   (how many days the stock lasts at that rate; NO_SALES_COVER if no sales)
The verdict uses the rule conditions of the policy file, so the thresholds are written in ONE place:
    shortage  = R-STK-01 condition (stock <= 5 or days_of_cover < 14)
    overstock = R-PRM-01 condition without the discount part (checked with the smallest possible discount)
"""

import json
from contextlib import closing
from datetime import timedelta

from callverse.config import sim_today
from callverse.data.db import connect
from callverse.kb.policies import check_condition, get_policy

DEMAND_DAYS = 30
NO_SALES_COVER = 9999   # "days of cover" when nothing was sold: the stock never runs out at that rate


def units_sold(con, days: int = DEMAND_DAYS) -> dict[int, int]:
    """product_id -> units sold in the last `days` days (today included), cancelled orders left out."""
    today = sim_today()
    start = (today - timedelta(days=days - 1)).isoformat()
    sold: dict[int, int] = {}
    rows = con.execute("SELECT items FROM orders WHERE order_date BETWEEN ? AND ? AND status != 'cancelled'",
                       (start, today.isoformat())).fetchall()
    for row in rows:
        for item in json.loads(row["items"]):
            pid = item.get("product_id")
            if isinstance(pid, int):
                sold[pid] = sold.get(pid, 0) + int(item.get("qty") or 1)
    return sold


def _facts(product: dict, sold_30d: int) -> dict:
    """The stock facts of one product, with the shortage / overstock verdict from the rule conditions."""
    rate = sold_30d / DEMAND_DAYS
    cover = round(product["stock"] / rate, 1) if rate > 0 else NO_SALES_COVER
    facts = {"product_id": product["id"], "name": product["name"], "price": product["price"],
             "stock": product["stock"], "active": bool(product["active"]), "units_sold_30d": sold_30d,
             "days_of_cover": cover}
    facts["shortage"] = facts["active"] and check_condition(get_policy("R-STK-01")["condition"], facts)
    # The smallest discount D can propose is 1 %, so this asks only "is it overstocked?".
    facts["overstock"] = (facts["active"] and not facts["shortage"]
                          and check_condition(get_policy("R-PRM-01")["condition"], {**facts, "discount_pct": 1}))
    return facts


def stock_facts(product_id: int) -> dict:
    """Stock facts of one product, or {"error": ...}."""
    if isinstance(product_id, bool) or not isinstance(product_id, int):
        return {"error": "product_id must be an integer"}
    with closing(connect()) as con:
        row = con.execute("SELECT id, name, price, stock, active FROM products WHERE id = ?", (product_id,)).fetchone()
        if row is None:
            return {"error": f"product {product_id} not found"}
        sold = units_sold(con).get(product_id, 0)
    return _facts(dict(row), sold)


def stock_report() -> list[dict]:
    """Stock facts of every product (Agent D's scan). One pass over the orders, one over the products."""
    with closing(connect()) as con:
        sold = units_sold(con)
        products = [dict(r) for r in con.execute("SELECT id, name, price, stock, active FROM products ORDER BY id")]
    return [_facts(p, sold.get(p["id"], 0)) for p in products]


def get_stock(product_id: int) -> dict:
    """TOOL: stock of a product + D's verdict (shortage / overstock). Read only."""
    return stock_facts(product_id)


SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_stock",
        "description": "Stock of a product (units left, units sold in 30 days, shortage). Read only.",
        "parameters": {"type": "object", "properties": {"product_id": {"type": "integer"}},
                       "required": ["product_id"]},
    },
}
