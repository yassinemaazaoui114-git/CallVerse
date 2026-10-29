"""Seed data: volume, labels, consistency, determinism; scripted cases untouched; the real Olist sample (T15)."""

import hashlib
import json
import sqlite3
from contextlib import closing

from callverse.data import db
from callverse.data.layer3 import layer3_decide
from callverse.config import sim_start
from callverse.data.seed import ORDERS, load_real_sample, seed
from callverse.tools.shopnova_tools import get_order, get_refunds, get_tracking

# Orders 4505-4514 as they were in P01/P02 (copied from the DB before P03), to prove they did not change.
SCRIPTED_BEFORE_P03 = {
    4505: (2, 34.50, 34.50, "delivered", "2026-09-10", "2026-09-15", "2026-09-14", "Aramex", "ARX100045"),
    4506: (3, 189.00, 189.00, "refunded", "2026-09-12", "2026-09-18", "2026-09-17", "Rapid-Poste", "RP200046"),
    4507: (4, 108.90, 108.90, "delivered", "2026-09-15", "2026-09-20", "2026-09-22", "Aramex", "ARX100047"),
    4508: (5, 74.90, 74.90, "delivered", "2026-09-18", "2026-09-23", "2026-09-23", "Rapid-Poste", "RP200048"),
    4509: (1, 39.80, 39.80, "delivered", "2026-09-20", "2026-09-25", "2026-09-24", "Aramex", "ARX100049"),
    4510: (2, 59.90, 59.90, "shipped", "2026-10-04", "2026-10-10", None, "Aramex", "ARX100050"),
    4511: (3, 54.40, 54.40, "processing", "2026-10-07", "2026-10-13", None, None, None),
    4512: (1, 59.90, 59.90, "stuck_at_depot", "2026-09-28", "2026-10-03", None, "Rapid-Poste", "RP200052"),
    4513: (4, 189.00, 189.00, "shipped", "2026-10-05", "2026-10-11", None, "Aramex", "ARX100053"),
    4514: (5, 89.00, 0.00, "processing", "2026-10-08", "2026-10-14", None, None, None),
}
FIELDS = ("user_id", "total", "paid", "status", "order_date", "promised_date", "delivered_date",
          "carrier", "tracking_number")


def _q(sql, *args):
    with closing(sqlite3.connect(db.db_path())) as con:
        return con.execute(sql, args).fetchall()


def test_scripted_orders_unchanged():
    for oid, expected in SCRIPTED_BEFORE_P03.items():
        order = get_order(oid)
        assert tuple(order[f] for f in FIELDS) == expected, oid
    refunds = get_refunds(4506)["refunds"]
    assert [(r["amount"], r["status"], r["created_at"]) for r in refunds] == [(189.0, "completed", "2026-09-20")]
    assert get_tracking(4512)["days_late"] == 6
    assert get_tracking(4510)["status"] == "shipped" and get_tracking(4510)["days_late"] == 0


def test_counts_and_labels():
    # T15: the 120 generated orders (ids 5001-5120, users 6-25) were replaced by the real Olist sample
    # (orders 10001+, users 1001+). Clients are drawn until 2,000 orders or more; this draw lands on 2,000 exactly.
    n = len(load_real_sample()["orders"])
    assert n == 2000
    assert _q("SELECT COUNT(*) FROM orders WHERE scripted = 1")[0][0] == 11
    assert _q("SELECT MIN(id), MAX(id), COUNT(*) FROM orders WHERE source = 'olist'")[0] == (10001, 10000 + n, n)
    assert _q("SELECT COUNT(*) FROM orders")[0][0] == 11 + n
    assert _q("SELECT COUNT(*) FROM orders WHERE user_id <= 5 AND id >= 10001")[0][0] == 0  # real clients only


def test_status_mix_and_cash_on_delivery():
    # T15: Olist's REAL status mix is kept (follow-up item 3): mostly delivered, no out_for_delivery, (almost) no
    # shipped on time. The on-time "live" cases come from the scripted orders (4510, 4513).
    statuses = dict(_q("SELECT status, COUNT(*) FROM orders WHERE source = 'olist' GROUP BY status"))
    assert set(statuses) <= {"delivered", "refunded", "stuck_at_depot", "shipped", "processing", "cancelled"}
    assert "out_for_delivery" not in statuses
    assert statuses["delivered"] > 0.9 * sum(statuses.values())  # mostly delivered
    assert {"refunded", "stuck_at_depot", "processing", "cancelled"} <= set(statuses)
    # Cash on delivery not delivered yet: nothing paid.
    assert 1 <= _q("SELECT COUNT(*) FROM orders WHERE paid = 0 AND status != 'cancelled' AND id >= 10001")[0][0] <= 30


def test_dates_are_consistent():
    assert _q("SELECT COUNT(*) FROM orders WHERE delivered_date > '2026-10-09' OR order_date > '2026-10-09'"
              " OR order_date > promised_date OR delivered_date < order_date")[0][0] == 0
    assert _q("SELECT COUNT(*) FROM orders WHERE (status IN ('delivered', 'refunded'))"
              " != (delivered_date IS NOT NULL)")[0][0] == 0
    assert _q("SELECT COUNT(*) FROM orders WHERE delivered_date > promised_date")[0][0] >= 5  # some late


# T15: real orders have a "Delivery" line (the Olist freight), so items + delivery = total. In these 8 real orders
# the client paid another amount than items + delivery in Olist (voucher or instalment interest); their total is
# what was paid, so it differs. They are the only exceptions, listed by id.
PAID_DIFFERENT_FROM_LINES = {10261, 10359, 11014, 11631, 11644, 11705, 11750, 11914}


def test_totals_and_refunds_are_consistent():
    different = set()
    for oid, items, total in _q("SELECT id, items, total FROM orders"):
        if abs(sum(i["price"] * i["qty"] for i in json.loads(items)) - total) >= 0.001:
            different.add(oid)
    assert different == PAID_DIFFERENT_FROM_LINES
    for (oid,) in _q("SELECT id FROM orders WHERE status = 'refunded'"):
        assert abs(get_refunds(oid)["refunded_total"] - get_order(oid)["paid"]) < 0.001, oid  # refunded in full
    over = _q("SELECT COUNT(*) FROM (SELECT o.paid, SUM(r.amount) s FROM orders o JOIN refunds r"
              " ON r.order_id = o.id GROUP BY o.id) WHERE s > paid + 0.001")
    assert over[0][0] == 0  # R-REF-05 holds on all data


def test_layer3_case_4515():
    order, tracking = get_order(4515), get_tracking(4515)
    assert order["paid"] == 378.00 and order["status"] == "stuck_at_depot"
    assert tracking["days_late"] >= 6 and tracking["delivered"] is False
    assert _q("SELECT scripted FROM orders WHERE id = 4515")[0][0] == 1
    assert layer3_decide(4515, 378.00, "late delivery refund")["decision"] == "approved"


def test_days_since_delivery():
    assert get_tracking(4505)["days_since_delivery"] == 25  # 2026-10-09 - 2026-09-14
    assert get_tracking(4507)["days_since_delivery"] == 17
    assert get_tracking(4512)["days_since_delivery"] is None


def test_rebuild_is_identical(tmp_path):
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    seed(a)
    seed(b)
    assert hashlib.md5(a.read_bytes()).hexdigest() == hashlib.md5(b.read_bytes()).hexdigest()


def test_scripted_list_has_11_orders():
    assert [o[0] for o in ORDERS] == list(range(4505, 4516))


# ---- T15: the real Olist sample -------------------------------------------------------------------------------

def test_real_sample_loads():
    sample = load_real_sample()
    for table in ("users", "products", "orders", "reviews"):
        assert _q(f"SELECT COUNT(*) FROM {table} WHERE source = 'olist'")[0][0] == len(sample[table]), table
    assert _q("SELECT COUNT(*) FROM refunds WHERE source = 'generated'")[0][0] == len(sample["refunds"])
    assert "CC BY-NC-SA 4.0" in sample["_note"]


def test_real_ids_start_at_10001_1001_101():
    for table, first in (("orders", 10001), ("users", 1001), ("products", 101)):
        lo, hi, n = _q(f"SELECT MIN(id), MAX(id), COUNT(*) FROM {table} WHERE source = 'olist'")[0]
        assert (lo, hi) == (first, first + n - 1), table   # numbered from `first`, no gap
    # every real order belongs to a real client
    assert _q("SELECT COUNT(*) FROM orders o JOIN users u ON u.id = o.user_id"
              " WHERE o.source = 'olist' AND u.source != 'olist'")[0][0] == 0


def test_no_date_after_sim_today():
    # Nothing that HAPPENED is after sim_today (2026-10-09): orders placed, deliveries, reviews, refunds.
    # A promised date is a promise, not an event: with the real durations kept, an order delivered early can
    # still have its promised date after today (like the scripted 4510, promised 2026-10-10).
    today = sim_start().isoformat()
    assert _q("SELECT COUNT(*) FROM orders WHERE order_date > ? OR delivered_date > ?", today, today)[0][0] == 0
    assert _q("SELECT COUNT(*) FROM reviews WHERE created_at > ?", today)[0][0] == 0
    assert _q("SELECT COUNT(*) FROM refunds WHERE created_at > ?", today)[0][0] == 0
    # the window: every real order was placed in the 90 days before sim_today
    assert _q("SELECT MIN(order_date) FROM orders WHERE source = 'olist'")[0][0] >= "2026-07-11"


def test_real_rows_have_source_and_source_id():
    assert _q("SELECT COUNT(*) FROM orders WHERE scripted = 0"
              " AND (source IS NOT 'olist' OR ai_generated != 0)")[0][0] == 0
    for table in ("users", "products", "orders", "reviews"):
        n, with_id, distinct = _q(f"SELECT COUNT(*), COUNT(source_id), COUNT(DISTINCT source_id) FROM {table}"
                                  " WHERE source = 'olist'")[0]
        assert n == with_id, table               # every real row keeps its Olist id
        if table != "reviews":                   # Olist reuses a few review_ids across orders (a dataset quirk)
            assert with_id == distinct, table


def test_refunds_only_on_late_orders_with_score_1_or_2():
    latest_score = {}
    for oid, score in _q("SELECT order_id, score FROM reviews ORDER BY created_at, id"):
        latest_score[oid] = score          # the latest review of each order wins
    refunded = set()
    for oid, amount, status, rule, paid, order_status, delivered, promised in _q(
            "SELECT r.order_id, r.amount, r.status, r.rule_id, o.paid, o.status, o.delivered_date, o.promised_date"
            " FROM refunds r JOIN orders o ON o.id = r.order_id WHERE r.source = 'generated'"):
        assert delivered > promised and latest_score[oid] <= 2, oid      # late AND unhappy client (real signals)
        assert (amount, status, rule, order_status) == (paid, "completed", "R-RET-01", "refunded"), oid
        assert amount <= 300, oid           # R-ESC-01: no refund above 300 TND without finance approval
        refunded.add(oid)
    # and every real order with those signals (up to 300 TND) was refunded; the ones above 300 stay delivered
    for oid, paid, status in _q("SELECT id, paid, status FROM orders WHERE source = 'olist'"
                                " AND delivered_date > promised_date"):
        if latest_score.get(oid, 5) <= 2:
            assert (oid in refunded) == (paid <= 300), oid
            assert status == ("refunded" if paid <= 300 else "delivered"), oid
    assert len(refunded) > 0


# md5 of the scripted rows (orders 4505-4515, users 1-5, products 1-6, refund 1; the columns that existed before
# T15, labels included) dumped from main 7164f54 BEFORE T15. Same number = not one value changed.
SCRIPTED_ROWS_MD5 = "bab2634bb19a2fe02b1c298c3bb4faeb"
OLD_COLUMNS = {
    "users": ("id, name, email, phone, ai_generated, scripted", "id BETWEEN 1 AND 5"),
    "products": ("id, name, price, stock, ai_generated, scripted", "id BETWEEN 1 AND 6"),
    "orders": ("id, user_id, items, total, paid, status, order_date, promised_date, delivered_date, carrier,"
               " tracking_number, ai_generated, scripted", "id BETWEEN 4505 AND 4515"),
    "refunds": ("id, order_id, amount, status, rule_id, proposal_id, created_at, ai_generated, scripted", "id = 1"),
}


def test_scripted_rows_unchanged_since_main():
    dump = {t: [list(r) for r in _q(f"SELECT {cols} FROM {t} WHERE {where} ORDER BY id")]
            for t, (cols, where) in OLD_COLUMNS.items()}
    assert hashlib.md5(json.dumps(dump, sort_keys=True).encode()).hexdigest() == SCRIPTED_ROWS_MD5
    for t, (_, where) in OLD_COLUMNS.items():
        assert {r[0] for r in _q(f"SELECT source FROM {t} WHERE {where}")} == {"scripted"}, t


def test_delivery_line():
    # T15 follow-up item 1: each real order has ONE "Delivery" line (the real Olist freight), no product;
    # scripted orders have none.
    for oid, items, source in _q("SELECT id, items, source FROM orders"):
        delivery = [i for i in json.loads(items) if i["product_id"] is None]
        if source == "olist":
            assert len(delivery) == 1, oid
            assert delivery[0]["name"] == "Delivery" and delivery[0]["qty"] == 1 and delivery[0]["price"] >= 0, oid
        else:
            assert delivery == [], oid
