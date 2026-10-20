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
import random
import sqlite3
from datetime import timedelta
from pathlib import Path

from callverse.config import sim_today
from callverse.data import db
from callverse.kb.policies import notification_events

DB_PATH = db.DEFAULT_DB_PATH  # kept for older imports; the file in use is db.db_path()

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
# GENERATED DATA (ai_generated = 1, scripted = 0): 20 extra users (ids 6-25) and 120 orders
# (ids 5001-5120) over the 60 days before the demo date, so the shop looks like a real one.
# A fixed random seed makes the data identical on every rebuild. Generated orders only belong to
# generated users, so the scripted clients' order histories stay exactly as written above.
# ---------------------------------------------------------------------------
RANDOM_SEED = 2026
FIRST_NAMES = ["Ahmed", "Mariem", "Omar", "Ines", "Hamza", "Nour", "Mehdi", "Rania", "Aziz", "Salma"]
LAST_NAMES = ["Hammami", "Bouazizi", "Chaabane", "Dridi", "Ferchichi", "Khelifi", "Mejri", "Sassi"]
# status: weight (out of 100). Mostly delivered, like a real shop.
STATUS_WEIGHTS = {"delivered": 60, "shipped": 10, "processing": 7, "out_for_delivery": 5,
                  "stuck_at_depot": 5, "cancelled": 6, "refunded": 7}


def generate_data() -> tuple[list, list, list]:
    """Return (users, orders, refunds) of generated data, always the same (fixed seed)."""
    rng = random.Random(RANDOM_SEED)
    today = sim_today()  # the fixed demo date from config.yaml (never the real clock)
    users = []
    for uid in range(6, 26):
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        users.append((uid, f"{first} {last}", f"{first}.{last}.{uid}@example.com".lower(),
                      f"+216 {50 + uid} {100 + uid * 7:03d} {200 + uid * 3:03d}"))

    orders, refunds = [], []
    for oid in range(5001, 5121):
        status = rng.choices(list(STATUS_WEIGHTS), weights=list(STATUS_WEIGHTS.values()))[0]
        items = [_item(rng.randint(1, len(PRODUCTS)), rng.choice([1, 1, 1, 2]))
                 for _ in range(rng.choice([1, 1, 2, 3]))]
        total = round(sum(i["price"] * i["qty"] for i in items), 2)

        # How long ago the order was placed depends on how far it got (the clock is fixed at today = sim_today).
        days_ago = {"processing": (1, 3), "shipped": (2, 7), "out_for_delivery": (3, 8),
                    "stuck_at_depot": (6, 15)}.get(status, (8, 60))
        order_date = today - timedelta(days=rng.randint(*days_ago))
        promised = order_date + timedelta(days=rng.randint(3, 6))
        delivered = None
        if status in ("delivered", "refunded"):
            # About 80% on time (or early), 20% 1-5 days late; never in the future, never before the order.
            delay = rng.choices([-2, -1, 0, 1, 2, 3, 5], weights=[10, 20, 50, 8, 6, 4, 2])[0]
            delivered = promised + timedelta(days=delay)
            delivered = min(max(delivered, order_date + timedelta(days=1)), today)

        # Cash on delivery (paid 0) only for orders not delivered yet; cancelled orders were never paid.
        cash_on_delivery = status in ("processing", "shipped", "out_for_delivery") and rng.random() < 0.25
        paid = 0.0 if cash_on_delivery or status == "cancelled" else total
        has_carrier = status not in ("processing", "cancelled")
        carrier = rng.choice(["Aramex", "Rapid-Poste"]) if has_carrier else None
        tracking = (("ARX" if carrier == "Aramex" else "RP") + str(300000 + oid)) if has_carrier else None

        orders.append((oid, rng.randint(6, 25), items, total, paid, status, order_date.isoformat(),
                       promised.isoformat(), delivered.isoformat() if delivered else None, carrier, tracking))
        if status == "refunded":  # item returned, refunded in full a few days after delivery
            refund_day = min(delivered + timedelta(days=rng.randint(2, 6)), today)
            refunds.append((len(REFUNDS) + len(refunds) + 1, oid, paid, "completed", "R-RET-01", None,
                            refund_day.isoformat()))
    return users, orders, refunds


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
        # Every seed row is AI-generated (ai_generated = 1). The 11 scripted orders and the refund of
        # order 4506 are demo cases (scripted = 1); users, products and generated data are not.
        gen_users, gen_orders, gen_refunds = generate_data()
        con.executemany("INSERT INTO users VALUES (?, ?, ?, ?, 1, 0)", USERS + gen_users)
        con.executemany("INSERT INTO products VALUES (?, ?, ?, ?, 1, 0)", PRODUCTS)
        # items is stored as JSON text because SQLite has no list type.
        con.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1)",
                        [(o[0], o[1], json.dumps(o[2]), *o[3:]) for o in ORDERS])
        con.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0)",
                        [(o[0], o[1], json.dumps(o[2]), *o[3:]) for o in gen_orders])
        con.executemany("INSERT INTO refunds VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1)", REFUNDS)
        con.executemany("INSERT INTO refunds VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0)", gen_refunds)
        con.commit()
    finally:
        con.close()
    return db_path


if __name__ == "__main__":
    print(f"Database created: {seed()}")
