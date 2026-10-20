"""The ShopNova policy file loads and is well formed."""

import json

import pytest

from callverse.kb.policies import (check_condition, get_policy, layer3_threshold, load_policies,
                                   notification_events)
from callverse.tools.shopnova_tools import get_order, get_refunds, get_tracking

EXPECTED_IDS = ["R-DEL-01", "R-DEL-02", "R-REF-03", "R-REF-05",
                "R-RET-01", "R-DMG-01", "R-ESC-01", "R-NOT-01"]


def test_all_8_rules_load_with_the_4_fields():
    rules = load_policies()
    assert [r["id"] for r in rules] == EXPECTED_IDS
    for r in rules:
        assert {"id", "title", "text", "condition"} <= r.keys()
        assert r["ai_generated"] is True


def test_key_numbers_in_conditions():
    rules = {r["id"]: r for r in load_policies()}
    assert rules["R-REF-03"]["condition"] == "days_late > 5 and not delivered"
    assert rules["R-REF-05"]["condition"] == "amount <= paid - refunded_total"
    assert rules["R-ESC-01"]["condition"] == "amount > 300"
    assert "14" in rules["R-RET-01"]["condition"]
    assert notification_events() == ["shipped", "out_for_delivery", "delivered"]


def test_duplicate_id_is_rejected(tmp_path):
    bad = tmp_path / "bad.json"
    rule = {"id": "R-X", "title": "t", "text": "x", "condition": None}
    bad.write_text(json.dumps([rule, rule]), encoding="utf-8")
    with pytest.raises(ValueError):
        load_policies(bad)


def test_missing_field_is_rejected(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"id": "R-X", "title": "t", "text": "x"}]), encoding="utf-8")
    with pytest.raises(ValueError):
        load_policies(bad)


def _facts(order_id, amount):
    order, tracking, refunds = get_order(order_id), get_tracking(order_id), get_refunds(order_id)
    return {"amount": amount, "paid": order["paid"], "refunded_total": refunds["refunded_total"],
            "days_late": tracking["days_late"], "delivered": tracking["delivered"]}


def test_r_ref_05_blocks_second_refund_of_4506():
    rule = get_policy("R-REF-05")["condition"]
    assert check_condition(rule, _facts(4506, 1)) is False      # 189 paid, 189 already refunded
    assert check_condition(rule, _facts(4512, 59.90)) is True
    assert check_condition(rule, _facts(4512, 70.00)) is False
    assert check_condition(rule, _facts(4514, 1)) is False      # cash on delivery, 0 paid


def test_other_conditions_on_real_data():
    assert check_condition(get_policy("R-REF-03")["condition"], _facts(4512, 59.90)) is True
    assert check_condition(get_policy("R-REF-03")["condition"], _facts(4507, 10)) is False  # delivered
    assert check_condition(get_policy("R-DEL-02")["condition"], {"days_late": 3, "delivered": False}) is True
    assert check_condition(get_policy("R-DEL-02")["condition"], {"days_late": 6, "delivered": False}) is False
    assert check_condition(get_policy("R-NOT-01")["condition"], {"event": "lost"}) is False
    assert check_condition(get_policy("R-ESC-01")["condition"], {"amount": 300.01}) is True


def test_check_condition_refuses_code_and_missing_facts():
    with pytest.raises(ValueError):
        check_condition("__import__('os').system('echo hi')", {})
    with pytest.raises(ValueError):
        check_condition("amount <= paid", {"amount": 1})


def test_layer3_threshold_comes_from_r_esc_01():
    assert layer3_threshold() == 300.0


def test_r_ret_01_uses_days_since_delivery():
    rule = get_policy("R-RET-01")["condition"]
    t4505, t4512 = get_tracking(4505), get_tracking(4512)
    assert check_condition(rule, {"delivered": t4505["delivered"],
                                  "days_since_delivery": t4505["days_since_delivery"]}) is False  # 25 days
    assert check_condition(rule, {"delivered": t4512["delivered"],
                                  "days_since_delivery": t4512["days_since_delivery"]}) is False  # not delivered
    assert check_condition(rule, {"delivered": True, "days_since_delivery": 10}) is True
