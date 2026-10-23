"""Guarded hybrid Agent E: the Forecast rule owns the CAPACITY LEVEL, the RL policy owns the FINE decisions.

    python -m bench.guarded_e --glob "*_intake_h64x64_s*_400k" --out results/agent_e_v2_guarded
Why: generalize_e.py showed RL policies lose to the forecast rule when the demand SHAPE changes (the rule
re-forecasts every step, the network extrapolates). In the hybrid, whenever the rule wants to activate or
deactivate a session, its action is taken (total staffing follows the forecast); otherwise the RL action is taken
(which queue gets the sessions, when to use the capped fallback). No retraining: existing VAL-chosen checkpoints.
Same TEST days, conditions and equal-cost comparison as generalize_e.py.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from baselines.heuristics import Forecast  # noqa: E402
from bench.benchmark_e import load_run  # noqa: E402
from bench.evaluation import SPLITS, evaluate, summarize  # noqa: E402
from bench.generalize_e import CONDITIONS, gap_stats, interp_gap  # noqa: E402
from env.callcenter_env import A_ACT, A_DEACT  # noqa: E402
from env.factory import make_env  # noqa: E402


def guarded(agent, rule):
    def policy(env, obs, mask):
        a_rule = rule.act(env, obs, mask)
        if a_rule in (A_ACT, A_DEACT):
            return a_rule
        a = agent.act(obs, mask, explore=False)
        return a if a not in (A_ACT, A_DEACT) else a_rule          # RL never changes the capacity level itself
    return policy


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", default="*_intake_h64x64_s*_400k")
    ap.add_argument("--z", type=float, default=0.0, help="Forecast z (0.0 = the value chosen on in-dist VAL)")
    ap.add_argument("--curves", default="results/agent_e_v2_general/generalization.json")
    ap.add_argument("--out", default="results/agent_e_v2_guarded")
    a = ap.parse_args()
    torch.set_num_threads(1)
    curves = json.loads(Path(a.curves).read_text())["conditions"]
    runs = [(d, *load_run(d)) for d in sorted(Path("results/runs").glob(a.glob)) if (d / "best.pt").exists()]
    res = {}
    for cname, ov in CONDITIONS.items():
        env = make_env("intake", overrides=ov, scenarios=SPLITS["test"]["scenarios"])
        groups = defaultdict(list)
        for d, info, agent in runs:
            s = summarize(evaluate(guarded(agent, Forecast(a.z)), "test", env))
            s["gap_vs_forecast"] = interp_gap(s, curves[cname]["heuristic_curves"]["forecast"])
            groups["guarded_" + re.sub(r"_s\d+", "", d.name)].append(s)
        res[cname] = {g: {"mean": {k: float(np.mean([x[k] for x in v])) for k in v[0] if isinstance(v[0][k], float)},
                          "std": {k: float(np.std([x[k] for x in v])) for k in v[0] if isinstance(v[0][k], float)},
                          "gap_vs_forecast": gap_stats(v, "gap_vs_forecast")} for g, v in groups.items()}
        fc = curves[cname]["heuristic_picked"]["forecast"]
        print(f"== {cname}  forecast(z=0) ret {fc['ret']:.2f} cost {fc['cost']:.0f} SLA {fc['sla_pct']:.2f}")
        for g, v in res[cname].items():
            m, gf = v["mean"], v["gap_vs_forecast"]
            print(f"  {g:44s} ret {m['ret']:7.2f}±{v['std']['ret']:.2f} cost {m['cost']:6.0f} SLA {m['sla_pct']:6.2f} "
                  f"ab {m['abandon_pct']:5.2f} csat {m['sim_csat']:.3f} fb {m['fallback_share']:.2f} | gap SLA "
                  f"{gf['sla_pct'][0] if gf['sla_pct'][0] is None else round(gf['sla_pct'][0], 2)} ab "
                  f"{gf['abandon_pct'][0] if gf['abandon_pct'][0] is None else round(gf['abandon_pct'][0], 2)}")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "guarded.json").write_text(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
