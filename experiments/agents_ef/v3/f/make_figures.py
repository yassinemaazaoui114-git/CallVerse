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


SHORT = {"tfidf_ridge": "TF-IDF+Ridge", "tfidf_ridge_en": "TF-IDF+Ridge (EN only)", "hgb_features": "HGB features",
         "tfidf_logreg": "TF-IDF+LogReg", "group_mean": "per-corpus mean", "mean": "global mean",
         "tinybert_ft_en_frac0.5_len128": "TinyBERT-4L EN /128", "e5small_trim_ft_L6_frac0.5_len128": "e5-small trim L6 /128",
         "e5small_trim_ft_L6_frac0.5_len256": "e5-small trim L6 /256", "e5small_trim_ft_frac0.5_len128": "e5-small trim L12 /128",
         "mminilmv2l6_trim_ft_frac0.5_len128": "mMiniLMv2-L6 trim /128", "tfidf_ridge_tail128tok": "TF-IDF last 128 tok",
         "tfidf_ridge_tail256tok": "TF-IDF last 256 tok", "tfidf_ridge_frac0.5": "TF-IDF+Ridge (50% TRAIN)",
         "group_mean_frac0.5": "per-corpus mean (50% TRAIN)"}
CORE = ["tfidf_ridge", "tfidf_ridge_en", "hgb_features", "tinybert_ft_en_frac0.5_len128",
        "e5small_trim_ft_L6_frac0.5_len128", "e5small_trim_ft_L6_frac0.5_len256", "e5small_trim_ft_frac0.5_len128",
        "mminilmv2l6_trim_ft_frac0.5_len128"]
short = lambda m: SHORT.get(m, m)


def color(m):
    return "#4C72B0" if "_ft" in m else "#999999" if "mean" in m else "#DD8452"


def fig_leaderboard():
    fig, ax = plt.subplots(2, 2, figsize=(11, 7.5))
    for j, g in enumerate(["lang:en", "lang:zh"]):
        rows = [r for r in board(g) if r["model"] != "group_mean_frac0.5"]
        names = [r["model"] for r in rows]
        y = np.arange(len(rows))
        for i, (k, lab) in enumerate([("mae", "TEST MAE (1-5 scale, lower = better)"),
                                      ("spearman", "TEST Spearman (higher = better)")]):
            vals = [r[f"test_{k}"] if r[f"test_{k}"] == r[f"test_{k}"] else 0 for r in rows]
            ax[i, j].barh(y, vals, xerr=[r[f"test_{k}_std"] for r in rows], color=[color(n) for n in names],
                          capsize=2)
            ax[i, j].set_yticks(y, [short(n) for n in names], fontsize=7)
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
    fig, ax = plt.subplots(2, 2, figsize=(11, 7.5))
    for i, g in enumerate(("lang:en", "lang:zh")):
        rr = [r for r in board(g) if r["model"] in CORE and r["n_params"]]
        lat = [(r.get(lat_key) or r["latency_p50_ms_bench"]) for r in rr]
        for r, x in zip(rr, lat):
            c = color(r["model"])
            ax[i, 0].errorbar(r["n_params"] / 1e6, r["test_mae"], yerr=r["test_mae_std"], fmt="o", c=c, capsize=2)
            ax[i, 0].annotate(short(r["model"]), (r["n_params"] / 1e6, r["test_mae"]), fontsize=6,
                              xytext=(3, 3), textcoords="offset points")
            ax[i, 1].errorbar(x, r["test_mae"], yerr=r["test_mae_std"], fmt="o", c=c, capsize=2)
            ax[i, 1].annotate(short(r["model"]), (x, r["test_mae"]), fontsize=6, xytext=(3, 3),
                              textcoords="offset points")
        gm = [r for r in board(g) if r["model"] == "group_mean"][0]["test_mae"]
        for a in ax[i]:
            a.axhline(gm, ls="--", c="k", lw=0.8, label="per-corpus mean floor")
            a.set_xscale("log")
            a.set_ylabel("TEST MAE")
            a.legend(fontsize=7)
        ax[i, 0].set_xlabel("parameters (millions, log)")
        ax[i, 1].set_xlabel("CPU latency p50, batch 1, 2 threads (ms, log)")
        ax[i, 0].set_title(f"USS {g} TEST: size vs error (mean ± std over seeds)", fontsize=9)
        ax[i, 1].set_title(f"USS {g} TEST: latency vs error (shared CPU: upper bound)", fontsize=9)
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


def fig_quant(paths, lat_rows):
    items = []
    for p in paths:
        q = json.loads(Path(p).read_text())
        name = Path(p).stem.replace("quant_", "").replace("amazon_rescore_e5small_trim_ft", "Amazon e5 trim L12/128")
        name = short(name)
        for k, lab in (("fp32", "fp32"), ("int8_dynamic", "int8"), ("int8_dynamic_val_recentred", "int8+VAL offset")):
            if k not in q:
                continue
            tag = Path(p).stem.replace("quant_", "")
            lt = lat_rows.get(tag + ("_int8" if k != "fp32" else ""))
            items.append((f"{name}\n{lab}", q[k].get("state_dict_mb") or q["int8_dynamic"]["state_dict_mb"],
                          q[k]["test"]["all"]["mae"], lt["p50"] if lt else None))
    fig, ax = plt.subplots(1, 3, figsize=(13, 4.4))
    x = np.arange(len(items))
    cols = ["#4C72B0" if "fp32" in it[0] else "#55A868" for it in items]
    for a, idx, lab in zip(ax, (1, 2, 3), ("state dict size (MB)", "TEST MAE (own dataset)",
                                          "CPU p50 latency batch 1 (ms), latency_cpu.json")):
        a.bar(x, [it[idx] if it[idx] is not None else 0 for it in items], color=cols)
        a.set_xticks(x, [it[0] for it in items], fontsize=6, rotation=60, ha="right")
        a.set_ylabel(lab)
    fig.suptitle("Dynamic int8 quantization of nn.Linear layers - same TEST split before/after (USS rows: USS TEST all; "
                 "Amazon rows: Amazon TEST EN+FR). Latency 0 = not measured", fontsize=8)
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
        lr = {}
        if (R / "latency_cpu.json").exists():
            lr = {r["model"]: r for r in json.loads((R / "latency_cpu.json").read_text())["rows"]}
        fig_quant(a.quant, lr)
    print(sorted(p.name for p in F.glob("*.png")))
