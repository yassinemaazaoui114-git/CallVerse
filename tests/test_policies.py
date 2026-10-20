"""The ShopNova policy file loads and is well formed."""

import json

import pytest

from callverse.kb.policies import load_policies, notification_events

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
    assert rules["R-REF-05"]["condition"] == "amount <= paid"
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
