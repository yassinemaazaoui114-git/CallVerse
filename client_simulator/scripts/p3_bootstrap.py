"""Paired bootstrap (same test items) of each model's chosen-version QWK and MAE, and of differences vs the best model.
python p3_bootstrap.py MODEL...  -> results/p3_bootstrap.json"""
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import cohen_kappa_score

from common import RESULTS, load_json, save_json
from llm import short

B = 2000


def chosen_preds(m, name, t3):
    d = pd.read_csv(RESULTS / f"p3_test3_{name}_{short(m).replace(':', '_').replace('/', '_')}_chosen_test.csv")
    return d.set_index("id").real, pd.Series(d.pred.values, index=d.id)


def qwk(a, b):
    return cohen_kappa_score(a, b, weights="quadratic", labels=[1, 2, 3, 4, 5])


def main(models):
    t3 = load_json(RESULTS / "p3_test3_scores.json")
    out = {"B": B, "note": "95% percentile intervals; paired resampling of the same test items"}
    rng = np.random.RandomState(0)
    for name in ("csat", "conv"):
        P = {}
        real = None
        for m in models:
            if name not in t3.get(short(m), {}):
                continue
            y, p = chosen_preds(m, name, t3)
            real = y if real is None else real
            P[short(m)] = p.reindex(real.index).values
        y = real.values
        idx = [rng.randint(0, len(y), len(y)) for _ in range(B)]
        res = {}
        for m, p in P.items():
            q = np.array([qwk(y[i], p[i]) for i in idx])
            res[m] = {"qwk": qwk(y, p), "qwk_ci": [float(np.percentile(q, 2.5)), float(np.percentile(q, 97.5))],
                      "mae": float(np.mean(np.abs(y - p)))}
        best = max(res, key=lambda k: res[k]["qwk"])
        for m, p in P.items():
            if m == best:
                continue
            dq = np.array([qwk(y[i], P[best][i]) - qwk(y[i], p[i]) for i in idx])
            res[m]["qwk_gap_to_best"] = float(res[best]["qwk"] - res[m]["qwk"])
            res[m]["qwk_gap_ci"] = [float(np.percentile(dq, 2.5)), float(np.percentile(dq, 97.5))]
            res[m]["share_of_resamples_best_is_better"] = float(np.mean(dq > 0))
        out[name] = {"best": best, "models": res}
    save_json(out, RESULTS / "p3_bootstrap.json")
    for name in ("csat", "conv"):
        print(name, "best", out[name]["best"])
        for m, r in out[name]["models"].items():
            print(f"  {m:14s} qwk {r['qwk']:.3f} CI {r['qwk_ci'][0]:.3f}..{r['qwk_ci'][1]:.3f} mae {r['mae']:.3f}",
                  f"gap CI {r['qwk_gap_ci'][0]:.3f}..{r['qwk_gap_ci'][1]:.3f} P(best better) {r['share_of_resamples_best_is_better']:.2f}"
                  if "qwk_gap_ci" in r else "")


if __name__ == "__main__":
    main(sys.argv[1:])
