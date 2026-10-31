"""Agent F benchmark: pick the model on the REAL validation split (never on test).

Run: python -m benchmarks.agent_f.benchmark   -> benchmarks/agent_f/results/benchmark.json
Data: SetFit/amazon_reviews_multi_en (real customer reviews, real 1-5 stars, balanced classes).
"""
from __future__ import annotations

import json
import time
from collections import Counter

import numpy as np

from benchmarks.agent_f.common import ROOT, TRAIN_N, candidates, load


def metrics(y, p):
    """MAE + Spearman on the raw (float) prediction; accuracy / within-1 on the rounded one."""
    from scipy.stats import spearmanr
    y, raw = np.array(y), np.clip(np.asarray(p, dtype=float), 1, 5)
    rho = spearmanr(y, raw).statistic if len(set(raw)) > 1 else 0.0
    p = np.rint(raw).astype(int)
    return {"mae_raw": round(float(np.abs(y - raw).mean()), 4), "spearman": round(float(rho), 4),
            "mae": round(float(np.abs(y - p).mean()), 4), "accuracy": round(float((y == p).mean()), 4),
            "within_1": round(float((np.abs(y - p) <= 1).mean()), 4)}


def latency(model, texts, n=300):
    times = []
    for t in texts[:n]:
        s = time.perf_counter(); model.predict([t]); times.append((time.perf_counter() - s) * 1000)
    return {"ms_mean": round(float(np.mean(times)), 3), "ms_p95": round(float(np.percentile(times, 95)), 3)}


def main():
    xtr, ytr = load("train", TRAIN_N)
    xva, yva = load("validation")
    out = {"data": "SetFit/amazon_reviews_multi_en", "train_n": len(xtr), "val_n": len(xva), "models": {}}
    mean, mode = float(np.mean(ytr)), Counter(ytr).most_common(1)[0][0]
    out["models"]["baseline_mean"] = metrics(yva, [mean] * len(yva))
    out["models"]["baseline_majority"] = metrics(yva, [mode] * len(yva))
    for name, m in candidates().items():
        s = time.perf_counter(); m.fit(xtr, ytr); fit_s = time.perf_counter() - s
        out["models"][name] = {**metrics(yva, m.predict(xva)), **latency(m, xva), "fit_s": round(fit_s, 1)}
        print(name, out["models"][name], flush=True)
    try:  # MiniLM embeddings + logistic regression (optional: needs the model download)
        from sentence_transformers import SentenceTransformer
        from sklearn.linear_model import LogisticRegression
        enc = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device="cpu")
        k = 20000  # encoding is slow on CPU: smaller train set
        s = time.perf_counter()
        clf = LogisticRegression(C=2.0, max_iter=2000).fit(enc.encode(xtr[:k], batch_size=64), ytr[:k])
        fit_s = time.perf_counter() - s
        times = []
        for t in xva[:300]:
            s = time.perf_counter(); clf.predict(enc.encode([t])); times.append((time.perf_counter() - s) * 1000)
        out["models"]["minilm_logreg"] = {**metrics(yva, clf.predict(enc.encode(xva, batch_size=64))),
                                          "ms_mean": round(float(np.mean(times)), 3),
                                          "ms_p95": round(float(np.percentile(times, 95)), 3),
                                          "fit_s": round(fit_s, 1), "train_n": k}
        print("minilm_logreg", out["models"]["minilm_logreg"], flush=True)
    except Exception as e:  # noqa: BLE001
        out["models"]["minilm_logreg"] = {"skipped": repr(e)[:200]}
    real = {k: v for k, v in out["models"].items() if "mae" in v and not k.startswith("baseline")}
    out["chosen"] = min(real, key=lambda k: (real[k]["mae"], -real[k]["accuracy"]))
    (ROOT / "benchmarks/agent_f/results").mkdir(parents=True, exist_ok=True)
    (ROOT / "benchmarks/agent_f/results/benchmark.json").write_text(json.dumps(out, indent=2))
    print("chosen:", out["chosen"])


if __name__ == "__main__":
    main()
