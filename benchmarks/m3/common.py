"""Shared pieces of the M3 benchmark (T23): the candidates, the data, the Intake matcher, BM25 and the measures.

Everything here is pure Python / numpy (no model is loaded here), so it can be tested offline.
The matcher is a copy of the system's rule (callverse/intake/reasons.py), written on vectors that are already
computed, so many thresholds and top-k values can be tried without embedding the texts again.
tests/test_m3_benchmark.py checks that it gives the same answer as reasons.py.
"""

import json
import math
import re
from collections import Counter
from pathlib import Path

import numpy as np

from callverse import companies
from callverse.intake.reasons import split_sentences      # the system's own sentence splitter (read only)
from callverse.kb.policies import load_policies
from callverse.kb.search import policy_text                # the system's "title. text" (read only)

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "benchmarks" / "m3" / "data"
RESULTS = ROOT / "benchmarks" / "m3" / "results"
WORK = ROOT / "out" / "t23"                                 # embeddings and other big files (git-ignored)

COMPANIES = ["shopnova", "atlas"]

# The candidates (item 2). revision = the Hugging Face commit, so every run uses the exact same files.
# Prompts are each model's DOCUMENTED ones for search (query -> passage). Intake compares a message with example
# messages (the same kind of text on both sides), so Intake uses no prompt for every model, like the system.
MODELS = {
    "bge-small": {
        "name": "BAAI/bge-small-en-v1.5", "revision": "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",
        "licence": "MIT", "today": True,
        "query_prompt": "Represent this sentence for searching relevant passages: ", "doc_prompt": "",
        "prompt_source": "BGE model card: instruction for short queries in retrieval; passages without one",
    },
    "minilm": {
        "name": "sentence-transformers/all-MiniLM-L6-v2", "revision": "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
        "licence": "Apache-2.0",
        "query_prompt": "", "doc_prompt": "",
        "prompt_source": "no prompts documented (symmetric model)",
    },
    "bge-base": {
        "name": "BAAI/bge-base-en-v1.5", "revision": "a5beb1e3e68b9ab74eb54cfd186867f64f240e1a",
        "licence": "MIT",
        "query_prompt": "Represent this sentence for searching relevant passages: ", "doc_prompt": "",
        "prompt_source": "BGE model card: instruction for short queries in retrieval; passages without one",
    },
    "embeddinggemma": {
        "name": "google/embeddinggemma-300m", "revision": "57c266a740f537b4dc058e1b0cda161fd15afa75",
        "licence": "Gemma terms of use (gated: Hugging Face login + accepting the licence)",
        "query_prompt": "task: search result | query: ", "doc_prompt": "title: none | text: ",
        "prompt_source": "EmbeddingGemma model card (Retrieval query / document prompts)",
    },
    "qwen3-0.6b": {
        "name": "Qwen/Qwen3-Embedding-0.6B", "revision": "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3",
        "licence": "Apache-2.0",
        "query_prompt": "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:",
        "doc_prompt": "",
        "prompt_source": "Qwen3-Embedding model card: instruction on queries only, documents without one",
    },
}
RERANKER = {"name": "BAAI/bge-reranker-base", "revision": "2cfc18c9415c912f9d8155881c133215df768a70",
            "licence": "MIT"}

# Today's system settings (config.yaml), reported as they are.
TODAY = {"model": "bge-small", "top_k": 3, "thresholds": {"shopnova": 0.66, "atlas": 0.68}}

# Money reasons (item 8): mixing one of these with a non-money reason is a "critical error".
MONEY = {"shopnova": {"refund_request", "return_item", "damaged_item"},
         "atlas": {"refund_request", "compensation_request", "cancellation"}}

THRESHOLDS = [round(0.40 + i / 100, 2) for i in range(51)]      # 0.40 .. 0.90, step 0.01
TOP_KS = [1, 3, 5]
NEEDS_LLM = "needs_llm"          # the prediction when no reason passes the threshold (0 API calls here)


# ---------------------------------------------------------------- data

def load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def intake_val(company: str) -> list[dict]:
    """[{id, text, reason}] of a company's VALIDATION set."""
    name = {"shopnova": "shopnova_intake_val.json", "atlas": "atlas_intake_val.json"}[company]
    return load_json(DATA / name)["messages"]


def reason_examples(company: str) -> dict[str, list[str]]:
    """The examples the system's Intake compares with (the index), per reason, in the company's reason order."""
    data = load_json(companies.path(company, "reason_examples"))
    return {reason: data[reason] for reason in companies.get(company)["reasons"]}


def rules(company: str) -> list[dict]:
    return load_policies(companies.path(company, "rules_file"))


def rule_texts(company: str) -> list[str]:
    return [policy_text(r) for r in rules(company)]


def rag_val() -> list[dict]:
    return load_json(DATA / "rag_val.json")["questions"]


# ---------------------------------------------------------------- Intake matcher (copy of reasons.py's rule)

def sentence_scores(sentence_vectors: np.ndarray, example_vectors: dict[str, np.ndarray], top_k: int) -> np.ndarray:
    """Matrix [sentence x reason]: mean of the top_k similarities of the sentence to that reason's examples."""
    columns = []
    for matrix in example_vectors.values():
        similarities = sentence_vectors @ matrix.T                 # [sentence x example]
        k = min(top_k, matrix.shape[0])
        columns.append(np.sort(similarities, axis=1)[:, -k:].mean(axis=1))
    return np.stack(columns, axis=1)


def found_reasons(scores: np.ndarray, reasons: list[str], threshold: float) -> list[str]:
    """reasons.py's rule: each sentence keeps its best reason if it passes the threshold; "other" is dropped
    when a specific reason is also found. Returns the found reasons, best score first."""
    best = {}
    for row in scores:
        i = int(np.argmax(row))
        if row[i] >= threshold and row[i] > best.get(reasons[i], -1):
            best[reasons[i]] = float(row[i])
    if len(best) > 1:
        best.pop("other", None)
    return sorted(best, key=best.get, reverse=True)


def main_reason(found: list[str], order: list[str]) -> str:
    """intake.py's pick_main_reason: the first reason of the company's precedence order; nothing -> needs_llm."""
    if not found:
        return NEEDS_LLM
    return next((r for r in order if r in found), found[0])


# ---------------------------------------------------------------- measures

def intake_measures(true: list[str], pred: list[str], reasons: list[str], money: set[str]) -> dict:
    """Accuracy, macro-F1 over the company's reasons, per-reason precision / recall, critical errors, needs-LLM.

    A needs_llm prediction is a miss (it lowers the recall of the true reason, it is no reason's prediction).
    Critical error = a money reason predicted as a non-money reason, or the other way round (needs_llm is not one:
    the LLM would still look at it)."""
    n = len(true)
    per_reason, f1s = {}, []
    for r in reasons:
        tp = sum(t == r and p == r for t, p in zip(true, pred))
        n_pred, n_true = sum(p == r for p in pred), sum(t == r for t in true)
        precision = tp / n_pred if n_pred else 0.0
        recall = tp / n_true if n_true else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        if n_true:                                  # a reason absent from the set is not averaged
            f1s.append(f1)
        per_reason[r] = {"precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3),
                         "support": n_true}
    critical = sum(p != NEEDS_LLM and ((t in money) != (p in money)) for t, p in zip(true, pred))
    return {"n": n, "accuracy": round(sum(t == p for t, p in zip(true, pred)) / n, 4),
            "macro_f1": round(sum(f1s) / len(f1s), 4), "critical_errors": critical,
            "needs_llm_rate": round(sum(p == NEEDS_LLM for p in pred) / n, 4), "per_reason": per_reason}


def rank_measures(rankings: list[list[str]], expected: list[list[str]]) -> dict:
    """Top-1, top-2 (agents get 2 rules) and MRR over questions that have an expected rule."""
    top1 = top2 = rr = 0.0
    for ranking, exp in zip(rankings, expected):
        top1 += ranking[0] in exp
        top2 += any(r in exp for r in ranking[:2])
        rank = next((i + 1 for i, r in enumerate(ranking) if r in exp), None)
        rr += 1 / rank if rank else 0.0
    n = len(rankings)
    return {"n": n, "top1": round(top1 / n, 4), "top2": round(top2 / n, 4), "mrr": round(rr / n, 4),
            "top1_count": int(top1), "top2_count": int(top2)}


def percentile_ms(seconds: list[float], q: float) -> float:
    return round(float(np.percentile(np.array(seconds) * 1000, q)), 2)


# ---------------------------------------------------------------- baselines (no model)

TOKEN = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


class BM25:
    """Okapi BM25 (k1 = 1.5, b = 0.75), the classic keyword search, written out so no library is added."""

    def __init__(self, documents: list[str], k1: float = 1.5, b: float = 0.75):
        self.docs = [Counter(tokens(d)) for d in documents]
        self.lengths = np.array([sum(d.values()) for d in self.docs], dtype=float)
        self.avg = self.lengths.mean()
        n = len(documents)
        df = Counter(t for d in self.docs for t in d)
        self.idf = {t: math.log((n - c + 0.5) / (c + 0.5) + 1) for t, c in df.items()}
        self.k1, self.b = k1, b

    def scores(self, query: str) -> np.ndarray:
        out = np.zeros(len(self.docs))
        for t in tokens(query):
            if t not in self.idf:
                continue
            tf = np.array([d[t] for d in self.docs], dtype=float)
            out += self.idf[t] * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * self.lengths / self.avg))
        return out


class TfIdf:
    """TF-IDF vectors (log tf, smooth idf, length 1), fitted on the index texts only (the examples)."""

    def __init__(self, documents: list[str]):
        df = Counter(t for d in documents for t in set(tokens(d)))
        self.vocab = {t: i for i, t in enumerate(sorted(df))}
        n = len(documents)
        self.idf = np.array([math.log((1 + n) / (1 + df[t])) + 1 for t in sorted(df)])

    def vectors(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), len(self.vocab)))
        for row, text in enumerate(texts):
            for t, c in Counter(tokens(text)).items():
                if t in self.vocab:
                    out[row, self.vocab[t]] = (1 + math.log(c)) * self.idf[self.vocab[t]]
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(norms == 0, 1, norms)


def rrf(rankings: list[list[int]], k: int = 60) -> list[int]:
    """Reciprocal rank fusion: score = sum of 1 / (k + rank) over the rankings (rank starts at 1). Best first."""
    score = Counter()
    for ranking in rankings:
        for rank, doc in enumerate(ranking, start=1):
            score[doc] += 1 / (k + rank)
    return sorted(score, key=lambda d: (-score[d], rankings[0].index(d)))
