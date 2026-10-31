"""Final evaluation of Agent F on the team's REAL rated conversations (~100). Never used for training/tuning.

Input: a JSONL file, one record per line, each with "rating" (1-5) plus "text" or "messages"
(same record shape as callverse.satisfaction.predict_satisfaction).
Run: python -m benchmarks.agent_f.evaluate_rated path/to/rated.jsonl
Prints MAE, accuracy, within-1, latency mean/p95, baselines (mean / majority of the TRAIN labels = 3,
since training is balanced) and the 10 worst errors for error analysis.
"""
from __future__ import annotations

import json
import sys
import time

import numpy as np

from callverse.satisfaction import predict_satisfaction, record_text
from benchmarks.agent_f.benchmark import metrics


def evaluate(records):
    y, p, ms = [], [], []
    for r in records:
        s = time.perf_counter(); p.append(predict_satisfaction(r)); ms.append((time.perf_counter() - s) * 1000)
        y.append(int(r["rating"]))
    errs = sorted(zip(y, p, records), key=lambda t: -abs(t[0] - t[1]))[:10]
    return {"n": len(y), "agent_f": metrics(y, p), "baseline_constant_3": metrics(y, [3] * len(y)),
            "ms_mean": round(float(np.mean(ms)), 3), "ms_p95": round(float(np.percentile(ms, 95)), 3),
            "confusion_true_pred": {f"{a}->{b}": int(sum(1 for i, j in zip(y, p) if (i, j) == (a, b)))
                                    for a in range(1, 6) for b in range(1, 6)},
            "worst": [{"true": a, "pred": b, "text": record_text(r)[:200]} for a, b, r in errs]}


if __name__ == "__main__":
    recs = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
    print(json.dumps(evaluate(recs), indent=2))
