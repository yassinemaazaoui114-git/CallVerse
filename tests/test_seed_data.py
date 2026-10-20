"""Generated data: volume, labels, consistency, determinism; scripted cases untouched."""

import hashlib
import json
import sqlite3
from contextlib import closing

from callverse.data import db
from callverse.data.layer3 import layer3_decide
from callverse.data.seed import ORDERS, seed
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
    assert _q("SELECT COUNT(*) FROM orders WHERE scripted = 1")[0][0] == 11
    generated = _q("SELECT MIN(id), MAX(id), COUNT(*) FROM orders WHERE scripted = 0 AND ai_generated = 1")[0]
    assert generated == (5001, 5120, 120)
    assert _q("SELECT COUNT(*) FROM orders")[0][0] == 131
    assert _q("SELECT COUNT(*) FROM orders WHERE user_id <= 5 AND id >= 5001")[0][0] == 0  # generated users only


def test_status_mix_and_cash_on_delivery():
    statuses = dict(_q("SELECT status, COUNT(*) FROM orders WHERE id >= 5001 GROUP BY status"))
    assert set(statuses) == {"delivered", "shipped", "processing", "out_for_delivery",
                             "stuck_at_depot", "cancelled", "refunded"}
    assert statuses["delivered"] > 60  # mostly delivered
    assert 1 <= _q("SELECT COUNT(*) FROM orders WHERE paid = 0 AND status != 'cancelled' AND id >= 5001")[0][0] <= 15


def test_dates_are_consistent():
    assert _q("SELECT COUNT(*) FROM orders WHERE delivered_date > '2026-10-09' OR order_date > '2026-10-09'"
              " OR order_date > promised_date OR delivered_date < order_date")[0][0] == 0
    assert _q("SELECT COUNT(*) FROM orders WHERE (status IN ('delivered', 'refunded'))"
              " != (delivered_date IS NOT NULL)")[0][0] == 0
    assert _q("SELECT COUNT(*) FROM orders WHERE delivered_date > promised_date")[0][0] >= 5  # some late


def test_totals_and_refunds_are_consistent():
    for items, total in _q("SELECT items, total FROM orders"):
        assert abs(sum(i["price"] * i["qty"] for i in json.loads(items)) - total) < 0.001
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
