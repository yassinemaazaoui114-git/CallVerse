"""Figures for F2 (real result files only): VAL MAE per variant vs floors, and EN prediction spread.

    python -m v4.f.make_figures_v4      -> v4/f/figures/f2_variants_val.png
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent


def main():
    res = json.loads((HERE / "results/f2_experiments.json").read_text())["variants"]
    names = list(res)
    fig, ax = plt.subplots(1, 2, figsize=(10, 3.6))
    ax[0].bar(names, [res[n]["val"]["mae"] for n in names], color="#4C78A8")
    ax[0].axhline(0.414, color="k", ls="--", lw=1, label="per-corpus mean floor (V3 VAL 0.414)")
    ax[0].set_ylim(0.38, 0.42)
    ax[0].set_ylabel("VAL MAE (USS, all)")
    ax[0].legend(fontsize=7)
    ax[0].tick_params(axis="x", rotation=35, labelsize=7)
    ax[1].bar(names, [res[n]["val"]["spearman_en"] for n in names], color="#F58518")
    ax[1].set_ylabel("VAL Spearman, EN")
    ax[1].tick_params(axis="x", rotation=35, labelsize=7)
    fig.suptitle("F2: TF-IDF variants (selection on VAL only); two_turn = ShopNova-shaped view", fontsize=9)
    fig.tight_layout()
    fig.savefig(HERE / "figures/f2_variants_val.png", dpi=130)
    print("ok")


if __name__ == "__main__":
    main()
