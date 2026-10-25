"""Tests: reviews data contract (F5) and the annotation evaluation pipeline (F3). Fixtures are SYNTHETIC."""

import copy
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from v4.f.annotation.eval_labels import evaluate, krippendorff_ordinal  # noqa: E402
from v4.f.annotation.make_synthetic_fixture import make  # noqa: E402
from v4.f.contracts.validate_reviews import usable_for_validation, validate  # noqa: E402
from v3.f.uss_data import krippendorff_interval  # noqa: E402

CUSTOMER = {"schema_version": "0.1", "record_id": "r1", "conversation_id": "run_1", "ticket_id": "T-1",
            "order_id": 4512, "rating_source": "customer_submitted", "rating": 4, "predicted_score": None,
            "prediction": None, "annotator_id": None, "feedback_text": "Quick answer, thanks",
            "submitted_at": "2026-10-09T10:00:00", "conversation_closed_at": "2026-10-09T09:58:00",
            "channel": "chat", "language": "fr",
            "consent": {"given": True, "scope": ["quality_reporting", "model_validation"]},
            "pii_redaction": {"status": "none_found", "method": "regex+human", "checked_by": "Y"},
            "data_quality": {"is_duplicate": False, "is_test_or_synthetic": False}}
PREDICTED = {**CUSTOMER, "record_id": "r2", "rating_source": "ai_predicted", "rating": None, "predicted_score": 3.3,
             "feedback_text": None, "channel": "agent_f",
             "prediction": {"model_id": "tfidf_ridge_tail256", "model_sha256": "1c2018532cf6b50631eca9e150e66b94f2ac"
                            "8c1cdfead1d620e44b7088a75261", "label_type_trained_on": "human_annotation",
                            "validity": "indicative_out_of_domain"}}


def test_valid_measured_and_predicted_records():
    assert validate(CUSTOMER) == [] and validate(PREDICTED) == []
    assert usable_for_validation(CUSTOMER) is True and usable_for_validation(PREDICTED) is False


@pytest.mark.parametrize("change,rule", [
    ({"rating_source": "ai_predicted"}, "R2"),                       # a "prediction" with a measured rating
    ({"predicted_score": 3.1}, "R1"),                                 # measured record carrying a prediction
    ({"pii_redaction": {"status": "not_done"}}, "R4"),
    ({"consent": {"given": False, "scope": []}}, "R5"),
    ({"rating_source": "annotator"}, "R3"),
    ({"rating": 6}, "> 5"), ({"rating": 0}, "< 1"), ({"rating": 4.5}, "type"),
    ({"language": "de"}, "not in"), ({"stars": 5}, "unknown field"), ({"submitted_at": "yesterday"}, "ISO 8601"),
])
def test_contract_rejects(change, rule):
    r = {**copy.deepcopy(CUSTOMER), **change}
    errs = validate(r)
    assert any(rule in e for e in errs), errs


def test_prediction_needs_model_identity_and_rating_null():
    p = copy.deepcopy(PREDICTED)
    p["prediction"]["model_sha256"] = "abc"
    assert any("pattern" in e or "match" in e for e in validate(p))
    p = {**copy.deepcopy(PREDICTED), "prediction": None}
    assert any(e.startswith("R2") for e in validate(p))
    withheld = copy.deepcopy(PREDICTED)
    withheld["predicted_score"] = None
    withheld["prediction"]["validity"] = "withheld_language_not_validated"
    assert validate(withheld) == []                                   # boundary: a withheld score is allowed


def test_synthetic_or_unconsented_records_are_not_labels():
    assert usable_for_validation({**CUSTOMER, "data_quality": {"is_duplicate": False, "is_test_or_synthetic": True}}) \
        is False
    assert usable_for_validation({**CUSTOMER, "consent": {"given": True, "scope": ["quality_reporting"]}}) is False


# ---------------- agreement ----------------

def test_krippendorff_ordinal_properties():
    assert krippendorff_ordinal([[3, 3, 3], [1, 1], [5, 5, 5]]) == pytest.approx(1.0)
    rng = np.random.default_rng(0)
    rand = [list(rng.integers(1, 6, 3)) for _ in range(3000)]
    assert abs(krippendorff_ordinal(rand)) < 0.03                    # independent raters -> about 0
    binary = [list(rng.integers(0, 2, 3)) for _ in range(300)]
    assert krippendorff_ordinal(binary) == pytest.approx(krippendorff_interval(binary), abs=1e-9)


# ---------------- evaluation pipeline on the SYNTHETIC fixture ----------------

def test_pipeline_drops_synthetic_records_by_default():
    labels, preds, split = make()
    rep, card = evaluate(labels, preds, split)
    assert rep["n_conversations_labelled"] == 0 and rep["dropped"]["test or synthetic record"] == len(labels)


def test_pipeline_on_synthetic_fixture_marks_card_and_never_opens_gate():
    labels, preds, split = make()
    rep, card = evaluate(labels, preds, split, allow_synthetic=True)
    assert card["SYNTHETIC"] is True and card["label_type"] == "synthetic_fixture"
    assert rep["gate"]["e_reward_allowed"] is False
    assert rep["agreement"]["n_units_multi_rated"] == 60 and 0 < rep["agreement"]["krippendorff_alpha_ordinal"] < 1
    assert rep["test_not_scored_by_language"].get("fr", 0) > 0 and rep["test_coverage"] < 1   # French withheld
    assert set(rep["model_test_by_language"]) == {"en"}
    assert rep["model_test"]["n"] == rep["split"]["test"] - rep["test_not_scored"]


def test_dev_test_overlap_is_refused():
    labels, preds, split = make()
    split["test"].append(split["dev"][0])
    with pytest.raises(ValueError):
        evaluate(labels, preds, split, allow_synthetic=True)


def test_customer_ratings_give_genuine_label_type_but_small_n_fails_gate():
    recs, preds = [], []
    rng = np.random.default_rng(1)
    for i in range(40):
        cid = f"run_{i}"
        recs.append({**copy.deepcopy(CUSTOMER), "record_id": f"r{i}", "conversation_id": cid,
                     "rating": int(rng.integers(1, 6)), "language": "en"})
        preds.append({"conversation_id": cid, "predicted_satisfaction": float(rng.uniform(2, 4))})
    split = {"dev": [f"run_{i}" for i in range(10)], "test": [f"run_{i}" for i in range(10, 40)]}
    rep, card = evaluate(recs, preds, split)
    assert card["label_type"] == "genuine_customer_rating" and card["corpus"] == "callverse"
    assert rep["agreement"]["n_units_multi_rated"] == 0                       # one rating per conversation
    assert rep["gate"]["e_reward_allowed"] is False and any("test_n" in r for r in rep["gate"]["reasons"])
