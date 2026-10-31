"""Agent F dual reward (correctness + satisfaction -> RL reward). Tiny text model, no models/ file, no LLM."""
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

from callverse.quality.reward import check_correctness, evaluate_response, reward_of

TEXTS = ["terrible awful broken refund now", "bad slow not happy", "ok fine average",
         "good nice works", "excellent perfect love it thank you"] * 4
MODEL = make_pipeline(TfidfVectorizer(), LogisticRegression(max_iter=500)).fit(TEXTS, [1, 2, 3, 4, 5] * 4)
KW = {"model": MODEL, "stacker": False}

DECISION = {"outcome": "approve", "action": "refund", "order_id": 4512, "rule_id": "R-REF-03",
            "facts": {"amount_tnd": 59.90, "days_late": 6, "delivered": False, "order_status": "stuck_at_depot"},
            "next_step": "The money goes back to the card you paid with.",
            "must_say": ["Your refund of 59.90 TND is approved."]}
GOOD_REPLY = "About your order 4512: Your refund of 59.90 TND is approved. The money goes back to the card you paid with."


def rec(user_text, reply, decision=DECISION, company="shopnova", days_late=6):
    return {"ticket_id": "T-1", "company": company, "style": "short",
            "situation": {"days_late": days_late, "emotion": "anger"},
            "messages": [{"role": "user", "text": user_text}, {"role": "assistant", "text": reply}],
            "decision": decision}


def test_correct_and_satisfying_gets_plus_one():
    # days_late=0: the real Olist delay prior (4.22) does not drag a happy customer below 4
    out = evaluate_response(rec("excellent perfect love it thank you", GOOD_REPLY, days_late=0), **KW)
    assert out["correctness"] == "PASS" and out["reward"] == 1 and out["train"]


def test_correct_but_unsatisfying_gets_minus_one():
    out = evaluate_response(rec("terrible awful broken", GOOD_REPLY), **KW)
    assert out["correctness"] == "PASS" and out["satisfaction"] < 4 and out["reward"] == -1


def test_incorrect_but_satisfying_never_positive():
    wrong = "About your order 4512: Your refund of 59.90 TND is approved. You will receive 80 TND within 2 days."
    out = evaluate_response(rec("excellent perfect love it thank you", wrong), **KW)
    assert out["correctness"] == "FAIL" and out["reward"] == -1
    assert any("numbers not in the decision" in e for e in out["evidence"])


def test_missing_evidence_is_unknown_and_excluded():
    out = evaluate_response(rec("ok fine", GOOD_REPLY, decision=None), **KW)
    assert out["correctness"] == "UNKNOWN" and out["reward"] is None and not out["train"]
    assert check_correctness(rec("ok", "", DECISION))["status"] == "UNKNOWN"


def test_cross_tenant_rule_fails():
    out = check_correctness(rec("ok", GOOD_REPLY, company="atlas"))   # R-REF-03 is a ShopNova rule
    assert out["status"] == "FAIL" and any("tenant" in e for e in out["evidence"])


def test_unauthorized_refund_promise_fails():
    info = {"outcome": "info", "action": "status", "order_id": 4512, "rule_id": "R-DEL-02",
            "facts": {"days_late": 3, "delivered": False, "order_status": "in_transit"},
            "next_step": "We will tell you as soon as it ships."}
    reply = "About your order 4512: it is 3 days late. Your refund will be processed today."
    out = check_correctness(rec("where is it", reply, decision=info))
    assert out["status"] == "FAIL" and any("refund" in e for e in out["evidence"])


def test_policy_condition_not_met_fails():
    bad = DECISION | {"facts": {"amount_tnd": 59.90, "days_late": 2, "delivered": False}}
    out = check_correctness(rec("ok", GOOD_REPLY, decision=bad))
    assert out["status"] == "FAIL" and any("condition does not hold" in e for e in out["evidence"])


def test_reward_table():
    assert reward_of("PASS", 4.0) == 1 and reward_of("PASS", 3.99) == -1
    assert reward_of("FAIL", 5.0) == -1 and reward_of("UNKNOWN", 5.0) is None


def test_predict_satisfaction_still_compatible():
    from callverse.quality.satisfaction import predict_satisfaction
    out = predict_satisfaction(rec("good nice works", GOOD_REPLY), **KW)
    assert set(out) == {"score"} and 1.0 <= out["score"] <= 5.0
