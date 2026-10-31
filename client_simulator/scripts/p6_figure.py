"""Chart: real vs simulated mean CSAT per waiting-time bucket, before/after the delay-aware calibration (test)."""
import numpy as np

from common import FIG, REAL, RESULTS, SIM, CAL, load_json, plot_style

DELAYS = ["0-5 min", "5-30 min", "30 min-2 h", "2-8 h", "8 h+"]
r = load_json(RESULTS / "p6_followup.json")
plt = plot_style()
fig, axes = plt.subplots(1, 2, figsize=(12, 3.8), sharey=True)
for ax, m in zip(axes, ["qwen3.5:4b", "phi4-mini:3.8b"]):
    t = r[m]["delay_aware"]["test"]
    glob = next(k for k in t if k.startswith("global (Phase 3"))
    exp = next(k for k in t if "expected" in k)
    x = np.arange(len(DELAYS))
    for i, (key, col, lab) in enumerate([(glob, SIM, "simulated, global map (before)"), (exp, CAL, "simulated, delay-aware (after)")]):
        ax.plot(x, [t[key]["by_delay"][b]["sim_mean"] for b in DELAYS], marker="o", color=col, lw=2, ms=8, label=lab)
    ax.plot(x, [t[glob]["by_delay"][b]["real_mean"] for b in DELAYS], marker="o", color=REAL, lw=2, ms=8, label="real customers")
    ax.set_xticks(x, [f"{b}\nn={t[glob]['by_delay'][b]['n']}" for b in DELAYS])
    ax.set_title(m, loc="left")
    ax.set_ylim(1, 5)
axes[0].set_ylabel("mean CSAT on test (1-5)")
axes[1].legend(frameon=False, fontsize=8, loc="lower left")
fig.suptitle("Mean satisfaction by waiting time: real vs simulated (CSAT test)", x=0.01, ha="left", fontweight="bold")
fig.tight_layout()
fig.savefig(FIG / "delay_aware_calibration.png")
