"""Find WHY the client writes (the contact reasons), by meaning, with sentence embeddings (M3).

Idea: each of the 7 reasons has ~10 example messages (data/reason_examples.json, written by the Brain;
T14a: cancel_order's 10 examples are real tweets).
The embedding model turns every text into a vector; two texts with a similar MEANING get vectors that
point in a similar direction (high cosine similarity), even when they share no words:
"my parcel never came" is close to "I'm still waiting for an order that was due last week".

match_reasons(text):
  1. split the message into sentences (one message can contain several problems = several sub-cases);
  2. score each sentence against each reason = mean of its top-3 cosine similarities to that reason's
     examples (top-3 instead of the single best, so one lucky example is not enough);
  3. each sentence keeps its BEST reason, if that score passes the threshold (chosen by leave-one-out
     on the EXAMPLES). Several sentences can give several reasons (sub-cases);
  4. nothing passes -> needs_llm = True (intake.py then asks M2).

Why only the best reason per sentence (step 3)? With this model all scores are fairly high (0.6-0.85),
so one sentence often passes the threshold for 2-3 reasons at once. In leave-one-out on the examples,
"keep every reason above the threshold" gave at best 21/60 exact matches; "best reason per sentence"
gave 47/60 (see tasks/T03_report.md).

The example vectors are computed once and cached in data/reason_vectors.npz (git-ignored).
The cache is rebuilt automatically when the examples file or the model changes.

T21: every company has its own reasons, examples, threshold and cache (config.yaml companies:). Same model, same
method. The default is ShopNova, so old callers keep working.
"""

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

import numpy as np

from callverse import companies
from callverse.config import load_config

DATA_DIR = Path(__file__).resolve().parent / "data"

# T14a: "cancel" and "refund" are both about money coming back, so by meaning alone the matcher mostly says refund.
# A sentence that says it wants to cancel is a cancellation (a rule, not tuning: threshold and top-k are the same).
# Not "cancelled": "I cancelled it, where is my money?" is about what already happened. "cancle": a typo in real tweets.
CANCEL_WORD_RE = re.compile(r"\b(?:cancel|cancle|cancell?ing)\b", re.IGNORECASE)
# Cancelling a subscription or an account is not cancelling an order: the rule stays out of those sentences.
NOT_AN_ORDER_RE = re.compile(r"\b(?:subscriptions?|memberships?|prime|accounts?|plans?)\b", re.IGNORECASE)

REASONS = ["order_status", "late_delivery", "refund_request", "cancel_order", "return_item", "damaged_item", "other"]


@lru_cache(maxsize=1)
def get_model():
    """Load the embedding model once (M3, local CPU). Imported here so other modules load fast."""
    from sentence_transformers import SentenceTransformer
    cfg = load_config()["intake"]
    # embedding_revision pins the exact Hugging Face files tested in T23 (optional: None = latest)
    return SentenceTransformer(cfg["embedding_model"], device="cpu", revision=cfg.get("embedding_revision"))


def embed(texts: list[str]) -> np.ndarray:
    """One vector per text. normalize_embeddings=True -> length 1, so cosine similarity = dot product."""
    return get_model().encode(texts, normalize_embeddings=True, convert_to_numpy=True)


def load_examples(company: str = companies.DEFAULT) -> dict[str, list[str]]:
    """{reason: [example texts]} from the company's examples file (keys starting with "_" are notes, skipped)."""
    data = json.loads(companies.path(company, "reason_examples").read_text(encoding="utf-8"))
    return {reason: data[reason] for reason in companies.get(company)["reasons"]}


@lru_cache(maxsize=4)
def example_vectors(company: str = companies.DEFAULT) -> dict[str, np.ndarray]:
    """{reason: matrix of example vectors}, read from the company's cache when it is still valid."""
    model_name = load_config()["intake"]["embedding_model"]
    examples_path, cache_path = companies.path(company, "reason_examples"), companies.path(company, "reason_cache")
    # Fingerprint of the examples file + model name: if either changes, the cache is outdated.
    fingerprint = hashlib.sha256(examples_path.read_bytes() + model_name.encode()).hexdigest()

    if cache_path.exists():
        cache = np.load(cache_path)
        if str(cache["fingerprint"]) == fingerprint:
            return {reason: cache[reason] for reason in companies.get(company)["reasons"]}

    examples = load_examples(company)
    vectors = {reason: embed(texts) for reason, texts in examples.items()}
    np.savez(cache_path, fingerprint=np.array(fingerprint), **vectors)
    return vectors


def split_sentences(text: str) -> list[str]:
    """Split on . ! ? (followed by a space) and on line breaks. Very short pieces ("Hi!") are kept
    but they rarely pass the threshold, because they carry no reason."""
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def reason_scores(vector: np.ndarray, vectors: dict[str, np.ndarray], top_k: int) -> dict[str, float]:
    """Score of ONE sentence vector against each reason: mean of the top_k cosine similarities."""
    scores = {}
    for reason, matrix in vectors.items():
        similarities = matrix @ vector                      # cosine similarity with every example
        best = np.sort(similarities)[-top_k:]               # the top_k highest
        scores[reason] = float(best.mean())
    return scores


def match_reasons(text: str, threshold: float | None = None, company: str = companies.DEFAULT) -> dict:
    """Find the reasons in a message, among the reasons of this company.

    Returns {"reasons": [{reason, score, sentence}, ...] best first, "needs_llm": bool,
             "sentence_scores": [...] (every sentence's scores, for the trace)}.
    Each sentence gives at most one reason: its best one, if it passes the threshold.
    A reason found in several sentences is listed once, with its best sentence.
    "other" is dropped when a specific reason is also found ("other" means "none of the above").
    """
    cfg = load_config()["intake"]
    threshold = companies.get(company)["reason_threshold"] if threshold is None else threshold
    vectors = example_vectors(company)

    sentences = split_sentences(text)
    sentence_vectors = embed(sentences) if sentences else []

    best_per_reason = {}
    sentence_scores = []
    for sentence, vector in zip(sentences, sentence_vectors):
        scores = reason_scores(vector, vectors, cfg["top_k"])
        sentence_scores.append({"sentence": sentence, "scores": {r: round(s, 3) for r, s in scores.items()}})
        reason = max(scores, key=scores.get)               # this sentence's best reason
        if ("cancel_order" in scores and CANCEL_WORD_RE.search(sentence)   # ShopNova only (T14a, see above)
                and not NOT_AN_ORDER_RE.search(sentence)):
            reason = "cancel_order"
        score = scores[reason]
        if score >= threshold and score > best_per_reason.get(reason, {}).get("score", -1):
            best_per_reason[reason] = {"reason": reason, "score": round(score, 3), "sentence": sentence}

    if len(best_per_reason) > 1:
        best_per_reason.pop("other", None)

    found = sorted(best_per_reason.values(), key=lambda r: r["score"], reverse=True)
    return {"reasons": found, "needs_llm": not found, "sentence_scores": sentence_scores}


def leave_one_out(thresholds: list[float], company: str = companies.DEFAULT) -> list[dict]:
    """Choose the threshold on the EXAMPLES only (the test set is never used here).

    For each example: hide it, score it against the remaining examples (its own vector removed),
    keep its best reason if it passes the threshold (same rule as match_reasons), and compare with
    its true reason. Returns one row of counts per threshold:
    exact (right reason), wrong (wrong reason), needs_llm (no reason passed -> M2 call).
    """
    top_k = load_config()["intake"]["top_k"]
    vectors = example_vectors(company)

    # Scores of every example against every reason, with the example itself left out.
    rows = []
    for true_reason in companies.get(company)["reasons"]:
        for i in range(len(vectors[true_reason])):
            vector = vectors[true_reason][i]
            others = {r: (np.delete(m, i, axis=0) if r == true_reason else m) for r, m in vectors.items()}
            rows.append((true_reason, reason_scores(vector, others, top_k)))

    results = []
    for t in thresholds:
        exact = wrong = no_reason = 0
        for true_reason, scores in rows:
            best = max(scores, key=scores.get)
            if scores[best] < t:
                no_reason += 1        # would go to the LLM fallback
            elif best == true_reason:
                exact += 1
            else:
                wrong += 1            # wrong reason -> wrong agent
        results.append({"threshold": round(t, 3), "exact": exact, "wrong": wrong,
                        "needs_llm": no_reason, "total": len(rows)})
    return results
