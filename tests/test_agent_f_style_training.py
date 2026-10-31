"""Offline RL3 style-reward checks using ONLY generated unit-test examples.

These tests are NOT a model performance benchmark and do not involve real support ratings.
"""
import numpy as np
import pytest

from benchmarks.agent_f.train_style import (train_and_validate, validate_rows, persona_id)
from benchmarks.agent_f.evaluate_style_candidate import compare_real
from callverse.quality.satisfaction import STYLES, EMOTIONS, features, predict_satisfaction


class FakeRealReviewModel:
    """Mimics fitted real-review classifier API, with a deterministic middle rating."""
    classes_ = np.array([1, 2, 3, 4, 5])

    def predict_proba(self, texts):
        return np.tile([0.05, 0.1, 0.7, 0.1, 0.05], (len(texts), 1))


def record(persona, scenario, emotion, style, source="simulated"):
    # Explicit style-dependent outcomes are only a UNIT TEST fixture.
    reward = 5 if (emotion == "anger" and style == "apology_first") or (
        emotion == "neutral" and style == "short") else 2
    return {"ticket_id": f"P{persona}-S{scenario}", "company": "shopnova", "persona_id": f"p{persona}",
            "scenario_id": f"sc{scenario}", "situation": {"days_late": 1, "emotion": emotion},
            "style": style, "source": source, "rating": reward,
            "messages": [{"role": "user", "text": "My order has a problem."},
                         {"role": "assistant", "text": "I checked your order."}]}


def data():
    return [record(p, s, ["anger", "neutral"][s % 2], style)
            for p in range(12) for s in range(4) for style in STYLES]


def test_features_interactions_and_size():
    m = FakeRealReviewModel()
    a, b = record(0, 0, "anger", "short"), record(0, 0, "anger", "apology_first")
    va, vb = features(a, m), features(b, m)
    assert len(va) == len(vb) == 3 + len(STYLES) + len(EMOTIONS) + len(STYLES) * len(EMOTIONS)
    assert va != vb
    assert sum(va[-21:]) == sum(vb[-21:]) == 1.0


def test_persona_is_required():
    with pytest.raises(ValueError, match="persona_id"):
        persona_id({})


def test_rejects_real_labels_and_insufficient_data():
    with pytest.raises(ValueError, match="Need >="):
        validate_rows(data()[:10], min_rows=100)
    wrong = data()
    wrong[0] = dict(wrong[0], source="real")
    with pytest.raises(ValueError, match="simulated"):
        validate_rows(wrong, min_rows=1)


def test_train_respects_persona_holdout_and_learns_style():
    m = FakeRealReviewModel()
    learned, report = train_and_validate(data(), m, min_rows=100, min_personas=8)
    assert report["split"]["persona_overlap"] == 0
    assert report["inventory"]["paired_scenarios"] == 48
    assert report["candidate_improves_simulated_mae"]
    assert report["style_effect_present"]
    assert report["real_support_evaluation"].startswith("NOT RUN")
    angry = record(15, 0, "anger", "short")
    apologetic = dict(angry, style="apology_first")
    assert predict_satisfaction(angry, model=m, stacker=learned)["score"] < predict_satisfaction(
        apologetic, model=m, stacker=learned)["score"]
    assert predict_satisfaction(angry, model=m, stacker=False) == predict_satisfaction(
        apologetic, model=m, stacker=False)


def test_real_eval_rejects_simulated_data():
    m = FakeRealReviewModel()
    learned, _ = train_and_validate(data(), m, min_rows=100)
    with pytest.raises(ValueError, match="Simulated"):
        compare_real(data()[:2], m, learned)


def test_unknown_styles_are_rejected():
    r = record(0, 0, "anger", "apology_first")
    r["style"] = "compensation_promise"
    with pytest.raises(ValueError, match="Unsupported reply style"):
        features(r, FakeRealReviewModel())
