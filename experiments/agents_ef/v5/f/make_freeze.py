"""Worker F v5 — freeze the TEST candidate list (VAL only), choose the ensemble weight on VAL, write the freeze file.

    $PY -m v5.f.make_freeze        -> v5/f/results/FREEZE_candidates.json (refuses to overwrite)

Selection rules (written in the notebook before running):
  ridge_v5     the F3 grid selection (results/f3_ridge_grid.json "selected")
  neural_v5    the completed v5 neural run (results/neural/*.json) with the lowest VAL MAE
  references   ridge_v3 (V3 saved Ridge) and e5_v3 (V3 selected e5 checkpoint, seed 1); floors mean / group_mean
  ensemble     w * ridge_v5 + (1 - w) * neural_v5, w in {0, 0.05, ..., 1} minimising VAL MAE. It is kept in the
               recommendation only if (a) its VAL MAE is >= 0.002 below the best single model's VAL MAE and
               (b) its TEST MAE paired-bootstrap CI vs the best single model lies below 0.
  comparisons  (pre-registered, Holm over the MAE p-values): ridge_v5 vs ridge_v3; neural_v5 vs e5_v3;
               neural_v5 vs ridge_v3; neural_v5 vs ridge_v5; ensemble vs the better single model on VAL.
"""

import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from v5.f.common import FREEZE, FV3, FV5, RESULTS, V3_RESULTS, load, mae, write_json, y_of  # noqa: E402


def v3_e5_val_preds():
    """VAL predictions of the V3 selected e5 checkpoint (V3 stored only TEST predictions)."""
    p = RESULTS / "val_preds_e5_v3_s1.json"
    if p.exists():
        return np.array(json.loads(p.read_text()))
    import torch
    torch.set_num_threads(2)
    from v3.f.f_predictor import SatisfactionPredictor
    m = SatisfactionPredictor.load(FV3 / "ckpt" / "e5small_trim_ft_L6_frac0.5_len256_s1")
    pv = m.scores([r["text"] for r in load("val")]).tolist()
    p.write_text(json.dumps(pv))
    return np.array(pv)


def main():
    if FREEZE.exists():
        raise SystemExit("freeze file exists: " + str(FREEZE))
    va = load("val")
    yva = y_of(va)
    grid = json.loads((RESULTS / "f3_ridge_grid.json").read_text())
    rsel = grid["selected"]["name"]
    pr = np.clip(np.array(grid["val_preds"][rsel]), 1, 5)
    runs = []
    for f in sorted((RESULTS / "neural").glob("*.json")):
        d = json.loads(f.read_text())
        if d.get("status") == "completed":
            runs.append(d)
    best = min(runs, key=lambda d: d["val_mae"])
    pn = np.clip(np.array(best["val_pred_best"]), 1, 5)
    pe3 = np.clip(v3_e5_val_preds(), 1, 5)
    ws = np.round(np.arange(0, 1.0001, 0.05), 2)
    curve = {float(w): mae(yva, w * pr + (1 - w) * pn) for w in ws}
    w = min(curve, key=curve.get)
    singles = {"ridge_v5": mae(yva, pr), "neural_v5": mae(yva, pn)}
    best_single = min(singles, key=singles.get)
    fr = {"created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
          "note": "Written BEFORE any v5 TEST scoring. Candidates and comparisons are fixed from here on.",
          "candidates": {
              "ridge_v3": {"kind": "ridge_v3", "path": str(FV3 / "ckpt" / "tfidf_ridge_tail256"), "role": "reference (V3 winner)"},
              "ridge_v5": {"kind": "ridge_v5", "path": str(FV5 / "ckpt" / f"ridge_v5_{rsel}"), "role": f"F3 selection ({rsel})",
                           "val_mae": singles["ridge_v5"]},
              "e5_v3": {"kind": "neural", "path": str(FV3 / "ckpt" / "e5small_trim_ft_L6_frac0.5_len256_s1"),
                        "role": "reference (V3 selected e5)", "val_mae": mae(yva, pe3)},
              "neural_v5": {"kind": "neural", "path": best["checkpoint"], "role": f"F4 selection ({best['name']})",
                            "val_mae": best["val_mae"]}},
          "neural_runs_val": {d["name"]: {"val_mae": d["val_mae"], "best_epoch": d["best_epoch"],
                                          "val_mae_curve": d["val_mae_curve"]} for d in runs},
          "v3_reference_files": {"mean (V3 floor)": "mean.json", "group_mean (V3 floor)": "group_mean.json"},
          "ensembles": [{"name": "ensemble_ridge_v5+neural_v5", "components": ["ridge_v5", "neural_v5"],
                         "weight_first": w, "val_mae": curve[w], "val_curve": curve,
                         "val_gain_vs_best_single": singles[best_single] - curve[w], "best_single_on_val": best_single,
                         "keep_rule": "VAL gain >= 0.002 AND TEST paired CI vs best single entirely below 0"}],
          "comparisons": [["ridge_v3", "ridge_v5"], ["e5_v3", "neural_v5"], ["ridge_v3", "neural_v5"],
                          ["ridge_v5", "neural_v5"], [best_single, "ensemble_ridge_v5+neural_v5"]],
          "primary_metric": "MAE (paired bootstrap over TEST dialogues, Holm over the 5 comparisons)"}
    write_json(FREEZE, fr)
    print(json.dumps({k: fr[k] for k in ("created_utc", "candidates", "neural_runs_val")}, indent=1))
    print("ensemble w", w, "VAL", round(curve[w], 4), "singles", singles)


if __name__ == "__main__":
    main()
