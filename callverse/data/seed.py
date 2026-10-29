"""Creates the ShopNova SQLite database (callverse/data/shopnova.db).

Two kinds of data go in (T15):
1. The SCRIPTED demo data written below by hand: users 1-5, products 1-6, orders 4505-4515, refund 1.
   It never changes (the demo scenarios and tests rely on every value).
2. The REAL sample: 2,000 real orders of the Olist dataset (ids 10001+, users 1001+, products 101+,
   their reviews, and refunds made from real signals), read from callverse/data/real/shopnova_olist_sample.json.
   That file is built by scripts/build_shopnova_sample.py and already contains everything, so seeding needs
   no raw data, no random numbers and no network.
The schema is described in docs/platform_contract.md section 2 (with which columns are real, which generated).

Labels asked by the teacher, on every table:
- ai_generated = 1 : the row (or part of it, see the contract) is fictional data written by an AI / a generator.
- scripted     = 1 : the row belongs to a demo scenario that must stay exactly as it is.
- source           : where the row comes from: "scripted" (written below), "olist" (real data) or
                     "generated" (made by the builder from real signals); NULL = written at run time.
- source_id        : the Olist id of a real row (order_id, customer_unique_id, product_id, review_id).
Rows created later at run time (by the Coordinator's write functions) get 0 / 0 and source NULL.

Run it directly:  python -m callverse.data.seed
"""

import json
import sqlite3
from functools import lru_cache
from pathlib import Path

from callverse.data import db
from callverse.kb.policies import notification_events

DB_PATH = db.DEFAULT_DB_PATH  # kept for older imports; the file in use is db.db_path()
# The real ShopNova sample (T15), derived from Olist (CC BY-NC-SA 4.0, see DATA_LICENCES.md).
REAL_SAMPLE_PATH = Path(__file__).resolve().parent / "real" / "shopnova_olist_sample.json"
SOURCES = ("scripted", "olist", "generated")

# Allowed codes (also enforced by CHECK constraints in the schema below).
ORDER_STATUSES = ("processing", "shipped", "stuck_at_depot", "out_for_delivery",
                  "delivered", "refunded", "cancelled")
REFUND_STATUSES = ("approved", "completed", "refused")
# Refund statuses that count as money given back (a "refused" refund does not count).
COUNTED_REFUND_STATUSES = ("approved", "completed")
# Allowed status moves (set_order_status). Besides these, any status may go to "cancelled" or "refunded".
STATUS_MOVES = {
    "processing": ("shipped",),
    "shipped": ("out_for_delivery", "stuck_at_depot"),   # a parcel can get stuck after shipping
    "out_for_delivery": ("delivered",),
    "stuck_at_depot": ("out_for_delivery",),
}
ALWAYS_ALLOWED = ("cancelled", "refunded")
SUBSCRIPTION_STATUSES = ("waiting", "sent")
# Coordinator decisions on a proposal (review(proposal) outcomes). Only "approve" lets a refund be written.
DECISIONS = ("approve", "send_back", "ask_user", "ask_proof", "layer3", "escalate")
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

# T15: where a row comes from, on the tables that hold seed data (users, products, orders, refunds, reviews).
SOURCE = f"""
    source    TEXT CHECK (source IS NULL OR source IN {_in(SOURCES)}),  -- NULL = written at run time
    source_id TEXT,                    -- Olist id of a real row, NULL otherwise"""

SCHEMA = f"""
CREATE TABLE users (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL,
    email TEXT UNIQUE,
    phone TEXT UNIQUE,
    city  TEXT,                        -- one of company_profile.json cities_served (NULL for users 1-5){SOURCE},{LABELS}
);
CREATE TABLE products (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL,
    price REAL NOT NULL,
    stock INTEGER NOT NULL,{SOURCE},{LABELS}
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
    tracking_number TEXT,{SOURCE},{LABELS}
);
CREATE TABLE refunds (
    id          INTEGER PRIMARY KEY,
    order_id    INTEGER NOT NULL REFERENCES orders(id),
    amount      REAL NOT NULL,       -- TND
    status      TEXT NOT NULL CHECK (status IN {_in(REFUND_STATUSES)}),
    rule_id     TEXT,                -- policy rule that justified the refund, e.g. R-REF-03
    proposal_id TEXT,                -- the agent proposal the Coordinator approved
    created_at  TEXT,                -- ISO date{SOURCE},{LABELS}
);
CREATE TABLE reviews (                 -- T15: real Olist review scores (the Portuguese text is not kept)
    id         INTEGER PRIMARY KEY,
    order_id   INTEGER NOT NULL REFERENCES orders(id),
    score      INTEGER NOT NULL CHECK (score BETWEEN 1 AND 5),
    created_at TEXT NOT NULL,          -- ISO date{SOURCE},{LABELS}
);
CREATE TABLE subscriptions (
    id         INTEGER PRIMARY KEY,
    order_id   INTEGER NOT NULL REFERENCES orders(id),
    event      TEXT NOT NULL CHECK (event IN {_in(NOTIFICATION_EVENTS)}),
    status     TEXT NOT NULL CHECK (status IN {_in(SUBSCRIPTION_STATUSES)}),
    created_at TEXT NOT NULL,
    proposal_id TEXT,                  -- the approved "subscribe" proposal it came from{LABELS}
);
CREATE TABLE events (
    id       INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    event    TEXT NOT NULL CHECK (event IN {_in(NOTIFICATION_EVENTS)}),
    at       TEXT NOT NULL,{LABELS}
);
CREATE TABLE proposals (               -- audit: every agent proposal and the Coordinator's decision on it
    id              TEXT PRIMARY KEY,  -- "P-0001", "P-0002", ...
    agent           TEXT NOT NULL,     -- "A", "B", ...
    action          TEXT NOT NULL,     -- e.g. "refund", "subscribe_update"
    params          TEXT NOT NULL,     -- JSON, e.g. {{"order_id": 4512, "amount": 59.9}}
    rule_id         TEXT,              -- policy rule the agent cites
    facts_used      TEXT NOT NULL,     -- JSON: the facts the agent says it used
    user_confirmed  INTEGER NOT NULL CHECK (user_confirmed IN (0, 1)),
    decision        TEXT CHECK (decision IS NULL OR decision IN {_in(DECISIONS)}),  -- NULL = not decided yet
    decision_reason TEXT,
    created_at      TEXT NOT NULL,
    decided_at      TEXT,{LABELS}
);
"""

# ---------------------------------------------------------------------------
# SCRIPTED DATA: AI-written demo data (fictional people, products and orders), source = "scripted".
# Do not change a value: the demo scenarios and the tests rely on it.
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
    # LAYER 3 CASE: 2 Smart Watches, 378.00 TND paid, promised 2026-10-01 (8 days late), stuck at the depot.
    # A full refund is above 300 TND, so it needs finance approval (R-ESC-01).
    (4515, 2, [_item(4, qty=2)],   378.00, 378.00, "stuck_at_depot", "2026-09-25", "2026-10-01", None,         "Aramex",      "ARX100055"),
]

REFUNDS = [
    # (id, order_id, amount, status, rule_id, proposal_id, created_at)
    # Part of scripted case 4506 (already refunded). rule_id/proposal_id unknown: it predates the system.
    (1, 4506, 189.00, "completed", None, None, "2026-09-20"),
]



# ---------------------------------------------------------------------------
# REAL DATA (T15): 2,000 real Olist orders and what belongs to them. Built once by
# scripts/build_shopnova_sample.py (fixed seed 2026); here we only load the file.
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def load_real_sample() -> dict:
    """The real ShopNova sample {users, products, orders, reviews, refunds}, read once from its JSON file."""
    return json.loads(REAL_SAMPLE_PATH.read_text(encoding="utf-8"))


def _insert(con: sqlite3.Connection, table: str, rows: list[dict], skip: tuple = ()) -> None:
    """Insert rows given as dicts {column: value}, leaving out the keys in `skip` (file-only information).

    `items` (a list) is stored as JSON text because SQLite has no list type.
    """
    for row in rows:
        row = {k: (json.dumps(v) if k == "items" else v) for k, v in row.items() if k not in skip}
        # The column names come from our own sample file, never from a client.
        con.execute(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                    list(row.values()))


def seed(db_path: Path | None = None) -> Path:
    """(Re)create the database file from scratch with the scripted and the real data. Returns its path.

    Without db_path, the file in use (db.db_path()) is rebuilt.
    """
    db_path = Path(db_path) if db_path else db.db_path()
    if db_path.exists():
        db_path.unlink()  # start clean every time, so the data is always the same

    con = sqlite3.connect(db_path)
    try:
        con.executescript(SCHEMA)
        # Scripted data: every row is AI-written (ai_generated = 1) and has source "scripted". The 11 orders and
        # the refund of order 4506 are demo cases (scripted = 1); users 1-5 and products 1-6 are not (as before).
        con.executemany("INSERT INTO users (id, name, email, phone, source, ai_generated, scripted)"
                        " VALUES (?, ?, ?, ?, 'scripted', 1, 0)", USERS)
        con.executemany("INSERT INTO products (id, name, price, stock, source, ai_generated, scripted)"
                        " VALUES (?, ?, ?, ?, 'scripted', 1, 0)", PRODUCTS)
        # items is stored as JSON text because SQLite has no list type.
        con.executemany("INSERT INTO orders (id, user_id, items, total, paid, status, order_date, promised_date,"
                        " delivered_date, carrier, tracking_number, source, ai_generated, scripted)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scripted', 1, 1)",
                        [(o[0], o[1], json.dumps(o[2]), *o[3:]) for o in ORDERS])
        con.executemany("INSERT INTO refunds (id, order_id, amount, status, rule_id, proposal_id, created_at,"
                        " source, ai_generated, scripted) VALUES (?, ?, ?, ?, ?, ?, ?, 'scripted', 1, 1)", REFUNDS)

        # Real data: every row of the sample file already carries its labels (source, source_id, ai_generated;
        # scripted = 0 by default). Its refunds have no id in the file: they get 2, 3, ... after refund 1.
        # `category` (products) and `payment` (orders) stay in the file only: the schema has no column for them.
        real = load_real_sample()
        _insert(con, "users", real["users"])
        _insert(con, "products", real["products"], skip=("category",))
        _insert(con, "orders", real["orders"], skip=("payment",))
        _insert(con, "reviews", real["reviews"])
        _insert(con, "refunds", real["refunds"])
        con.commit()
    finally:
        con.close()
    return db_path


if __name__ == "__main__":
    print(f"Database created: {seed()}")
