"""Summarise the shared-model experiment (A separate / B shared / C hybrid) over training seeds.

    python -m shared.aggregate --dir results/shared
Reads results/shared/{arch}_s{seed}.json, prints mean +- std over seeds and writes summary.json + curves.png.
Negative transfer = the shared/hybrid model is worse than "separate" on a task by more than the seed noise.
SIMULATOR + SIMULATED data only.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

E_KEYS = ["ret", "sla_pct", "urgent_sla_pct", "abandon_pct", "sim_csat", "cost", "violations"]
F_KEYS = ["mae", "f1_macro_3class", "spearman"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="results/shared")
    a = ap.parse_args()
    d = Path(a.dir)
    runs = defaultdict(list)
    for f in sorted(d.glob("*_s*.json")):
        r = json.loads(f.read_text())
        runs[r["arch"]].append(r)

    def ms(vals):
        return {"mean": float(np.mean(vals)), "std": float(np.std(vals)), "n": len(vals)}

    summary = {}
    for arch, rs in runs.items():
        summary[arch] = {
            "seeds": [r["seed"] for r in rs],
            "e_test": {k: ms([r["e_test"][k] for r in rs]) for k in E_KEYS},
            "f_test": {k: ms([r["f_test"][k] for r in rs]) for k in F_KEYS},
            "f_val": {k: ms([r["f_val"][k] for r in rs]) for k in F_KEYS},
            "params_total_unique": rs[0]["params_total_unique"],
            "params_e": rs[0]["params_e"], "params_f_lite": rs[0]["params_f_lite"],
            "train_s": ms([r["train_s"] for r in rs]),
            "peak_rss_mb": ms([r["peak_rss_mb"] for r in rs]),
            "e_decision_ms_p50": ms([r["e_decision_ms_p50"] for r in rs]),
            "f_predict_ms_p50": ms([r["f_predict_ms_p50"] for r in rs]),
        }

    # negative transfer check against the separate models (difference > 1 pooled std = flagged)
    if "separate" in summary:
        base = summary["separate"]
        for arch in summary:
            if arch == "separate":
                continue
            s = summary[arch]
            de = s["e_test"]["ret"]["mean"] - base["e_test"]["ret"]["mean"]
            ne = max(s["e_test"]["ret"]["std"], base["e_test"]["ret"]["std"], 1e-9)
            df = s["f_test"]["mae"]["mean"] - base["f_test"]["mae"]["mean"]       # higher MAE = worse
            nf = max(s["f_test"]["mae"]["std"], base["f_test"]["mae"]["std"], 1e-9)
            s["vs_separate"] = {
                "e_ret_delta": de, "e_negative_transfer": bool(de < -ne),
                "f_mae_delta": df, "f_negative_transfer": bool(df > nf),
                "param_saving_pct": 100 * (1 - s["params_total_unique"] / base["params_total_unique"]),
            }
    (d / "summary.json").write_text(json.dumps(summary, indent=2))

    print(f"{'arch':9s} {'E ret':>14s} {'SLA%':>6s} {'urg':>6s} {'csat':>6s} {'cost':>6s} {'F MAE':>14s} "
          f"{'F F1':>6s} {'params':>7s} {'train s':>8s}")
    for arch, s in summary.items():
        e, f = s["e_test"], s["f_test"]
        print(f"{arch:9s} {e['ret']['mean']:7.2f}±{e['ret']['std']:5.2f} {e['sla_pct']['mean']:6.2f} "
              f"{e['urgent_sla_pct']['mean']:6.2f} {e['sim_csat']['mean']:6.3f} {e['cost']['mean']:6.0f} "
              f"{f['mae']['mean']:7.4f}±{f['mae']['std']:.4f} {f['f1_macro_3class']['mean']:6.3f} "
              f"{s['params_total_unique']:7d} {s['train_s']['mean']:8.0f}")
        if "vs_separate" in s:
            print("          vs separate:", {k: round(v, 3) if isinstance(v, float) else v
                                           for k, v in s["vs_separate"].items()})
    plot(runs, d)


def plot(runs, d: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4))
    for arch, rs in sorted(runs.items()):
        n = min(len(r["curve"]) for r in rs)
        x = [p["step"] for p in rs[0]["curve"][:n]]
        e = np.array([[p["e_val_ret"] for p in r["curve"][:n]] for r in rs])
        f = np.array([[p["f_val_mae"] for p in r["curve"][:n]] for r in rs])
        a1.plot(x, e.mean(0), label=arch)
        a1.fill_between(x, e.min(0), e.max(0), alpha=0.15)
        a2.plot(x, f.mean(0), label=arch)
        a2.fill_between(x, f.min(0), f.max(0), alpha=0.15)
    a1.set_title("Agent E VAL return (higher = better)")
    a2.set_title("F-lite VAL MAE (lower = better)")
    for ax in (a1, a2):
        ax.set_xlabel("environment steps")
        ax.legend()
    fig.tight_layout()
    fig.savefig(d / "curves.png", dpi=110)


if __name__ == "__main__":
    main()
