"""Read-only views of ShopNova data for the ShopNova app (T17): the catalogue and a client's own orders.

Like reports.py: NOT agent tools, nothing here writes. Buying goes through writes.create_order.

Categories come from the products.category column (T17 follow-up Q2); a product without one is "other".
"""

import json
from contextlib import closing

from callverse.data.db import connect

FEATURED_IDS = (1, 2, 3, 4, 5, 6)   # the scripted products: "Featured" on top of the shop
# One icon and a readable name per category (T17 item 6).
CATEGORY_ICONS = {
    "computers_accessories": "🖱️", "watches_gifts": "⌚", "telephony": "📱", "electronics": "🔌",
    "consoles_games": "🎮", "fixed_telephony": "☎️", "audio": "🎧", "computers": "💻",
    "tablets_printing_image": "🖨️", "pc_gamer": "🕹️", "other": "📦",
}
CATEGORY_NAMES = {
    "computers_accessories": "Computer accessories", "watches_gifts": "Watches", "telephony": "Phones",
    "electronics": "Electronics", "consoles_games": "Consoles and games", "fixed_telephony": "Landline phones",
    "audio": "Audio", "computers": "Computers", "tablets_printing_image": "Tablets, printers, cameras",
    "pc_gamer": "Gaming PCs", "other": "Other",
}
PAGE_SIZE = 24


def icon(category: str) -> str:
    return CATEGORY_ICONS.get(category, CATEGORY_ICONS["other"])


def category_name(category: str) -> str:
    return CATEGORY_NAMES.get(category, category.replace("_", " ").capitalize())


def _all_products() -> list[dict]:
    with closing(connect()) as con:
        rows = con.execute("SELECT id, name, price, stock, category FROM products ORDER BY id").fetchall()
    return [{**dict(r), "category": r["category"] or "other"} for r in rows]


def product(product_id) -> dict | None:
    """One product with its category, or None."""
    return next((p for p in _all_products() if p["id"] == product_id), None)


def featured() -> list[dict]:
    return [p for p in _all_products() if p["id"] in FEATURED_IDS]


def categories() -> list[str]:
    """The categories that have products, the biggest first."""
    counts: dict[str, int] = {}
    for p in _all_products():
        counts[p["category"]] = counts.get(p["category"], 0) + 1
    return sorted(counts, key=lambda c: (-counts[c], c))


def products(search: str = "", category: str | None = None, page: int = 1) -> dict:
    """One page of the catalogue: {items, total, page, pages}. search = part of the name (any case)."""
    found = [p for p in _all_products()
             if (not search or search.lower() in p["name"].lower()) and (not category or p["category"] == category)]
    pages = max(1, -(-len(found) // PAGE_SIZE))
    page = min(max(1, int(page)), pages)
    start = (page - 1) * PAGE_SIZE
    return {"items": found[start:start + PAGE_SIZE], "total": len(found), "page": page, "pages": pages}


def user_orders(user_id: int) -> list[dict]:
    """The user's OWN orders, newest first, each with its lines and its refunds."""
    with closing(connect()) as con:
        rows = con.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY order_date DESC, id DESC",
                           (int(user_id),)).fetchall()
        refunds = con.execute("SELECT r.* FROM refunds r JOIN orders o ON o.id = r.order_id WHERE o.user_id = ?"
                              " ORDER BY r.id", (int(user_id),)).fetchall()
    by_order: dict[int, list] = {}
    for r in refunds:
        by_order.setdefault(r["order_id"], []).append(dict(r))
    return [{**dict(o), "items": json.loads(o["items"]), "refunds": by_order.get(o["id"], [])} for o in rows]


def user_name(user_id: int) -> str | None:
    with closing(connect()) as con:
        row = con.execute("SELECT name FROM users WHERE id = ?", (int(user_id),)).fetchone()
    return row["name"] if row else None
