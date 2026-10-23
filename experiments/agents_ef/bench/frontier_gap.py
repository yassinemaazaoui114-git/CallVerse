"""How far is each RL policy above/below the tuned-heuristic curve, at the SAME cost?

    python -m bench.frontier_gap            (reads results/frontier/frontier.json from bench/frontier.py)
For every RL run: linear interpolation of the Forecast(z) curve at the RL run's cost, then
gap = RL KPI - heuristic KPI at equal cost (positive = RL better). Also reports the "fair" heuristic:
the z with the best VAL return, scored on TEST. SIMULATOR results only.
"""

import json
from collections import defaultdict
from pathlib import Path

import numpy as np

KPIS = ["sla_pct", "urgent_sla_pct", "abandon_pct", "sim_csat"]


def main(path="results/frontier/frontier.json"):
    d = json.loads(Path(path).read_text())
    out = {}
    for split in ("val", "test"):
        h = d["heuristic"][split]
        zs = sorted(h, key=lambda z: h[z]["cost"])
        cost = np.array([h[z]["cost"] for z in zs])
        gaps = defaultdict(list)
        for run, r in d["rl"][split].items():
            algo = run.split("_balanced")[0]
            g = {k: r[k] - float(np.interp(r["cost"], cost, [h[z][k] for z in zs])) for k in KPIS}
            gaps[algo].append(g)
        out[split] = {a: {k: [float(np.mean([g[k] for g in v])), float(np.std([g[k] for g in v]))] for k in KPIS}
                      for a, v in gaps.items()}
    best_z = max(d["heuristic"]["val"], key=lambda z: d["heuristic"]["val"][z]["ret"])
    out["fair_heuristic"] = {"z_chosen_on_val": best_z, "test": d["heuristic"]["test"][best_z]}
    Path(path).with_name("frontier_gap.json").write_text(json.dumps(out, indent=2))
    print(f"Forecast z chosen on VAL = {best_z}: TEST ret {out['fair_heuristic']['test']['ret']:.2f}, "
          f"cost {out['fair_heuristic']['test']['cost']:.0f}")
    for split in ("val", "test"):
        print(f"[{split}] gap vs heuristic curve at equal cost (mean±std over seeds; + = RL better, "
              f"except abandon where - = better)")
        for a, g in out[split].items():
            print(f"  {a:20s} " + "  ".join(f"{k}={m:+.2f}±{s:.2f}" for k, (m, s) in g.items()))


if __name__ == "__main__":
    main()
