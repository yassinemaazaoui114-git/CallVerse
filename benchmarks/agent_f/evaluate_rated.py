"""RL3 check: Agent F on the team's REAL rated conversations (Notion 31, ~100). Test only: never train or tune on it.

Input: JSONL, one conversation record per line (RL_interface_spec "Conversation record") plus "rating" (1-5).
Run: python -m benchmarks.agent_f.evaluate_rated path/to/rated.jsonl [--out results/real_eval.json]
Reports MAE + Spearman (spec), accuracy, latency mean/p95, the two spec baselines
("predict the average" = 3.0 since the training stars are balanced; "delay-only rule" = real Olist delay table),
and the 10 worst errors.
"""
from __future__ import annotations

import json
import sys
import time

import numpy as np

from benchmarks.agent_f.benchmark import metrics
from callverse.quality.satisfaction import delay_prior, predict_satisfaction, user_text


def evaluate(records, predict=predict_satisfaction):
    y, p, ms = [], [], []
    for r in records:
        s = time.perf_counter(); p.append(predict(r)["score"]); ms.append((time.perf_counter() - s) * 1000)
        y.append(int(r["rating"]))
    delay = [delay_prior((r.get("situation") or {}).get("days_late")) or 3.0 for r in records]
    worst = sorted(zip(y, p, records), key=lambda t: -abs(t[0] - t[1]))[:10]
    return {"n": len(y), "agent_f": metrics(y, p),
            "baseline_average": metrics(y, [3.0] * len(y)), "baseline_delay_only": metrics(y, delay),
            "ms_mean": round(float(np.mean(ms)), 3), "ms_p95": round(float(np.percentile(ms, 95)), 3),
            "worst": [{"ticket_id": r.get("ticket_id"), "true": a, "pred": b, "style": r.get("style"),
                       "user_text": user_text(r)[:200]} for a, b, r in worst]}


if __name__ == "__main__":
    recs = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
    out = json.dumps(evaluate(recs), indent=2)
    if "--out" in sys.argv:
        open(sys.argv[sys.argv.index("--out") + 1], "w").write(out)
    print(out)
