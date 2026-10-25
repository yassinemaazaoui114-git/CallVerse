"""F -> E contract: the reward channel stays closed unless F's flag AND a passing validation card agree."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from v4.d.fe_contract import aggregate, reward_allowed  # noqa: E402

GOOD_CARD = {"model": "m", "label_type": "genuine_customer_rating", "domain": "support_conversation",
             "test_n": 1000, "mae": 0.5, "mae_mean_baseline": 0.8, "spearman_ci_low": 0.45}
USS_CARD = {**GOOD_CARD, "label_type": "human_annotation", "domain": "task_oriented_dialogue"}


def rec(cid, s, eligible, card, reason="damaged_item", t="2026-10-09T09:03:00"):
    return {"conversation_id": cid, "closed_at": t, "main_reason": reason, "predicted_satisfaction": s,
            "e_reward_eligible": eligible, "eligibility_reasons": [] if eligible else ["labels are annotations"],
            "validation_card": card}


def test_current_reality_everything_is_kpi_only():
    out = aggregate([rec("a", 2.0, False, USS_CARD), rec("b", 4.0, False, USS_CARD, reason="order_status")])
    assert out["reward"] == {} and len(out["refusals"]) == 2
    assert out["kpi_only"][("2026-10-09T09:00:00", "C_urgent")] == {"n": 1, "shortfall_sum": 0.75}


def test_f_flag_alone_is_not_enough():
    ok, why = reward_allowed(rec("a", 3.0, True, USS_CARD))       # F says eligible, but the card fails the gate
    assert not ok and "label_type" in why[0]


def test_card_alone_is_not_enough():
    ok, why = reward_allowed(rec("a", 3.0, False, GOOD_CARD))
    assert not ok and "not eligible" in why[0]


def test_both_agree_then_reward_channel_in_envv3_units():
    out = aggregate([rec("a", 5.0, True, GOOD_CARD), rec("b", 1.0, True, GOOD_CARD, t="2026-10-09T09:04:59")])
    assert out["reward"][("2026-10-09T09:00:00", "C_urgent")] == {"n": 2, "shortfall_sum": 1.0}
    assert out["refusals"] == []


def test_bad_scores_refused():
    for s in (None, 0.5, 6, "3"):
        assert reward_allowed(rec("a", s, True, GOOD_CARD))[0] is False
