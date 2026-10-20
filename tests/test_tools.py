"""The tools return the right data for the demo order 4512."""

from callverse.tools.shopnova_tools import get_order, get_tracking, get_user


def test_get_order_4512():
    order = get_order(4512)
    assert order["user_id"] == 1
    assert order["total"] == 59.90
    assert order["paid"] == 59.90
    assert order["status"] == "stuck at depot"
    assert order["order_date"] == "2026-09-28"
    assert order["promised_date"] == "2026-10-03"
    assert order["delivered_date"] is None


def test_get_tracking_4512_is_6_days_late():
    tracking = get_tracking(4512)
    assert tracking["status"] == "stuck at depot"
    assert tracking["delivered"] is False
    assert tracking["days_late"] == 6  # sim_today 2026-10-09 - promised 2026-10-03


def test_get_user_sara():
    user = get_user(email="sara@example.com")
    assert user["name"].startswith("Sara")
    assert get_user(user_id=1) == user


def test_unknown_order_returns_error():
    assert "error" in get_order(9999)
