"""Figures for the v5 deliverables (real data only: run val_logs and evaluation CSV/JSON files).

    python -m v5.e.figures5 curves      -> figures/e3_learning_curves.png (V3 VAL return during training per arm)
    python -m v5.e.figures5 forest      -> figures/e8_dev_forest.png (DEV paired differences vs matched control)
    python -m v5.e.figures5 test5       -> figures/e9_test5_*.png
"""

import csv
import json
import sys
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from v5.e.ablation import ARMS, done_seeds  # noqa: E402
from v5.e.common5 import E5, find_run  # noqa: E402

FIG = E5 / "figures"
COL = ["#2a6fdb", "#e07b39", "#3a9e5c", "#b8408f", "#7a5cc7", "#8a8a8a", "#c9a227", "#1aa3a3"]


def val_curve(run_id):
    p = find_run(run_id) / "val_log.csv"
    rows = list(csv.DictReader(open(p)))
    return np.array([int(r["step"]) for r in rows]), np.array([float(r["val_return"]) for r in rows])


def curves():
    FIG.mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 5))
    ctl_seeds = range(5)
    st, ys = None, []
    for s in ctl_seeds:
        st, y = val_curve(f"dueling_dqn_equal_h64x64_150k_s{s}")
        ys.append(y)
    m = np.mean(ys, 0)
    ax.plot(st / 1e3, m, color="black", lw=2.2, label=f"control V3 Dueling DQN (n={len(ys)})")
    for k, (name, (pat, ctl)) in enumerate(ARMS.items()):
        seeds = done_seeds(pat)
        if not seeds or "dueling_dqn" not in pat:
            continue
        ys = [val_curve(pat.format(s))[1] for s in seeds]
        ax.plot(st / 1e3, np.mean(ys, 0), color=COL[k % len(COL)], lw=1.6, label=f"{name} (n={len(ys)})")
    ax.set_ylim(-320, -160)
    ax.set_xlabel("training steps (thousands)")
    ax.set_ylabel("V3 VAL return (48 days, mean over seeds)")
    ax.set_title("Learning curves on V3 VAL (selection set; noisy, see E_ABLATIONS)")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="lower right")
    fig.tight_layout()
    fig.savefig(FIG / "e3_learning_curves.png", dpi=130)
    print("wrote", FIG / "e3_learning_curves.png")


def forest():
    res = json.loads((E5 / "results" / "ablation.json").read_text())["dev"]
    names = list(res)
    fig, axs = plt.subplots(1, 2, figsize=(11, 0.45 * len(names) + 1.6), sharey=True)
    for ax, (m, lab) in zip(axs, (("return", "Δ DEV return vs matched control"),
                                  ("sla_queue_c_pct", "Δ queue-C SLA (pp) vs matched control"))):
        for i, n in enumerate(names):
            c = res[n]["diff"][m]
            ax.errorbar(c["diff"], i, xerr=[[c["diff"] - c["ci95"][0]], [c["ci95"][1] - c["diff"]]], fmt="o",
                        color=COL[0] if n.endswith("pure") else COL[1], capsize=3)
        ax.axvline(0, color="black", lw=0.8)
        ax.set_xlabel(lab)
        ax.grid(alpha=0.3, axis="x")
    axs[0].set_yticks(range(len(names)))
    axs[0].set_yticklabels([f"{n} (n={len(res[n]['seeds'])})" for n in names], fontsize=8)
    axs[0].invert_yaxis()
    fig.suptitle("DEV (104 days): paired 95 % CI, two-level bootstrap (blue = pure RL, orange = inside floor@3)")
    fig.tight_layout()
    fig.savefig(FIG / "e8_dev_forest.png", dpi=130)
    print("wrote", FIG / "e8_dev_forest.png")


if __name__ == "__main__":
    {"curves": curves, "forest": forest}[sys.argv[1]]()
