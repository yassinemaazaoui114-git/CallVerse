"""Agent F (RL3): predicted satisfaction reward, CPU only.

Contract: predict_satisfaction(record) -> {"score": float in [1, 5]}.
The policy decision and refund amount are NOT inputs to change; the contextual bandit
chooses only the response style and an independently checked writer renders it.

A pretrained text-rating model plus Olist delay data provide a fixed baseline.
An OPTIONAL, separately evaluated style-aware Ridge model can estimate differential
rewards. No runtime training or external API calls occur here.
"""
from __future__ import annotations

import pickle
from functools import lru_cache
from pathlib import Path

MODEL_DIR = Path(__file__).resolve().parents[2] / "models" / "agent_f"
TEXT_MODEL = MODEL_DIR / "satisfaction.pkl"
STACKER = MODEL_DIR / "stacker.pkl"  # promoted model ONLY; trainer writes stacker_candidate.pkl
DELAY_TABLE = [(0, 4.22), (2, 3.07), (5, 2.5), (10, 1.57), (10_000, 1.4)]
STYLES = ["short", "apology_first", "apology_next_step"]
EMOTIONS = ["anger", "disgust", "fear", "joy", "neutral", "sadness", "surprise"]


def user_text(record: dict) -> str:
    """Only the customer's messages are input to the real-review classifier."""
    return "\n".join(m.get("text", "") for m in (record.get("messages") or [])
                     if m.get("role") == "user").strip()


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
    with p.open("rb") as f:
        return pickle.load(f)  # Only load trusted local model artifacts.


def text_score(text: str, model=None) -> float:
    model = model if model is not None else _load(str(TEXT_MODEL))
    if model is None:
        raise FileNotFoundError(f"Agent F model missing: {TEXT_MODEL}. Run python -m benchmarks.agent_f.train")
    if not text:
        return 3.0
    probs = model.predict_proba([text])[0]
    return float(sum(p * k for p, k in zip(probs, model.classes_)))


def features(record: dict, model=None) -> list[float]:
    """Fixed schema: text, delay, missing flag, style, emotion, style x emotion.

    The interaction features matter: additive style and emotion terms alone cannot
    express that apology_first may help an angry customer but not a neutral one.
    This function is used *identically* in training and serving.
    """
    sit = record.get("situation") or {}
    d = delay_prior(sit.get("days_late"))
    style = record.get("style")
    emotion = sit.get("emotion") or "neutral"
    if style not in STYLES:
        raise ValueError(f"Unsupported reply style: {style!r}")
    if emotion not in EMOTIONS:
        raise ValueError(f"Unsupported emotion: {emotion!r}")
    style_hot = [float(style == s) for s in STYLES]
    emotion_hot = [float(emotion == e) for e in EMOTIONS]
    interactions = [s * e for s in style_hot for e in emotion_hot]
    return ([text_score(user_text(record), model), d if d is not None else 0.0, float(d is None)]
            + style_hot + emotion_hot + interactions)


def predict_satisfaction(record: dict, model=None, stacker=None) -> dict:
    """Estimate the score, clipped to [1, 5]; `stacker=False` opts out.

    `stacker_candidate.pkl` is NEVER auto-loaded: candidate promotion needs
    human review of independent real support ratings.
    """
    if stacker is None:
        stacker = _load(str(STACKER))
    if stacker is not False and stacker is not None:
        score = float(stacker.predict([features(record, model)])[0])
    else:
        text = text_score(user_text(record), model)
        d = delay_prior((record.get("situation") or {}).get("days_late"))
        score = text if d is None else 0.5 * text + 0.5 * d
    return {"score": round(max(1.0, min(5.0, score)), 3)}
