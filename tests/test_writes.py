"""Coordinator-only write functions: they write the right rows, refuse bad input, are traced,
and are NOT reachable by agents."""

import json
import sqlite3
from contextlib import closing

from callverse import trace
from callverse.data import db
from callverse.data.writes import create_refund, create_subscription, set_order_status
from callverse.tools import registry
from callverse.tools.shopnova_tools import get_refunds, get_tracking


def _count(table: str) -> int:
    with closing(sqlite3.connect(db.db_path())) as con:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _last_trace() -> dict:
    return json.loads(trace.current_path().read_text(encoding="utf-8").splitlines()[-1])


def test_tests_use_a_temporary_db():
    assert db.db_path() != db.DEFAULT_DB_PATH


def test_create_refund_4512():
    before = _count("refunds")
    row = create_refund(4512, 59.90, "R-REF-03", "p-test")
    assert _count("refunds") == before + 1
    assert row["status"] == "approved"
    assert row["amount"] == 59.90 and row["rule_id"] == "R-REF-03" and row["proposal_id"] == "p-test"
    assert row["created_at"] == "2026-10-09"
    assert row["ai_generated"] == 0 and row["scripted"] == 0
    assert get_refunds(4512) == [row]
    assert _last_trace()["step"] == "db_write"


def test_create_refund_refuses_unknown_order_and_bad_amount():
    assert "error" in create_refund(9999, 10, "R-REF-03", "p")
    assert "error" in create_refund(4512, 0, "R-REF-03", "p")
    assert _last_trace()["step"] == "db_write_refused"
    assert get_refunds(4512) == []


def test_create_subscription():
    row = create_subscription(4512, "out_for_delivery")
    assert row["status"] == "waiting" and row["event"] == "out_for_delivery"
    before = _count("subscriptions")
    assert "error" in create_subscription(4512, "lost")
    assert _count("subscriptions") == before


def test_set_order_status_out_for_delivery_creates_1_event():
    result = set_order_status(4512, "out_for_delivery")
    assert result["old_status"] == "stuck_at_depot"
    assert result["new_status"] == "out_for_delivery"
    assert result["event"]["event"] == "out_for_delivery"
    assert _count("events") == 1
    assert get_tracking(4512)["status"] == "out_for_delivery"


def test_set_order_status_non_event_and_unknown():
    assert set_order_status(4511, "cancelled")["event"] is None
    assert _count("events") == 0
    assert "error" in set_order_status(4512, "teleported")
    assert get_tracking(4512)["status"] == "stuck_at_depot"


def test_delivered_sets_delivered_date():
    set_order_status(4512, "delivered")
    tracking = get_tracking(4512)
    assert tracking["delivered"] is True and tracking["delivered_date"] == "2026-10-09"


def test_write_functions_are_not_tools():
    for name in ("create_refund", "create_subscription", "set_order_status"):
        assert name not in registry.TOOL_FUNCTIONS
        assert name not in registry.TOOL_SCHEMAS
        assert all(name not in allowed for allowed in registry.ALLOW_LISTS.values())
