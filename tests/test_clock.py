"""P08: simulation clock + scripted delivery timeline (story S3). Temporary DB only (conftest)."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime

from fastapi.testclient import TestClient

from callverse import trace
from callverse.config import sim_start, sim_today
from callverse.data import clock, db
from callverse.data.reports import get_pending_notifications
from callverse.data.writes import create_subscription, record_decision, record_proposal, set_order_status
from callverse.tools.shopnova_tools import get_order, get_tracking

ORDER = 4510   # the timeline order: shipped, promised 2026-10-10, on time


def _event_rows(order_id=ORDER) -> list:
    with closing(sqlite3.connect(db.db_path())) as con:
        return con.execute("SELECT event, at, scripted FROM events WHERE order_id = ? ORDER BY id",
                           (order_id,)).fetchall()


def test_clock_starts_at_config_date_9am_and_sim_today_follows_it():
    assert clock.now() == datetime(2026, 10, 9, 9, 0) == clock.start()
    assert sim_today() == sim_start() == datetime(2026, 10, 9).date()
    clock.advance(15)                                   # 09:00 + 15 h = next day 00:00
    assert clock.now() == datetime(2026, 10, 10, 0, 0)
    assert sim_today().isoformat() == "2026-10-10" and sim_start().isoformat() == "2026-10-09"


def test_timeline_24h_then_30h_then_no_repeat():
    r = clock.advance(24)
    assert get_order(ORDER)["status"] == "out_for_delivery"
    assert len(r["applied"]) == 1 and r["applied"][0]["applied"] is True
    assert _event_rows() == [("out_for_delivery", "2026-10-10", 1)]           # exactly 1 new row, scripted

    r = clock.advance(6)                                                      # 30 h in total
    assert get_order(ORDER)["status"] == "delivered" and len(r["applied"]) == 1
    assert [e[0] for e in _event_rows()] == ["out_for_delivery", "delivered"]
    tracking = get_tracking(ORDER)
    assert tracking["delivered"] is True and tracking["delivered_date"] == "2026-10-10"
    assert tracking["days_late"] == 0                                         # promised 2026-10-10: on time

    r = clock.advance(10)
    assert r["applied"] == [] and len(_event_rows()) == 2                     # no repeat


def test_one_big_step_applies_both_events_in_order():
    r = clock.advance(48)
    assert [e["status"] for e in r["applied"]] == ["out_for_delivery", "delivered"]
    assert get_order(ORDER)["status"] == "delivered"


def test_pending_notification_appears_only_after_delivery():
    pid = record_proposal({"agent": "A", "action": "subscribe", "params": {"order_id": ORDER, "event": "delivered"},
                           "rule_id": "R-NOT-01", "facts_used": {}, "user_confirmed": True})["id"]
    record_decision(pid, "approve", "R-NOT-01")
    sub = create_subscription(ORDER, "delivered", pid)
    assert get_pending_notifications() == []
    clock.advance(24)                                   # out_for_delivery: not the subscribed event
    assert get_pending_notifications() == []
    clock.advance(6)                                    # delivered
    pending = get_pending_notifications()
    assert len(pending) == 1 and pending[0]["subscription_id"] == sub["id"] and pending[0]["event"] == "delivered"
    assert pending[0]["event_at"] == "2026-10-10"


def test_days_late_follows_the_clock():
    assert get_tracking(4512)["days_late"] == 6
    clock.advance(48)
    assert get_tracking(4512)["days_late"] == 8


def test_reset_restores_clock_and_order():
    clock.advance(30)
    assert get_order(ORDER)["status"] == "delivered"
    r = clock.reset()
    assert r["orders_restored"] == [ORDER]
    assert clock.now() == datetime(2026, 10, 9, 9, 0)
    order = get_order(ORDER)
    assert order["status"] == "shipped" and order["delivered_date"] is None
    assert _event_rows() == []
    r = clock.advance(24)                               # the timeline can play again after a reset
    assert get_order(ORDER)["status"] == "out_for_delivery" and len(r["applied"]) == 1


def test_wrong_timeline_event_is_refused_and_reported(tmp_path, monkeypatch):
    bad = tmp_path / "timeline.json"
    bad.write_text(json.dumps({"events": [
        {"id": "x1", "order_id": 4505, "after_hours": 1, "status": "shipped"},    # delivered -> shipped: illegal
        {"id": "x2", "order_id": 4511, "after_hours": 2, "status": "shipped"},    # processing -> shipped: fine
    ]}), encoding="utf-8")
    monkeypatch.setattr(clock, "TIMELINE_PATH", bad)
    r = clock.advance(3)                                # no exception
    refused, ok = r["applied"]
    assert refused["applied"] is False and "not allowed" in refused["reason"]
    assert ok["applied"] is True and get_order(4511)["status"] == "shipped"
    assert get_order(4505)["status"] == "delivered"     # unchanged
    assert clock.advance(5)["applied"] == []            # the refused event is not retried


def test_advance_refuses_bad_hours_and_traces():
    for bad in (0, -5, float("nan"), float("inf"), float("-inf"), 1e9, clock.MAX_HOURS + 1, True, "24"):
        assert "error" in clock.advance(bad)
    assert clock.now() == clock.start()
    clock.advance(1)
    last = json.loads(trace.current_path().read_text(encoding="utf-8").splitlines()[-1])
    assert last["step"] == "clock_advance" and last["actor"] == "clock"


def test_advance_huge_or_infinite_hours_returns_error_not_crash():
    for bad in (float("inf"), 1e9, clock.MAX_HOURS + 0.5):
        result = clock.advance(bad)                      # must not raise OverflowError
        assert "error" in result
    assert clock.now() == clock.start()                  # clock unchanged
    assert "error" not in clock.advance(clock.MAX_HOURS) # the limit itself is allowed


def test_status_changes_still_use_the_transition_table():
    set_order_status(ORDER, "out_for_delivery")          # moved by hand before the timeline
    r = clock.advance(24)                                # t1 (out_for_delivery again) is refused: same status
    assert r["applied"][0]["applied"] is False


def test_server_shows_the_clock_read_only():
    from callverse.server.app import app
    client = TestClient(app)
    assert client.get("/clock").json()["now"] == "2026-10-09T09:00:00"
    clock.advance(30)
    assert client.get("/clock").json()["today"] == "2026-10-10"
    paths = client.get("/openapi.json").json()["paths"]
    assert "post" not in paths["/clock"] and not any("clock" in p and "post" in v for p, v in paths.items())
