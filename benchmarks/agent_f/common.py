"""Shared helpers for the Agent F benchmark: real data loading + candidate models."""
from __future__ import annotations

import json
from pathlib import Path

from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline, make_union
from sklearn.feature_extraction.text import TfidfVectorizer

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "raw" / "amazon_reviews_multi_en"   # git-ignored, real 1-5 star reviews
URL = "https://huggingface.co/datasets/SetFit/amazon_reviews_multi_en/resolve/main/{}.jsonl"
TRAIN_N = 60000   # subsample of the 200k train split (fixed seed) - enough, keeps CPU training < 2 min


def load(split: str, n: int | None = None, seed: int = 0):
    """Return (texts, scores 1-5). Downloads the split once into data/raw/."""
    import random
    import urllib.request
    path = DATA / f"{split}.jsonl"
    if not path.exists():
        DATA.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(URL.format(split), path)
    rows = [json.loads(l) for l in path.open(encoding="utf-8")]
    if n and n < len(rows):
        rows = random.Random(seed).sample(rows, n)
    return [r["text"] for r in rows], [int(r["label"]) + 1 for r in rows]


def tfidf():
    return make_union(TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=200000, sublinear_tf=True),
                      TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=3, max_features=200000,
                                      sublinear_tf=True))


def candidates():
    return {
        "tfidf_ridge": make_pipeline(tfidf(), Ridge(alpha=1.0)),
        "tfidf_logreg": make_pipeline(tfidf(), LogisticRegression(C=2.0, max_iter=2000)),
    }
