"""Agent F: interface tests with a tiny model trained in the test (no download, no models/ file needed)."""
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

from callverse.satisfaction import predict_satisfaction, record_text
from benchmarks.agent_f.evaluate_rated import evaluate

TEXTS = ["terrible awful broken refund now", "bad slow not happy", "ok fine average",
         "good nice works", "excellent perfect love it thank you"] * 4
MODEL = make_pipeline(TfidfVectorizer(), LogisticRegression(max_iter=500)).fit(TEXTS, [1, 2, 3, 4, 5] * 4)


def test_record_text_uses_customer_turns():
    rec = {"messages": [{"role": "customer", "text": "broken"}, {"role": "agent", "content": "sorry"}]}
    assert record_text(rec) == "broken"
    assert record_text({"text": "hi"}) == "hi" and record_text("raw") == "raw"


def test_score_is_int_1_to_5():
    for rec in [{"text": "excellent perfect love it"}, {"text": "terrible awful"}, {"text": ""}, {"messages": []}]:
        s = predict_satisfaction(rec, model=MODEL)
        assert isinstance(s, int) and 1 <= s <= 5
    assert predict_satisfaction({"text": "excellent perfect love it"}, model=MODEL) == 5
    assert predict_satisfaction({"text": "terrible awful broken"}, model=MODEL) == 1


def test_evaluate_rated(monkeypatch):
    import callverse.satisfaction.predictor as p
    monkeypatch.setattr(p, "load_model", lambda *a: MODEL)
    import benchmarks.agent_f.evaluate_rated as ev
    monkeypatch.setattr(ev, "predict_satisfaction", lambda r: p.predict_satisfaction(r, model=MODEL))
    out = evaluate([{"text": "excellent love it", "rating": 5}, {"text": "terrible awful", "rating": 1}])
    assert out["n"] == 2 and out["agent_f"]["mae"] == 0.0
