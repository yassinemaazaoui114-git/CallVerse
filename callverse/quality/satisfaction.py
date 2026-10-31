"""Agent F (RL3) - predict user satisfaction for one conversation. Contract: docs RL_interface_spec v1.

    predict_satisfaction(record: dict) -> {"score": float 1..5}

record = {"ticket_id", "company", "messages": [{"role": "user"|"assistant", "text"}], "situation": {...}, "style"}
CPU only, ~2-5 ms per record, no API, no database write.

How the score is made (two real-data parts + one optional part):
1. TEXT: what the user wrote -> TF-IDF + logistic regression trained on REAL reviews with REAL 1-5 stars
   (amazon_reviews_multi_en). Output = expected stars (sum of p(k) * k), a float.
2. DELAY: situation["days_late"] -> average REAL Olist review score for that delay (ShopNova sample, delivered vs
   promised date). Table in DELAY_TABLE below, rebuilt by benchmarks/agent_f/olist_delay.py.
3. Blend: 0.5 * text + 0.5 * delay when days_late is known, else text only. PROVISIONAL weights: no real rated
   conversations exist to fit them (the team set is test-only). If models/agent_f/stacker.pkl exists (fitted on
   Mahmoud's SIMULATED ratings, flagged as such), it replaces the fixed blend and also uses style + emotion,
   which is what lets the RL reward differ between styles.
"""
from __future__ import annotations

import pickle
from functools import lru_cache
from pathlib import Path

MODEL_DIR = Path(__file__).resolve().parents[2] / "models" / "agent_f"
TEXT_MODEL = MODEL_DIR / "satisfaction.pkl"
STACKER = MODEL_DIR / "stacker.pkl"

# Real Olist (ShopNova sample): mean review score by days late. Keys = upper bound of the bucket (days).
# Built by benchmarks/agent_f/olist_delay.py (n per bucket in docs/agent_f.md).
DELAY_TABLE = [(0, 4.22), (2, 3.07), (5, 2.5), (10, 1.57), (10_000, 1.4)]
STYLES = ["short", "apology_first", "apology_next_step"]
EMOTIONS = ["anger", "disgust", "fear", "joy", "neutral", "sadness", "surprise"]


def user_text(record: dict) -> str:
    """Join what the USER wrote (the reply is not scored by the text model: it was trained on customer text)."""
    msgs = record.get("messages") or []
    return "\n".join(m.get("text", "") for m in msgs if m.get("role") == "user").strip()


def delay_prior(days_late) -> float | None:
    if days_late is None:
        return None
    for upper, mean in DELAY_TABLE:
        if float(days_late) <= upper:
            return mean
    return DELAY_TABLE[-1][1]


@lru_cache(maxsize=4)
def _load(path: str):
    p = Path(path)
    if not p.exists():
        return None
    with open(p, "rb") as f:
        return pickle.load(f)


def text_score(text: str, model=None) -> float:
    model = model or _load(str(TEXT_MODEL))
    if model is None:
        raise FileNotFoundError(f"Agent F model missing: {TEXT_MODEL}. Run: python -m benchmarks.agent_f.train")
    if not text:
        return 3.0
    probs = model.predict_proba([text])[0]
    return float(sum(p * k for p, k in zip(probs, model.classes_)))


def features(record: dict, model=None) -> list[float]:
    """Stacker input: text score, delay prior (or 0 + flag), style one-hot, emotion one-hot."""
    sit = record.get("situation") or {}
    d = delay_prior(sit.get("days_late"))
    return ([text_score(user_text(record), model), d or 0.0, float(d is None)]
            + [float(record.get("style") == s) for s in STYLES]
            + [float(sit.get("emotion") == e) for e in EMOTIONS])


def predict_satisfaction(record: dict, model=None, stacker=None) -> dict:
    """Return {"score": float in [1, 5]}. stacker=False forces the fixed blend (tests, ablations)."""
    if stacker is None:
        stacker = _load(str(STACKER))
    if stacker:
        score = float(stacker.predict([features(record, model)])[0])
    else:
        t = text_score(user_text(record), model)
        d = delay_prior((record.get("situation") or {}).get("days_late"))
        score = t if d is None else 0.5 * t + 0.5 * d
    return {"score": round(min(5.0, max(1.0, score)), 3)}
