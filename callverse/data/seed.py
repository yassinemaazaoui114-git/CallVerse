"""Creates the placeholder ShopNova SQLite database (callverse/data/shopnova.db).

The tables follow the teammate's structure, so when the real mock database is ready
we only swap the file; the tools do not change. The schema is described in
docs/platform_contract.md section 2.

Labels asked by the teacher, on every table:
- ai_generated = 1 : the row is fictional data written by an AI (all seed rows below).
- scripted     = 1 : the row belongs to a demo scenario that must stay exactly as it is.
Rows created later at run time (by the Coordinator's write functions) get 0 / 0.

Run it directly:  python -m callverse.data.seed
"""

import json
import sqlite3
from pathlib import Path

from callverse.data import db
from callverse.kb.policies import notification_events

DB_PATH = db.DEFAULT_DB_PATH  # kept for older imports; the file in use is db.db_path()

# Allowed codes (also enforced by CHECK constraints in the schema below).
ORDER_STATUSES = ("processing", "shipped", "stuck_at_depot", "out_for_delivery",
                  "delivered", "refunded", "cancelled")
REFUND_STATUSES = ("approved", "completed", "refused")
SUBSCRIPTION_STATUSES = ("waiting", "sent")
# Order statuses that create an `events` row (and can be subscribed to).
# Read from rule R-NOT-01 in the policy file, so the list is written in one place only.
NOTIFICATION_EVENTS = tuple(notification_events())


def _in(values) -> str:
    """SQL text "('a', 'b')" for a CHECK (... IN ...) constraint."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


# The two label columns added to every table.
LABELS = """
    ai_generated INTEGER NOT NULL DEFAULT 0 CHECK (ai_generated IN (0, 1)),
    scripted     INTEGER NOT NULL DEFAULT 0 CHECK (scripted IN (0, 1))"""

SCHEMA = f"""
CREATE TABLE users (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL,
    email TEXT UNIQUE,
    phone TEXT UNIQUE,{LABELS}
);
CREATE TABLE products (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL,
    price REAL NOT NULL,
    stock INTEGER NOT NULL,{LABELS}
);
CREATE TABLE orders (
    id              INTEGER PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    items           TEXT NOT NULL,       -- JSON list of {{product_id, name, qty, price}}
    total           REAL NOT NULL,       -- TND
    paid            REAL NOT NULL,       -- TND actually paid (0 = cash on delivery)
    status          TEXT NOT NULL CHECK (status IN {_in(ORDER_STATUSES)}),
    order_date      TEXT NOT NULL,       -- ISO dates: YYYY-MM-DD
    promised_date   TEXT,
    delivered_date  TEXT,                -- NULL = not delivered yet
    carrier         TEXT,
    tracking_number TEXT,{LABELS}
);
CREATE TABLE refunds (
    id          INTEGER PRIMARY KEY,
    order_id    INTEGER NOT NULL REFERENCES orders(id),
    amount      REAL NOT NULL,       -- TND
    status      TEXT NOT NULL CHECK (status IN {_in(REFUND_STATUSES)}),
    rule_id     TEXT,                -- policy rule that justified the refund, e.g. R-REF-03
    proposal_id TEXT,                -- the agent proposal the Coordinator approved
    created_at  TEXT,                -- ISO date{LABELS}
);
CREATE TABLE subscriptions (
    id         INTEGER PRIMARY KEY,
    order_id   INTEGER NOT NULL REFERENCES orders(id),
    event      TEXT NOT NULL CHECK (event IN {_in(NOTIFICATION_EVENTS)}),
    status     TEXT NOT NULL CHECK (status IN {_in(SUBSCRIPTION_STATUSES)}),
    created_at TEXT NOT NULL,{LABELS}
);
CREATE TABLE events (
    id       INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    event    TEXT NOT NULL CHECK (event IN {_in(NOTIFICATION_EVENTS)}),
    at       TEXT NOT NULL,{LABELS}
);
"""

# ---------------------------------------------------------------------------
# NOTE: all the data below is AI-GENERATED placeholder data (fictional people,
# products and orders). It only exists until the teammate's mock database is ready.
# ---------------------------------------------------------------------------

USERS = [
    # (id, name, email, phone)
    (1, "Sara Ben Ali",     "sara@example.com",    "+216 20 111 222"),
    (2, "Youssef Trabelsi", "youssef@example.com", "+216 22 333 444"),
    (3, "Amira Gharbi",     "amira@example.com",   "+216 24 555 666"),
    (4, "Karim Jaziri",     "karim@example.com",   "+216 26 777 888"),
    (5, "Leila Mansour",    "leila@example.com",   "+216 28 999 000"),
]

PRODUCTS = [
    # (id, name, price TND, stock)
    (1, "Wireless Earbuds",  59.90,  40),
    (2, "Phone Case",        19.90, 120),
    (3, "USB-C Charger",     34.50,  75),
    (4, "Smart Watch",      189.00,  15),
    (5, "Bluetooth Speaker", 89.00,  30),
    (6, "Laptop Backpack",   74.90,  25),
]


def _item(product_id: int, qty: int = 1) -> dict:
    """Build one order line from the product list (so names and prices stay consistent)."""
    _, name, price, _ = PRODUCTS[product_id - 1]
    return {"product_id": product_id, "name": name, "qty": qty, "price": price}


ORDERS = [
    # (id, user_id, items, total, paid, status, order_date, promised_date, delivered_date, carrier, tracking_number)
    (4505, 2, [_item(3)],           34.50,  34.50, "delivered",      "2026-09-10", "2026-09-15", "2026-09-14", "Aramex",      "ARX100045"),
    # Already refunded order (see REFUNDS below).
    (4506, 3, [_item(4)],          189.00, 189.00, "refunded",       "2026-09-12", "2026-09-18", "2026-09-17", "Rapid-Poste", "RP200046"),
    # Delivered, but 2 days after the promised date.
    (4507, 4, [_item(5), _item(2)], 108.90, 108.90, "delivered",     "2026-09-15", "2026-09-20", "2026-09-22", "Aramex",      "ARX100047"),
    (4508, 5, [_item(6)],           74.90,  74.90, "delivered",      "2026-09-18", "2026-09-23", "2026-09-23", "Rapid-Poste", "RP200048"),
    (4509, 1, [_item(2, qty=2)],    39.80,  39.80, "delivered",      "2026-09-20", "2026-09-25", "2026-09-24", "Aramex",      "ARX100049"),
    (4510, 2, [_item(1)],           59.90,  59.90, "shipped",        "2026-10-04", "2026-10-10", None,         "Aramex",      "ARX100050"),
    (4511, 3, [_item(3), _item(2)], 54.40,  54.40, "processing",     "2026-10-07", "2026-10-13", None,         None,          None),
    # THE DEMO ORDER: Sara, 59.90 TND paid, promised 2026-10-03, never delivered, stuck at the depot, no refund.
    (4512, 1, [_item(1)],           59.90,  59.90, "stuck_at_depot", "2026-09-28", "2026-10-03", None,         "Rapid-Poste", "RP200052"),
    (4513, 4, [_item(4)],          189.00, 189.00, "shipped",        "2026-10-05", "2026-10-11", None,         "Aramex",      "ARX100053"),
    # Cash on delivery: nothing paid yet.
    (4514, 5, [_item(5)],           89.00,   0.00, "processing",     "2026-10-08", "2026-10-14", None,         None,          None),
]

REFUNDS = [
    # (id, order_id, amount, status, rule_id, proposal_id, created_at)
    # Part of scripted case 4506 (already refunded). rule_id/proposal_id unknown: it predates the system.
    (1, 4506, 189.00, "completed", None, None, "2026-09-20"),
]


def seed(db_path: Path | None = None) -> Path:
    """(Re)create the database file from scratch with the placeholder data. Returns its path.

    Without db_path, the file in use (db.db_path()) is rebuilt.
    """
    db_path = Path(db_path) if db_path else db.db_path()
    if db_path.exists():
        db_path.unlink()  # start clean every time, so the data is always the same

    con = sqlite3.connect(db_path)
    try:
        con.executescript(SCHEMA)
        # Every seed row is AI-generated (ai_generated = 1). The 10 orders and the refund of
        # order 4506 are scripted demo cases (scripted = 1); users and products are not.
        con.executemany("INSERT INTO users VALUES (?, ?, ?, ?, 1, 0)", USERS)
        con.executemany("INSERT INTO products VALUES (?, ?, ?, ?, 1, 0)", PRODUCTS)
        con.executemany(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1)",
            # items is stored as JSON text because SQLite has no list type.
            [(o[0], o[1], json.dumps(o[2]), *o[3:]) for o in ORDERS],
        )
        con.executemany("INSERT INTO refunds VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1)", REFUNDS)
        con.commit()
    finally:
        con.close()
    return db_path


if __name__ == "__main__":
    print(f"Database created: {seed()}")
