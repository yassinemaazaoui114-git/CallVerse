"""Agent F (RL3): contract tests with a tiny model trained here (no download, no models/ file needed)."""
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline

from benchmarks.agent_f.evaluate_rated import evaluate
from callverse.quality import satisfaction as F

TEXTS = ["terrible awful broken refund now", "bad slow not happy", "ok fine average",
         "good nice works", "excellent perfect love it thank you"] * 4
MODEL = make_pipeline(TfidfVectorizer(), LogisticRegression(max_iter=500)).fit(TEXTS, [1, 2, 3, 4, 5] * 4)


def rec(text, days_late=None, style="short"):   # spec "Conversation record"
    sit = {"company": "shopnova", "emotion": "anger"} | ({"days_late": days_late} if days_late is not None else {})
    return {"ticket_id": "T-0001", "company": "shopnova", "style": style, "situation": sit,
            "messages": [{"role": "user", "text": text}, {"role": "assistant", "text": "We are sorry, refund sent."}]}


def test_output_contract():
    for r in [rec("excellent perfect love it"), rec("terrible awful", 6), rec(""), {"messages": []}]:
        out = F.predict_satisfaction(r, model=MODEL, stacker=False)
        assert set(out) == {"score"} and isinstance(out["score"], float) and 1.0 <= out["score"] <= 5.0


def test_only_user_turns_are_read():
    assert F.user_text(rec("broken")) == "broken"


def test_text_and_delay_move_the_score():
    good = F.predict_satisfaction(rec("excellent perfect love it"), model=MODEL, stacker=False)["score"]
    bad = F.predict_satisfaction(rec("terrible awful broken"), model=MODEL, stacker=False)["score"]
    late = F.predict_satisfaction(rec("excellent perfect love it", 20), model=MODEL, stacker=False)["score"]
    assert bad < late < good
    assert F.delay_prior(0) > F.delay_prior(6) > F.delay_prior(30)


def test_stacker_uses_style():
    X = [F.features(rec("ok fine", 0, s), MODEL) for s in F.STYLES]
    st = Ridge().fit(X, [2.0, 4.0, 3.0])
    a = F.predict_satisfaction(rec("ok fine", 0, "short"), model=MODEL, stacker=st)["score"]
    b = F.predict_satisfaction(rec("ok fine", 0, "apology_first"), model=MODEL, stacker=st)["score"]
    assert a < b


def test_evaluate_rated_reports_spec_metrics():
    recs = [rec("excellent love it") | {"rating": 5}, rec("terrible awful", 20) | {"rating": 1},
            rec("ok fine") | {"rating": 3}]
    out = evaluate(recs, predict=lambda r: F.predict_satisfaction(r, model=MODEL, stacker=False))
    assert out["n"] == 3 and {"mae", "spearman"} <= set(out["agent_f"])
    assert {"baseline_average", "baseline_delay_only", "ms_p95"} <= set(out)
