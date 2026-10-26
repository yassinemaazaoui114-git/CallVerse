"""Worker F v5 — F6/F7: evaluate the frozen candidates on TEST (predictions already made once by score_test.py).

    $PY -m v5.f.evaluate     -> v5/f/results/f7_evaluation.json, leaderboard_v5.csv, figures/f7_*.png

Reads FREEZE_candidates.json (written before any v5 TEST scoring): candidate list, the ensemble weight chosen on
VAL, and the pre-registered comparisons. Nothing here is tuned: TEST predictions are only measured.
Metrics per model: MAE, RMSE, Spearman, QWK (rounded), each with a bootstrap 95% CI over TEST dialogues;
per-class MAE (rounded label), calibration slope (pred on label) and prediction SD; subsets: dissatisfied
(label <= 2.5), highly satisfied (label >= 4), EN, ZH; cost (params, load, latency p50/p95, peak RSS).
Paired comparisons: paired bootstrap of the MAE difference (2,000 resamples, same resampled dialogues for both
models) + Spearman difference; Holm correction over the pre-registered MAE comparisons.
"""

import csv
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from v5.f.common import (FIG, FREEZE, RESULTS, V3_RESULTS, holm, load, mae, paired_bootstrap, qwk,  # noqa: E402
                         slope, spearman, to_int, write_json, y_of)


def boot_ci(y, p, f, n=2000, seed=1):
    rng = np.random.default_rng(seed)
    v = []
    for _ in range(n):
        i = rng.integers(0, len(y), len(y))
        v.append(f(y[i], p[i]))
    return [round(float(np.nanpercentile(v, 2.5)), 4), round(float(np.nanpercentile(v, 97.5)), 4)]


def block(y, p):
    p = np.clip(p, 1, 5)
    out = {"n": int(len(y)), "mae": round(mae(y, p), 4), "rmse": round(float(np.sqrt(((p - y) ** 2).mean())), 4),
           "pred_mean": round(float(p.mean()), 3), "pred_sd": round(float(p.std()), 4)}
    if len(y) >= 10 and np.std(y) > 0:
        out["spearman"] = round(spearman(y, p), 4)
        out["slope_pred_on_label"] = round(slope(y, p), 4)
    return out


def full(y, p, rows):
    p = np.clip(np.asarray(p, float), 1, 5)
    m = block(y, p)
    m["mae_ci95"] = boot_ci(y, p, lambda a, b: np.abs(a - b).mean())
    m["spearman_ci95"] = boot_ci(y, p, spearman)
    m["qwk"] = round(qwk(y, p), 4)
    m["qwk_ci95"] = boot_ci(y, p, qwk)
    yi = to_int(y)
    m["mae_by_true_class"] = {int(k): {"n": int((yi == k).sum()), "mae": round(mae(y[yi == k], p[yi == k]), 3),
                                       "signed": round(float((p[yi == k] - y[yi == k]).mean()), 3)}
                              for k in range(1, 6) if (yi == k).any()}
    lang = np.array([r["lang"] for r in rows])
    for name, mask in (("dissatisfied_le2.5", y <= 2.5), ("high_ge4", y >= 4), ("en", lang == "en"), ("zh", lang == "zh")):
        m[name] = block(y[mask], p[mask])
        m[name]["mae_ci95"] = boot_ci(y[mask], p[mask], lambda a, b: np.abs(a - b).mean())
    # dissatisfied detection: recall / precision of "pred < 2.75" vs label <= 2.5 (threshold fixed, not tuned)
    pos, hit = y <= 2.5, p < 2.75
    m["dissatisfied_detect_pred_lt_2.75"] = {"recall": round(float(hit[pos].mean()), 4),
                                             "precision": round(float(pos[hit].mean()), 4) if hit.any() else None,
                                             "n_pred_pos": int(hit.sum())}
    return m


def main():
    fr = json.loads(FREEZE.read_text())
    te = load("test")
    y = y_of(te)
    ids = [r["id"] for r in te]
    preds, cost = {}, {}
    for name in fr["candidates"]:
        d = json.loads((RESULTS / "test" / f"{name}.json").read_text())
        assert d["test_ids"] == ids
        preds[name] = np.array(d["test_pred"], float)
        cost[name] = {k: d[k] for k in ("n_params", "load_s", "latency_ms_batch1_val", "peak_rss_mb", "sha256")}
    for name, f in fr.get("v3_reference_files", {}).items():                 # floors (V3 result files)
        d = json.loads((V3_RESULTS / f).read_text())
        run = next(r for r in d["runs"] if r.get("seed", 0) == d["best_seed_by_val"])
        assert d["test_ids"] == ids
        preds[name] = np.array(run["test_pred"], float)
        cost[name] = {"n_params": run.get("n_params")}
    for ens in fr.get("ensembles", []):
        a, b, w = ens["components"][0], ens["components"][1], ens["weight_first"]
        preds[ens["name"]] = w * np.clip(preds[a], 1, 5) + (1 - w) * np.clip(preds[b], 1, 5)
        cost[ens["name"]] = {"n_params": (cost[a].get("n_params") or 0) + (cost[b].get("n_params") or 0),
                             "note": f"{w:g} x {a} + {1 - w:g} x {b}"}
    res = {"freeze_created_utc": fr["created_utc"], "models": {}, "comparisons": {}}
    for name, p in preds.items():
        res["models"][name] = {**full(y, p, te), "cost": cost[name]}
    pv = {}
    for a, b in fr["comparisons"]:
        k = f"{b} vs {a}"
        res["comparisons"][k] = {"mae": paired_bootstrap(y, preds[a], preds[b], "mae"),
                                 "spearman": paired_bootstrap(y, preds[a], preds[b], "spearman", n=1000)}
        for sub, mask in (("en", np.array([r["lang"] == "en" for r in te])), ("zh", np.array([r["lang"] == "zh" for r in te])),
                          ("dissatisfied_le2.5", y <= 2.5)):
            res["comparisons"][k][f"mae_{sub}"] = paired_bootstrap(y[mask], preds[a][mask], preds[b][mask], "mae")
        pv[k] = res["comparisons"][k]["mae"]["p_boot"]
    adj = holm(pv)
    for k in pv:
        res["comparisons"][k]["mae"]["p_holm"] = round(adj[k], 4)
    write_json(RESULTS / "f7_evaluation.json", res)
    with open(RESULTS / "leaderboard_v5.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", "params", "TEST_MAE", "MAE_CI95", "RMSE", "Spearman", "Sp_CI95", "QWK", "MAE_EN", "MAE_ZH",
                    "MAE_dissat", "MAE_high", "slope", "pred_sd", "lat_p50_ms", "lat_p95_ms", "peak_rss_mb"])
        for name, m in sorted(res["models"].items(), key=lambda kv: kv[1]["mae"]):
            c = m["cost"]
            lat = c.get("latency_ms_batch1_val") or {}
            w.writerow([name, c.get("n_params"), m["mae"], m["mae_ci95"], m["rmse"], m.get("spearman"),
                        m["spearman_ci95"], m["qwk"], m["en"]["mae"], m["zh"]["mae"], m["dissatisfied_le2.5"]["mae"],
                        m["high_ge4"]["mae"], m.get("slope_pred_on_label"), m["pred_sd"], lat.get("p50"), lat.get("p95"),
                        c.get("peak_rss_mb")])
    figures(res, preds, y, te)
    for name, m in sorted(res["models"].items(), key=lambda kv: kv[1]["mae"]):
        print(f"{name:34s} MAE {m['mae']:.4f} {m['mae_ci95']} Sp {m.get('spearman')} QWK {m['qwk']} "
              f"EN {m['en']['mae']} ZH {m['zh']['mae']} dissat {m['dissatisfied_le2.5']['mae']}")
    for k, v in res["comparisons"].items():
        print(k, "dMAE", round(v["mae"]["diff_b_minus_a"], 4), [round(x, 4) for x in v["mae"]["ci95"]],
              "p_holm", v["mae"]["p_holm"], "dSp", round(v["spearman"]["diff_b_minus_a"], 4))


def figures(res, preds, y, te):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    for name, m in res["models"].items():
        lat = (m["cost"].get("latency_ms_batch1_val") or {}).get("p50")
        if lat:
            ax[0].errorbar(lat, m["mae"], yerr=[[m["mae"] - m["mae_ci95"][0]], [m["mae_ci95"][1] - m["mae"]]], fmt="o")
            ax[0].annotate(name, (lat, m["mae"]), fontsize=7, xytext=(4, 2), textcoords="offset points")
    ax[0].set_xscale("log")
    ax[0].set(xlabel="CPU latency p50, batch 1 (ms, log)", ylabel="TEST MAE (95% CI)", title="Accuracy vs cost (USS TEST)")
    yi = to_int(y)
    for name in [n for n in res["models"] if not n.startswith(("mean", "group"))][:5]:
        p = np.clip(preds[name], 1, 5)
        ks = [k for k in range(1, 6) if (yi == k).sum() >= 5]
        ax[1].plot(ks, [p[yi == k].mean() for k in ks], "o-", label=name, ms=4)
    ax[1].plot([1, 5], [1, 5], "k--", lw=0.8)
    ax[1].set(xlabel="true rounded label (classes with >= 5 TEST items)", ylabel="mean prediction",
              title="Regression to the mean per class (TEST)")
    ax[1].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(FIG / "f7_pareto_and_classes.png", dpi=120)


if __name__ == "__main__":
    main()
