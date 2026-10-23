"""Agent E v2 generalisation: the same policies on TEST days under different demand patterns.

    python -m bench.generalize_e --env intake --glob "*_intake_h64x64_s*" --out results/agent_e_v2_general
Conditions (TEST seeds and scenarios of configs/splits.json, so days are comparable across conditions):
  in_dist      the training distribution (assumed two-peak shape)
  flat_real    Olist real demand shape (near flat)
  evening      back-loaded shape, never seen in any training pool
  volatile     day load x lognormal(sigma=0.43, Olist day-to-day CV)
  evening_vol  both
Heuristics: Forecast(z) and Erlang-C(target) SWEEPS (cost-service curves) + the setting chosen on in_dist VAL.
RL: every run matching --glob (VAL-chosen best.pt). For each condition the RL gap vs each heuristic curve is
measured AT EQUAL COST (interpolation), like bench/frontier_gap.py. Simulator results only.
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
from baselines.heuristics import ErlangC, Forecast  # noqa: E402
from bench.benchmark_e import load_run  # noqa: E402
from bench.evaluation import SPLITS, evaluate, summarize  # noqa: E402
from env.factory import make_env  # noqa: E402

CONDITIONS = {"in_dist": {}, "flat_real": {"hourly_profile": "flat"}, "evening": {"hourly_profile": "evening"},
              "volatile": {"load_sigma": 0.43}, "evening_vol": {"hourly_profile": "evening", "load_sigma": 0.43}}
Z = (-0.5, -0.25, 0.0, 0.25, 0.5, 1.0)
TARGETS = (0.6, 0.4, 0.3, 0.2, 0.1, 0.05)
KPIS = ["sla_pct", "urgent_sla_pct", "abandon_pct", "abandon_high_pct", "sim_csat"]


def interp_gap(r, curve):
    pts = sorted(curve.values(), key=lambda s: s["cost"])
    cost = [p["cost"] for p in pts]
    return {k: r[k] - float(np.interp(r["cost"], cost, [p[k] for p in pts])) for k in KPIS if k in r}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="intake")
    ap.add_argument("--glob", default="*_intake_h64x64_s*")
    ap.add_argument("--conditions", nargs="*", default=list(CONDITIONS))
    ap.add_argument("--out", default="results/agent_e_v2_general")
    a = ap.parse_args()
    torch.set_num_threads(1)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    # heuristic settings chosen on in-distribution VAL (what a team would tune on before deployment)
    val_env = make_env(a.env, scenarios=SPLITS["val"]["scenarios"])
    pick = {}
    for name, cls, grid in (("forecast", Forecast, Z), ("erlang_c", ErlangC, TARGETS)):
        scores = {g: summarize(evaluate(lambda e, o, m, p=cls(g): p.act(e, o, m), "val", val_env))["ret"] for g in grid}
        pick[name] = max(scores, key=scores.get)
    runs = [(d, *load_run(d)) for d in sorted(Path("results/runs").glob(a.glob)) if (d / "best.pt").exists()]

    res = {"picked_on_in_dist_val": pick, "conditions": {}}
    for cname in a.conditions:
        env = make_env(a.env, overrides=CONDITIONS[cname], scenarios=SPLITS["test"]["scenarios"])
        curves = {"forecast": {}, "erlang_c": {}}
        for g in Z:
            p = Forecast(g)
            curves["forecast"][str(g)] = summarize(evaluate(lambda e, o, m: p.act(e, o, m), "test", env))
        for g in TARGETS:
            p = ErlangC(g)
            curves["erlang_c"][str(g)] = summarize(evaluate(lambda e, o, m: p.act(e, o, m), "test", env))
        rl = defaultdict(list)
        for d, info, agent in runs:
            s = summarize(evaluate(lambda e, o, m: agent.act(o, m, explore=False), "test", env))
            group = re.sub(r"_s\d+", "", d.name)
            rl[group].append({"seed": info["seed"], **s,
                              "gap_vs_forecast": interp_gap(s, curves["forecast"]),
                              "gap_vs_erlang_c": interp_gap(s, curves["erlang_c"])})
        res["conditions"][cname] = {
            "heuristic_curves": curves,
            "heuristic_picked": {"forecast": curves["forecast"][str(pick["forecast"])],
                                 "erlang_c": curves["erlang_c"][str(pick["erlang_c"])]},
            "rl": {g: {"seeds": v,
                       "mean": {k: float(np.mean([x[k] for x in v])) for k in v[0] if isinstance(v[0][k], float)},
                       "std": {k: float(np.std([x[k] for x in v])) for k in v[0] if isinstance(v[0][k], float)},
                       "gap_vs_forecast": {k: [float(np.mean([x["gap_vs_forecast"][k] for x in v])),
                                               float(np.std([x["gap_vs_forecast"][k] for x in v]))]
                                           for k in v[0]["gap_vs_forecast"]},
                       "gap_vs_erlang_c": {k: [float(np.mean([x["gap_vs_erlang_c"][k] for x in v])),
                                               float(np.std([x["gap_vs_erlang_c"][k] for x in v]))]
                                           for k in v[0]["gap_vs_erlang_c"]}}
                   for g, v in rl.items()}}
        (out / "generalization.json").write_text(json.dumps(res, indent=2))
        c = res["conditions"][cname]
        print(f"== {cname}")
        for h, s in c["heuristic_picked"].items():
            print(f"  {h:34s} ret {s['ret']:7.2f} cost {s['cost']:6.0f} SLA {s['sla_pct']:6.2f} "
                  f"urg {s['urgent_sla_pct']:6.2f} ab {s['abandon_pct']:5.2f} csat {s['sim_csat']:.3f}")
        for g, v in c["rl"].items():
            m, sd = v["mean"], v["std"]
            ge = v["gap_vs_erlang_c"]
            print(f"  {g:34s} ret {m['ret']:7.2f}±{sd['ret']:.2f} cost {m['cost']:6.0f} SLA {m['sla_pct']:6.2f} "
                  f"urg {m['urgent_sla_pct']:6.2f} ab {m['abandon_pct']:5.2f} csat {m['sim_csat']:.3f} "
                  f"fb {m['fallback_share']:.2f} | vsErlang@cost SLA {ge['sla_pct'][0]:+.2f} ab {ge['abandon_pct'][0]:+.2f}")


if __name__ == "__main__":
    main()
