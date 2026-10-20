"""Emotion and sentiment of the client message, with two ready-made local classifiers (M4, CPU).

- Emotion model: one of 7 emotions (anger, disgust, fear, joy, neutral, sadness, surprise).
  Useful later for the reply's tone (the SLM) and for the trace.
- Sentiment model: negative / neutral / positive. Its "negative" probability is the
  emotion_intensity used in the priority (priority.py).

Why ready-made models? They are trained for exactly this, run locally for free, and are small enough
for a CPU. We do not fine-tune them (out of scope).
"""

from functools import lru_cache

from callverse.config import load_config


@lru_cache(maxsize=2)
def _classifier(model_name: str):
    """Load a text classifier once. top_k=None -> scores for ALL labels, not only the best one."""
    from transformers import pipeline
    return pipeline("text-classification", model=model_name, device="cpu", top_k=None)


def load_models() -> None:
    """Load both models now (so the first message is not slow). Optional."""
    cfg = load_config()["intake"]
    _classifier(cfg["emotion_model"])
    _classifier(cfg["sentiment_model"])


def _all_scores(model_name: str, text: str) -> dict[str, float]:
    """{label: probability} for one text. truncation=True: very long messages are cut to the model's limit."""
    result = _classifier(model_name)(text, truncation=True)
    # Depending on the transformers version, one text gives [[{...}, ...]] or [{...}, ...].
    if result and isinstance(result[0], list):
        result = result[0]
    return {item["label"].lower(): float(item["score"]) for item in result}


def analyze(text: str) -> dict:
    """Return {"emotion": {label, score}, "sentiment": {label, score}, "negative_score": float}."""
    cfg = load_config()["intake"]
    emotions = _all_scores(cfg["emotion_model"], text)
    sentiments = _all_scores(cfg["sentiment_model"], text)

    emotion = max(emotions, key=emotions.get)
    sentiment = max(sentiments, key=sentiments.get)
    return {
        "emotion": {"label": emotion, "score": round(emotions[emotion], 3)},
        "sentiment": {"label": sentiment, "score": round(sentiments[sentiment], 3)},
        "negative_score": round(sentiments.get("negative", 0.0), 3),
    }
