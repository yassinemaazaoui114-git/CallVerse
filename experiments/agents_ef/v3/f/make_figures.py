"""Agent F v3 figures (PNG) from the result files only.

    python v3/f/make_figures.py --best <USS tag> [--quant v3/f/results/quant_<tag>.json]
Outputs in v3/f/figures/. Every title names the dataset + split; error bars = std over seeds (fine-tuned models).
"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

H = Path(__file__).resolve().parent
R, F = H / "results", H / "figures"
F.mkdir(exist_ok=True)
plt.rcParams.update({"font.size": 9, "figure.dpi": 130})


def board(group):
    rows = [r for r in json.loads((R / "leaderboard_uss.json").read_text())["rows"] if r["group"] == group]
    return sorted(rows, key=lambda r: r["val_mae"])


def color(m):
    return "#4C72B0" if "_ft" in m else "#999999" if "mean" in m else "#DD8452"


def fig_leaderboard():
    fig, ax = plt.subplots(2, 2, figsize=(11, 7.5))
    for j, g in enumerate(["lang:en", "lang:zh"]):
        rows = board(g)
        names = [r["model"] for r in rows]
        y = np.arange(len(rows))
        for i, (k, lab) in enumerate([("mae", "TEST MAE (1-5 scale, lower = better)"),
                                      ("spearman", "TEST Spearman (higher = better)")]):
            vals = [r[f"test_{k}"] if r[f"test_{k}"] == r[f"test_{k}"] else 0 for r in rows]
            ax[i, j].barh(y, vals, xerr=[r[f"test_{k}_std"] for r in rows], color=[color(n) for n in names],
                          capsize=2)
            ax[i, j].set_yticks(y, names, fontsize=7)
            ax[i, j].invert_yaxis()
            ax[i, j].set_xlabel(lab)
            ax[i, j].set_title(f"USS {'EN (SGD+MWOZ+ReDial+CCPE)' if j == 0 else 'ZH (JDDC)'} - TEST, ranked by VAL MAE",
                               fontsize=9)
            if k == "mae":
                gm = [r for r in rows if r["model"] == "group_mean"]
                if gm:
                    ax[i, j].axvline(gm[0]["test_mae"], ls="--", c="k", lw=0.8, label="per-corpus mean floor")
                    ax[i, j].legend(fontsize=7)
    fig.suptitle("Agent F - dialogue-level satisfaction (USS, mean of annotators). Bars: mean ± std over seeds "
                 "(blue = fine-tuned, orange = classic, grey = floor)", fontsize=9)
    fig.tight_layout()
    fig.savefig(F / "uss_leaderboard_mae_spearman.png")
    plt.close(fig)


def fig_cost(lat_key):
    rows = [r for r in board("lang:zh") + board("lang:en") if r["n_params"] and r["n_params"] > 1000]
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
    for g, mk in (("lang:en", "o"), ("lang:zh", "s")):
        rr = [r for r in rows if r["group"] == g]
        ax[0].errorbar([r["n_params"] / 1e6 for r in rr], [r["test_mae"] for r in rr],
                       yerr=[r["test_mae_std"] for r in rr], fmt=mk, capsize=2, label=f"USS {g}")
        lat = [(r.get(lat_key) or r["latency_p50_ms_bench"]) for r in rr]
        ax[1].errorbar(lat, [r["test_mae"] for r in rr], yerr=[r["test_mae_std"] for r in rr], fmt=mk,
                       capsize=2, label=f"USS {g}")
        for r, x in zip(rr, lat):
            ax[0].annotate(r["model"].replace("_frac0.5_len128", ""), (r["n_params"] / 1e6, r["test_mae"]),
                           fontsize=6)
            ax[1].annotate(r["model"].replace("_frac0.5_len128", ""), (x, r["test_mae"]), fontsize=6)
    ax[0].set_xscale("log")
    ax[0].set_xlabel("parameters (millions, log)")
    ax[1].set_xscale("log")
    ax[1].set_xlabel("CPU latency p50, batch 1, 2 threads (ms, log)")
    for a in ax:
        a.set_ylabel("TEST MAE")
        a.legend(fontsize=7)
    ax[0].set_title("USS TEST: size vs error", fontsize=9)
    ax[1].set_title("USS TEST: latency vs error (CPU shared with other jobs: upper bound)", fontsize=9)
    fig.tight_layout()
    fig.savefig(F / "uss_params_latency_vs_mae.png")
    plt.close(fig)


def fig_amazon():
    rows = json.loads((R / "leaderboard_amazon.json").read_text())["rows"]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    x = np.arange(len(rows))
    for k, (lg, off) in enumerate((("en", -0.2), ("fr", 0.2))):
        ax.bar(x + off, [r["test_mae_mean"][lg] for r in rows], 0.4, yerr=[r["test_mae_std"][lg] for r in rows],
               capsize=2, label=lg.upper())
    ax.set_xticks(x, [r["model"] for r in rows], rotation=35, ha="right", fontsize=7)
    ax.set_ylabel("TEST MAE (stars, lower = better)")
    ax.set_title("Amazon reviews EN/FR (AUXILIARY: product stars) - TEST 399, by language, mean ± std over seeds",
                 fontsize=9)
    ax.legend()
    fig.tight_layout()
    fig.savefig(F / "amazon_language_breakdown.png")
    plt.close(fig)


def fig_confusion(tag):
    d = json.loads((R / "uss" / f"{tag}.json").read_text())
    run = min(d["runs"], key=lambda r: r["val"]["all"]["mae"])
    groups = [g for g in ("lang:en", "lang:zh") if g in run["test"]]
    fig, ax = plt.subplots(1, len(groups), figsize=(5 * len(groups), 4.2))
    ax = np.atleast_1d(ax)
    for a, g in zip(ax, groups):
        cm = np.array(run["test"][g]["confusion_5"])
        a.imshow(cm, cmap="Blues")
        for i in range(5):
            for j in range(5):
                a.text(j, i, cm[i, j], ha="center", va="center", fontsize=8,
                       color="white" if cm[i, j] > cm.max() / 2 else "black")
        a.set_xticks(range(5), range(1, 6))
        a.set_yticks(range(5), range(1, 6))
        a.set_xlabel("predicted (rounded)")
        a.set_ylabel("true (mean of annotators, rounded)")
        a.set_title(f"USS {g} TEST - {tag} (seed {run.get('seed', 0)})", fontsize=8)
    fig.tight_layout()
    fig.savefig(F / "uss_confusion_best.png")
    plt.close(fig)


def fig_quant(paths):
    items = []
    for p in paths:
        q = json.loads(Path(p).read_text())
        name = Path(p).stem.replace("quant_", "").replace("amazon_rescore_", "Amazon: ")
        for k in ("fp32", "int8_dynamic"):
            items.append((f"{name}\n{k}", q[k]["state_dict_mb"], q[k]["test"]["all"]["mae"],
                          q[k]["latency_ms_cpu_batch1"]["p50"]))
    fig, ax = plt.subplots(1, 3, figsize=(12, 4))
    x = np.arange(len(items))
    for a, idx, lab in zip(ax, (1, 2, 3), ("state dict size (MB)", "TEST MAE", "CPU p50 latency batch 1 (ms)")):
        a.bar(x, [it[idx] for it in items], color=["#4C72B0" if "fp32" in it[0] else "#55A868" for it in items])
        a.set_xticks(x, [it[0] for it in items], fontsize=6)
        a.set_ylabel(lab)
    fig.suptitle("Dynamic int8 quantization (nn.Linear) - same TEST split before/after; latency under shared CPU",
                 fontsize=9)
    fig.tight_layout()
    fig.savefig(F / "quantization_tradeoff.png")
    plt.close(fig)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--best", required=True)
    ap.add_argument("--quant", nargs="*", default=[])
    ap.add_argument("--lat-key", default="latency_p50_ms_quiet")
    a = ap.parse_args()
    fig_leaderboard()
    fig_cost(a.lat_key)
    fig_amazon()
    fig_confusion(a.best)
    if a.quant:
        fig_quant(a.quant)
    print(sorted(p.name for p in F.glob("*.png")))
