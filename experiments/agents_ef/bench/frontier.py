"""Cost-vs-service frontier: is an RL policy better than the forecast heuristic AT THE SAME COST?

Sweeps the heuristic's safety-staffing factor z and reports, for VAL and TEST, cost / SLA / urgent SLA / CSAT.
RL policies (VAL-chosen checkpoints) are placed on the same axes. Nothing is selected here: it is a picture of
trade-offs. Writes results/frontier/frontier.json and frontier.png.
"""

import json
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from baselines.heuristics import Forecast  # noqa: E402
from bench.benchmark_e import load_run  # noqa: E402
from bench.evaluation import evaluate, summarize  # noqa: E402

torch.set_num_threads(1)
out = Path("results/frontier")
out.mkdir(parents=True, exist_ok=True)
res = {"heuristic": {}, "rl": {}}
for split in ("val", "test"):
    for z in (-0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0, 1.5):
        p = Forecast(z)
        res["heuristic"].setdefault(split, {})[str(z)] = summarize(evaluate(lambda e, o, m: p.act(e, o, m), split))
    for run in sorted(Path("results/runs").glob("*_balanced_h64x64_s*")):
        info, agent = load_run(run)
        if info["algo"] == "tabular_q":
            continue
        s = summarize(evaluate(lambda e, o, m: agent.act(o, m, explore=False), split))
        res["rl"].setdefault(split, {})[run.name] = s
(out / "frontier.json").write_text(json.dumps(res, indent=2))

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
fig, axes = plt.subplots(1, 3, figsize=(14, 4))
for ax, key in zip(axes, ["sla_pct", "urgent_sla_pct", "sim_csat"]):
    h = res["heuristic"]["test"]
    xs = [h[z]["cost"] for z in h]
    ax.plot(xs, [h[z][key] for z in h], "o-", label="forecast heuristic, z sweep")
    for name, s in res["rl"]["test"].items():
        algo = name.split("_balanced")[0]
        ax.scatter(s["cost"], s[key], marker="x", label=algo)
    ax.set_xlabel("day cost (TEST mean)")
    ax.set_ylabel(key)
    ax.set_title(f"TEST: {key} vs cost")
h, l = axes[0].get_legend_handles_labels()
uniq = dict(zip(l, h))
axes[2].legend(uniq.values(), uniq.keys(), fontsize=7)
fig.tight_layout()
fig.savefig(out / "frontier.png", dpi=110)
for split in ("val", "test"):
    print(f"== {split}")
    for z, s in res["heuristic"][split].items():
        print(f"forecast z={z:>5s} cost {s['cost']:6.0f} SLA {s['sla_pct']:6.2f} urg {s['urgent_sla_pct']:6.2f} aband {s['abandon_pct']:5.2f} csat {s['sim_csat']:.3f} fb {s['fallback_share']:.2f}")
    for name, s in res["rl"][split].items():
        print(f"{name:38s} cost {s['cost']:6.0f} SLA {s['sla_pct']:6.2f} urg {s['urgent_sla_pct']:6.2f} aband {s['abandon_pct']:5.2f} csat {s['sim_csat']:.3f} fb {s['fallback_share']:.2f}")
