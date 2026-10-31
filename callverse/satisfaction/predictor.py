"""Agent F - predict a customer's satisfaction (1-5) from a finished conversation.

PROVISIONAL INTERFACE: RL_interface_spec.md was not in the repo when this was written.
Assumed record shape (any of these works):
  {"text": "..."}                                    -> the text is scored as is
  {"messages": [{"role": "customer", "text": "..."}, {"role": "agent", "content": "..."}]}
Only CUSTOMER turns are scored (roles "customer", "client", "user"); if none, all turns are used.
Output: an int 1..5, always.

Model: TF-IDF (word 1-2 grams + char 2-5 grams) + logistic regression, trained on REAL star ratings
(benchmarks/agent_f/train.py). Chosen by benchmarks/agent_f/benchmark.py. CPU only, ~1 ms per record.
The model file lives in models/agent_f/ (git-ignored); rebuild it with the train script.
"""
from __future__ import annotations

import pickle
from functools import lru_cache
from pathlib import Path

MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "agent_f" / "satisfaction.pkl"
CUSTOMER_ROLES = {"customer", "client", "user"}


def record_text(record) -> str:
    """Turn a record (str or dict) into the text the model reads."""
    if isinstance(record, str):
        return record
    if record.get("text"):
        return str(record["text"])
    msgs = record.get("messages") or record.get("turns") or []
    turns = [(m.get("role", ""), m.get("text") or m.get("content") or "") for m in msgs]
    mine = [t for r, t in turns if r.lower() in CUSTOMER_ROLES]
    return "\n".join(mine or [t for _, t in turns])


@lru_cache(maxsize=4)
def load_model(path: str = str(MODEL_PATH)):
    if not Path(path).exists():
        raise FileNotFoundError(f"Agent F model missing: {path}. Run: python benchmarks/agent_f/train.py")
    with open(path, "rb") as f:
        return pickle.load(f)


def predict_satisfaction(record, model=None) -> int:
    """Return the predicted satisfaction score, an int from 1 to 5."""
    model = model or load_model()
    text = record_text(record).strip()
    if not text:
        return 3  # nothing to read: neutral middle score
    score = int(round(float(model.predict([text])[0])))
    return min(5, max(1, score))
