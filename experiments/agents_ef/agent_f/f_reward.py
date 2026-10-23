"""Agent F's predicted satisfaction as a REWARD signal for Agent E (experiment E+F).

Agent F's text model needs the conversation, which the simulator does not generate. What E can be rewarded with
is F's satisfaction prediction from the ticket OUTCOME. This file fits that outcome model on GENUINE ratings:
  Olist public data: review_score (1-5) vs lateness relative to the promise
      x = (delivered - estimated) / (estimated - purchase)        (< 0 early, > 0 late)
  monotone (isotonic, decreasing) regression, orders split TRAIN / VAL by a hash of order_id.
In the simulator the same relative lateness is x = wait / ticket_SLA - 1. An abandoned ticket = 1.

Known blind spot (on purpose, it is the point of the experiment): this F does NOT see fallback quality or
priority, so an RL agent rewarded with it may overuse the cheap fallback -> we measure that with the ground-truth
SIM-CSAT (which does penalise fallback) and the fallback share, with and without the 25 % fallback cap.

    python -m agent_f.f_reward --raw <olist raw folder> --out results/f_reward/olist_isotonic.json
"""

import argparse
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

import numpy as np

F = "%Y-%m-%d %H:%M:%S"


def fit(raw: Path, out: Path):
    from sklearn.isotonic import IsotonicRegression
    rev = {}
    for r in csv.DictReader(open(raw / "olist_order_reviews_dataset.csv", encoding="utf-8")):
        rev.setdefault(r["order_id"], []).append(int(r["review_score"]))
    xs, ys, split = [], [], []
    for o in csv.DictReader(open(raw / "olist_orders_dataset.csv", encoding="utf-8")):
        d, e, p = o["order_delivered_customer_date"], o["order_estimated_delivery_date"], o["order_purchase_timestamp"]
        if not (d and e and p) or o["order_id"] not in rev:
            continue
        d, e, p = (datetime.strptime(v, F) for v in (d, e, p))
        promised = max((e - p).total_seconds(), 86400)
        xs.append((d - e).total_seconds() / promised)
        ys.append(float(np.mean(rev[o["order_id"]])))
        split.append(int(hashlib.sha1(o["order_id"].encode()).hexdigest(), 16) % 5 == 0)      # 20 % VAL
    xs, ys, split = np.clip(np.array(xs), -1.0, 3.0), np.array(ys), np.array(split)
    iso = IsotonicRegression(increasing=False, y_min=1, y_max=5, out_of_bounds="clip").fit(xs[~split], ys[~split])
    grid = np.linspace(-1, 3, 81)
    pred_va = iso.predict(xs[split])
    res = {"source": "Olist public dataset: review_score vs relative lateness (genuine ratings)",
           "x_grid": grid.round(4).tolist(), "y_grid": iso.predict(grid).round(4).tolist(),
           "n_train": int((~split).sum()), "n_val": int(split.sum()),
           "val_mae": float(np.abs(pred_va - ys[split]).mean()),
           "val_mae_constant_mean": float(np.abs(ys[~split].mean() - ys[split]).mean()),
           "val_spearman": float(__import__("scipy.stats").stats.spearmanr(pred_va, ys[split]).correlation)}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2))
    return res


def load_f_reward(path):
    """-> callable(queue, wait_over_sla, fallback, rank, emotion) -> predicted satisfaction 1..5 per ticket."""
    d = json.loads(Path(path).read_text())
    gx, gy = np.array(d["x_grid"]), np.array(d["y_grid"])

    def f(q, wait_ratio, fb, rank, emo):
        return np.interp(np.clip(np.asarray(wait_ratio) - 1.0, -1.0, 3.0), gx, gy)
    return f


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", default="results/f_reward/olist_isotonic.json")
    a = ap.parse_args()
    print(json.dumps({k: v for k, v in fit(Path(a.raw), Path(a.out)).items() if "grid" not in k}, indent=1))
