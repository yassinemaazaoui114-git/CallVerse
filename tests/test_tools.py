"""The tools return the right data for the demo order 4512."""

from callverse.tools.shopnova_tools import get_order, get_refunds, get_tracking, get_user


def test_get_order_4512():
    order = get_order(4512)
    assert order["user_id"] == 1
    assert order["total"] == 59.90
    assert order["paid"] == 59.90
    assert order["status"] == "stuck_at_depot"
    assert order["order_date"] == "2026-09-28"
    assert order["promised_date"] == "2026-10-03"
    assert order["delivered_date"] is None


def test_get_tracking_4512_is_6_days_late():
    tracking = get_tracking(4512)
    assert tracking["status"] == "stuck_at_depot"
    assert tracking["delivered"] is False
    assert tracking["days_late"] == 6  # sim_today 2026-10-09 - promised 2026-10-03


def test_get_user_sara():
    user = get_user(email="sara@example.com")
    assert user["name"].startswith("Sara")
    assert get_user(user_id=1) == user


def test_unknown_order_returns_error():
    assert "error" in get_order(9999)


def test_get_refunds():
    r4506 = get_refunds(4506)
    assert r4506["order_id"] == 4506 and r4506["refunded_total"] == 189.0
    assert len(r4506["refunds"]) == 1
    assert r4506["refunds"][0]["amount"] == 189.00 and r4506["refunds"][0]["status"] == "completed"
    assert get_refunds(4512) == {"order_id": 4512, "refunds": [], "refunded_total": 0.0}
    assert "error" in get_refunds(9999)


def test_get_refunds_is_not_on_any_allow_list_yet():
    from callverse.tools.registry import ALLOW_LISTS
    assert all("get_refunds" not in allowed for allowed in ALLOW_LISTS.values())


def test_labels_on_seed_data():
    import sqlite3
    from contextlib import closing
    from callverse.data import db
    with closing(sqlite3.connect(db.db_path())) as con:
        assert con.execute("SELECT COUNT(*) FROM orders WHERE ai_generated = 1 AND scripted = 1").fetchone()[0] == 11
        for table in ("users", "products", "orders", "refunds"):
            assert con.execute(f"SELECT COUNT(*) FROM {table} WHERE ai_generated = 0").fetchone()[0] == 0



def test_get_company_profile():
    import json as _json
    from callverse.tools.shopnova_tools import COMPANY_PROFILE_PATH, get_company_profile
    profile = get_company_profile()
    assert profile == _json.loads(COMPANY_PROFILE_PATH.read_text(encoding="utf-8"))  # all fields
    for field in ("name", "domain", "description", "cities_served", "carriers", "delivery_promise_days",
                  "currency", "support_channels", "ai_generated"):
        assert field in profile
    assert profile["name"] == "ShopNova" and profile["currency"] == "TND"


def test_get_company_profile_is_not_on_any_allow_list():
    from callverse.tools.registry import ALLOW_LISTS
    assert all("get_company_profile" not in allowed for allowed in ALLOW_LISTS.values())


def test_seed_uses_sim_today_from_config():
    from pathlib import Path as _Path
    seed_text = (_Path(__file__).resolve().parent.parent / "callverse" / "data" / "seed.py").read_text(encoding="utf-8")
    assert "2026, 10, 9" not in seed_text and "SIM_TODAY" not in seed_text
