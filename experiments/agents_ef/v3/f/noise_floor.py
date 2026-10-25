"""Annotator-noise floor for the USS target (mean of k annotators) on the TEST split.

    python v3/f/noise_floor.py --data <f_v3/data_uss> --out v3/f/results/noise_floor.json
Model: rating_ij = truth_i + noise_ij, noise variance s2 (pooled within-dialogue variance, unbiased).
The target is the mean of k_i ratings, so even a perfect predictor of truth_i has error with variance s2 / k_i.
Assuming normal noise, its expected MAE = sqrt(2/pi) * sqrt(s2 / k_i). Rough lower bound, not a guarantee.
Also reported: target std (what a constant predictor fights) and the share of target variance that is noise.
"""
import argparse
import json
from pathlib import Path

import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--data", required=True)
ap.add_argument("--out", required=True)
a = ap.parse_args()
rows = [json.loads(l) for l in open(Path(a.data) / "test.jsonl", encoding="utf-8")]
res = {}
for g, sel in (("lang:en", lambda r: r["lang"] == "en"), ("lang:zh", lambda r: r["lang"] == "zh"),
               *[(f"sub:{s}", (lambda s: lambda r: r["sub"] == s)(s)) for s in ("SGD", "MWOZ", "ReDial", "CCPE", "JDDC")]):
    rr = [r for r in rows if sel(r)]
    ss = sum(((np.array(r["ratings"]) - np.mean(r["ratings"])) ** 2).sum() for r in rr)
    dof = sum(len(r["ratings"]) - 1 for r in rr)
    s2 = ss / dof
    k = np.array([len(r["ratings"]) for r in rr])
    noise_var_target = float(np.mean(s2 / k))
    tvar = float(np.var([r["rating"] for r in rr]))
    res[g] = {"n": len(rr), "annotator_noise_var": round(float(s2), 4),
              "expected_mae_of_perfect_predictor": round(float(np.mean(np.sqrt(2 / np.pi) * np.sqrt(s2 / k))), 4),
              "target_var": round(tvar, 4), "noise_share_of_target_var": round(noise_var_target / tvar, 3),
              "max_explainable_r2": round(1 - noise_var_target / tvar, 3)}
Path(a.out).write_text(json.dumps(res, indent=1))
print(json.dumps(res, indent=1))
