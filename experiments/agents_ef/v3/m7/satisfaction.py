"""M7 responsibility 1: a satisfaction score for EVERY closed conversation, learned from the few real reviews.

Pieces (all small, CPU):
  load_scorer(spec)     the tiny model chosen by the Agent F benchmark (v3/f): "f:<checkpoint folder>" for a
                        fine-tuned encoder (v3/f/f_predictor.py), or "none" (no score, the report says so).
  score_all(convs, s)   {conversation_id: score 1-5} from the dialogue text (client message + final reply).
                        Prediction time = when the conversation is closed; nothing later is used.
  ReviewCalibrator      "learns from real reviews": when some clients leave a rating, an isotonic map
                        model score -> rating is fitted on those conversations (cross-validated, so it is
                        kept only if it beats the raw score). Cheap, monotone, needs no retraining.
  review_bias(...)      users who review are not typical: compares reviewed vs all conversations on outcome,
                        priority and emotion (total variation distance) so the owner sees how far the
                        reviewed subset can be trusted.
The score is a PREDICTION. It is labelled with its model and validation card everywhere it is shown.
"""

import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))          # experiments/agents_ef
from v3.m7.conversations import dialogue_text  # noqa: E402


def load_scorer(spec: str):
    if spec in (None, "", "none"):
        return None
    kind, _, path = spec.partition(":")
    if kind == "f":
        from v3.f.f_predictor import SatisfactionPredictor
        return SatisfactionPredictor.load(path)
    raise ValueError(f"unknown scorer spec {spec!r} (use f:<checkpoint folder> or none)")


def score_all(convs: list[dict], scorer, batch: int = 16) -> dict:
    if scorer is None:
        return {}
    texts = [dialogue_text(c) for c in convs]
    preds = scorer.predict(texts)
    return {c["conversation_id"]: float(p["score"]) for c, p in zip(convs, preds)}


class ReviewCalibrator:
    """Isotonic map raw score -> rating, fitted on conversations that HAVE a real review.
    fit() reports a 5-fold cross-validated MAE for raw vs calibrated; use() is True only if calibration helps
    and there are at least min_reviews reviews."""

    def __init__(self, min_reviews: int = 50):
        self.min_reviews, self.model, self.report = min_reviews, None, {}

    def fit(self, raw: np.ndarray, rating: np.ndarray, seed: int = 0) -> dict:
        from sklearn.isotonic import IsotonicRegression
        raw, rating = np.asarray(raw, float), np.asarray(rating, float)
        n = len(raw)
        if n < self.min_reviews:
            self.report = {"n_reviews": n, "used": False, "why": f"fewer than {self.min_reviews} reviews"}
            return self.report
        idx = np.random.default_rng(seed).permutation(n)
        folds = np.array_split(idx, 5)
        err_raw, err_cal = [], []
        for k in range(5):
            te = folds[k]
            tr = np.concatenate([folds[j] for j in range(5) if j != k])
            iso = IsotonicRegression(y_min=1, y_max=5, out_of_bounds="clip").fit(raw[tr], rating[tr])
            err_raw.append(np.abs(np.clip(raw[te], 1, 5) - rating[te]).mean())
            err_cal.append(np.abs(iso.predict(raw[te]) - rating[te]).mean())
        self.model = IsotonicRegression(y_min=1, y_max=5, out_of_bounds="clip").fit(raw, rating)
        used = float(np.mean(err_cal)) < float(np.mean(err_raw))
        self.report = {"n_reviews": n, "cv_mae_raw": round(float(np.mean(err_raw)), 4),
                       "cv_mae_calibrated": round(float(np.mean(err_cal)), 4), "used": used}
        if not used:
            self.model = None
        return self.report

    def apply(self, raw):
        raw = np.asarray(raw, float)
        return self.model.predict(raw) if self.model is not None else np.clip(raw, 1, 5)


def _tv(a: Counter, b: Counter) -> float:
    na, nb = sum(a.values()) or 1, sum(b.values()) or 1
    return 0.5 * sum(abs(a[k] / na - b[k] / nb) for k in set(a) | set(b))


def review_bias(reviews_by_conv: dict, quality_reviews: list[dict], convs: list[dict]) -> dict:
    """How different the reviewed conversations are from all of them (0 = same mix, 1 = disjoint)."""
    emo = {c["conversation_id"]: ((c.get("ticket") or {}).get("emotion") or {}).get("label") for c in convs}
    feats = {"outcome": lambda r: r["outcome"], "priority": lambda r: r["priority"],
             "emotion": lambda r: emo.get(r["conversation_id"])}
    rev = [r for r in quality_reviews if r["conversation_id"] in reviews_by_conv]
    out = {"n_all": len(quality_reviews), "n_reviewed": len(rev),
           "review_rate": round(len(rev) / max(1, len(quality_reviews)), 4)}
    for name, f in feats.items():
        out[f"tv_{name}"] = round(_tv(Counter(map(f, rev)), Counter(map(f, quality_reviews))), 4) if rev else None
    return out
