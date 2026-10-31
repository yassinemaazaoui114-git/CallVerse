"""Compare response-aware satisfaction models on the SIMULATED persona splits (train fit, val select, eval once).

Run: python -m benchmarks.agent_f.compare_satisfaction -> results/satisfaction_models.json, models/agent_f/stacker_selected.pkl
Candidates (all CPU, same 44 features from quality.satisfaction.features): Ridge (alphas), HistGradientBoosting,
ExtraTrees, RandomForest, and "ridge_cross" = Ridge on features + pairwise products of the style/outcome block.
Metrics: MAE, Spearman, pairwise style-preference accuracy (same persona + scenario, two styles: is the better
rated one predicted higher), calibration (mean |bin mean pred - bin mean true| over 5 bins), latency.
"""
from __future__ import annotations

import json
import pickle
import time
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer

from callverse.quality.satisfaction import MODEL_DIR, TEXT_MODEL, features, predict_satisfaction

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/simulated/agent_f"
OUT = ROOT / "benchmarks/agent_f/results"


def read(name):
    return [json.loads(l) for l in (DATA / f"{name}.jsonl").open(encoding="utf-8") if l.strip()]


def cross_block(X):
    """Pairwise products of the style one-hot (cols 3..5) with the reply/outcome block (last 10 cols)."""
    X = np.asarray(X)
    style, tail = X[:, 3:6], X[:, -10:]
    return np.hstack([X] + [style[:, [i]] * tail for i in range(3)])


def candidates():
    c = {f"ridge_a{a}": Ridge(alpha=a) for a in (0.1, 1.0, 10.0)}
    c["ridge_cross_a1"] = make_pipeline(FunctionTransformer(cross_block), Ridge(alpha=1.0))
    c["hist_gbm"] = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_depth=4, random_state=0)
    c["extra_trees"] = ExtraTreesRegressor(n_estimators=300, min_samples_leaf=5, random_state=0, n_jobs=-1)
    c["random_forest"] = RandomForestRegressor(n_estimators=300, min_samples_leaf=5, random_state=0, n_jobs=-1)
    return c


def metrics(rows, y, p):
    y, p = np.asarray(y, float), np.clip(np.asarray(p, float), 1, 5)
    rho = spearmanr(y, p).statistic if len(set(p)) > 1 else 0.0
    groups = defaultdict(list)
    for i, r in enumerate(rows):
        groups[(r["persona_id"], r["scenario_id"])].append(i)
    agree = total = 0
    for idx in groups.values():
        for i, j in combinations(idx, 2):
            if y[i] != y[j]:
                total += 1; agree += (p[i] - p[j]) * (y[i] - y[j]) > 0
    bins = np.digitize(p, [1.8, 2.6, 3.4, 4.2])
    calib = float(np.mean([abs(p[bins == b].mean() - y[bins == b].mean()) for b in set(bins)]))
    return {"mae": round(float(np.mean(np.abs(y - p))), 4), "spearman": round(float(rho), 4),
            "pairwise_pref_acc": round(agree / max(1, total), 4), "pairs": total, "calibration_err": round(calib, 4)}


def by_slice(rows, y, p, key):
    out = {}
    for v in sorted({key(r) for r in rows}):
        idx = [i for i, r in enumerate(rows) if key(r) == v]
        out[v] = metrics([rows[i] for i in idx], [y[i] for i in idx], [p[i] for i in idx])
    return out


def main():
    base = pickle.loads(TEXT_MODEL.read_bytes())
    sets = {k: read(k) for k in ("train", "val", "eval")}
    X = {k: np.asarray([features(r, base) for r in v]) for k, v in sets.items()}
    Y = {k: [float(r["rating"]) for r in v] for k, v in sets.items()}
    res = {"note": "SIMULATED labels (callverse/learning/simulator.py); fit on train personas, selected on val, eval read once",
           "rows": {k: len(v) for k, v in sets.items()}, "models": {}}
    fixed = {k: [predict_satisfaction(r, model=base, stacker=False)["score"] for r in sets[k]] for k in sets}
    res["models"]["fixed_text_delay"] = {"val": metrics(sets["val"], Y["val"], fixed["val"])}
    res["models"]["mean_of_train"] = {"val": metrics(sets["val"], Y["val"], [np.mean(Y["train"])] * len(Y["val"]))}
    fitted = {}
    for name, m in candidates().items():
        t = time.perf_counter(); m.fit(X["train"], Y["train"]); fit_s = time.perf_counter() - t
        t = time.perf_counter(); pv = m.predict(X["val"]); ms = (time.perf_counter() - t) * 1000 / len(X["val"])
        res["models"][name] = {"val": metrics(sets["val"], Y["val"], pv), "fit_s": round(fit_s, 1), "predict_ms_per_row": round(ms, 3)}
        fitted[name] = m
        print(name, res["models"][name], flush=True)
    ranked = sorted(fitted, key=lambda n: (res["models"][n]["val"]["mae"], -res["models"][n]["val"]["pairwise_pref_acc"]))
    best = ranked[0]
    res["selected"] = best
    pe = fitted[best].predict(X["eval"])
    res["eval_selected"] = {"all": metrics(sets["eval"], Y["eval"], pe),
                            "by_company": by_slice(sets["eval"], Y["eval"], pe, lambda r: r["company"]),
                            "by_emotion": by_slice(sets["eval"], Y["eval"], pe, lambda r: r["situation"]["emotion"]),
                            "by_reply_quality": by_slice(sets["eval"], Y["eval"], pe,
                                                         lambda r: "wrong" if r["corruption"] else ("degraded" if r.get("degradation") else "clean"))}
    res["eval_fixed_text_delay"] = metrics(sets["eval"], Y["eval"], fixed["eval"])
    res["eval_mean_of_train"] = metrics(sets["eval"], Y["eval"], [np.mean(Y["train"])] * len(Y["eval"]))
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    (MODEL_DIR / "stacker_selected.pkl").write_bytes(pickle.dumps(fitted[best]))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "satisfaction_models.json").write_text(json.dumps(res, indent=2))
    print("selected:", best, res["eval_selected"]["all"])


if __name__ == "__main__":
    main()
