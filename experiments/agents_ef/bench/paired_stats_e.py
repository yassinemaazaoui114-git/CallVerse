"""Statistical uncertainty for Agent E v2: PAIRED per-day differences vs the VAL-tuned Forecast rule.

    python -m bench.paired_stats_e --out results/agent_e_v2_stats
Every policy is run on the SAME 56 TEST days (same seeds -> same arrivals), so day-level differences are paired.
For each condition and policy family (3 training seeds each):
  diff[seed, day] = KPI(policy, seed, day) - KPI(forecast z=0, day)
  mean diff and a 95 % CI from a two-level bootstrap (resample seeds, then days; 4000 draws), plus the share of
  days where the policy's return beats the rule ("win rate").
Two-level bootstrap = uncertainty from BOTH the training seed (how lucky the RL run was) and the test days.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from baselines.heuristics import ErlangC, Forecast  # noqa: E402
from bench.benchmark_e import load_run  # noqa: E402
from bench.evaluation import SPLITS, evaluate  # noqa: E402
from bench.generalize_e import CONDITIONS  # noqa: E402
from bench.guarded_e import guarded  # noqa: E402
from env.factory import make_env  # noqa: E402

KPIS = ["ret", "sla_pct", "abandon_pct", "cost", "sim_csat"]
FAMILIES = {"dueling_400k": "dueling_double_dqn_intake_h64x64_s{}_400k",
            "dueling_dr": "dueling_double_dqn_intake_h64x64_s{}_dr",
            "ppo": "ppo_intake_h64x64_s{}"}


def boot_ci(diff, n=4000, seed=0):
    """diff: array [seeds, days]. Two-level bootstrap of the mean."""
    rng = np.random.default_rng(seed)
    s, d = diff.shape
    means = np.empty(n)
    for b in range(n):
        si = rng.integers(0, s, s)
        di = rng.integers(0, d, d)
        means[b] = diff[np.ix_(si, di)].mean()
    return float(diff.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/agent_e_v2_stats")
    ap.add_argument("--conditions", nargs="*", default=list(CONDITIONS))
    ap.add_argument("--only", nargs="*", default=None, help="only these policy names (e.g. guarded_ppo)")
    a = ap.parse_args()
    torch.set_num_threads(1)
    runs = {f: [load_run(Path("results/runs") / pat.format(s)) for s in range(3)] for f, pat in FAMILIES.items()}
    res = {}
    for cname in a.conditions:
        env = make_env("intake", overrides=CONDITIONS[cname], scenarios=SPLITS["test"]["scenarios"])
        ref_p = Forecast(0.0)
        ref = evaluate(lambda e, o, m: ref_p.act(e, o, m), "test", env)
        pols = {"erlang_c(0.95)": [lambda e, o, m, p=ErlangC(0.95): p.act(e, o, m)]}
        for f, rs in runs.items():
            pols[f] = [lambda e, o, m, ag=ag: ag.act(o, m, explore=False) for _, ag in rs]
            pols["guarded_" + f] = [guarded(ag, Forecast(0.0)) for _, ag in rs]
        if a.only:
            pols = {k: v for k, v in pols.items() if k in a.only}
        res[cname] = {"forecast_mean": {k: float(np.mean([r[k] for r in ref])) for k in KPIS}, "policies": {}}
        print(f"== {cname}: Forecast ret {res[cname]['forecast_mean']['ret']:.2f}")
        for name, fns in pols.items():
            rows = [evaluate(fn, "test", env) for fn in fns]
            out = {}
            for k in KPIS:
                diff = np.array([[r[k] - q[k] for r, q in zip(rr, ref)] for rr in rows])
                m, lo, hi = boot_ci(diff)
                out[k] = {"mean_diff": m, "ci95": [lo, hi], "significant": bool(lo > 0 or hi < 0)}
            wins = np.array([[r["ret"] > q["ret"] for r, q in zip(rr, ref)] for rr in rows])
            out["win_rate_ret"] = float(wins.mean())
            out["n_seeds"], out["n_days"] = len(rows), len(ref)
            res[cname]["policies"][name] = out
            r_, s_ = out["ret"], out["sla_pct"]
            print(f"  {name:22s} dRet {r_['mean_diff']:+6.2f} [{r_['ci95'][0]:+.2f},{r_['ci95'][1]:+.2f}]  "
                  f"dSLA {s_['mean_diff']:+5.2f} [{s_['ci95'][0]:+.2f},{s_['ci95'][1]:+.2f}]  "
                  f"dCost {out['cost']['mean_diff']:+6.1f}  win {out['win_rate_ret']:.2f}", flush=True)
        out_dir = Path(a.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "paired_stats.json").write_text(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
