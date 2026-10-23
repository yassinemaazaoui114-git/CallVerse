"""WHY does pure RL fail on unfamiliar traffic? Three measured diagnostics (Dueling DDQN 400k, 3 seeds, TEST days).

    python -m bench.diagnose_e --out results/agent_e_v2_diagnose
1. Staffing vs demand by hour: mean active sessions and mean offered load (sum_q EWMA_q * service_q / 5 min,
   the sessions the forecast says are needed) per hour of the simulated day, for RL and the Forecast rule.
   Ratio = active / offered load. A policy that tracks demand keeps the ratio flat when the shape changes.
2. Clock ablation: obs[28], obs[29] = sin/cos(2 pi t) are the only time-of-day inputs. Replace them by 0 (their
   mean over the day) and re-run. If return rises on the shifted shapes, the policy was relying on the clock.
3. Out-of-distribution states: Mahalanobis distance of each state to the in-distribution state cloud (RL's own
   in_dist trajectories); share of states above the in_dist 99th percentile.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from baselines.heuristics import Forecast  # noqa: E402
from bench.benchmark_e import load_run  # noqa: E402
from bench.evaluation import split_days  # noqa: E402
from bench.generalize_e import CONDITIONS  # noqa: E402
from env.factory import make_env  # noqa: E402
from bench.evaluation import SPLITS  # noqa: E402

TIME_IDX = (28, 29)


def run_days(env, policy, days, ablate_clock=False):
    """-> per-step records (hour, active, offered_load), states, returns."""
    recs, states, rets = [], [], []
    for seed, sc in days:
        obs, info = env.reset(seed=seed, scenario=sc)
        done, ret = False, 0.0
        while not done:
            o = obs.copy()
            if ablate_clock:
                o[list(TIME_IDX)] = 0.0
            states.append(obs.copy())
            a = policy(env, o, info["action_mask"])
            c = env.cfg
            offered = float((env.ewma * env.svc / c.step_min).sum())
            recs.append((int(env.t * 8 / c.steps_per_day), float(env.alloc.sum()), offered))
            obs, r, done, _, info = env.step(a)
            ret += r
        rets.append(ret)
    return np.array(recs), np.array(states), np.array(rets)


def by_hour(recs):
    out = []
    for h in range(8):
        m = recs[:, 0] == h
        out.append({"hour": h, "active": float(recs[m, 1].mean()), "offered": float(recs[m, 2].mean()),
                    "ratio": float(recs[m, 1].mean() / max(recs[m, 2].mean(), 1e-6))})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/agent_e_v2_diagnose")
    ap.add_argument("--glob", default="dueling_double_dqn_intake_h64x64_s{}_400k")
    a = ap.parse_args()
    torch.set_num_threads(1)
    agents = [load_run(Path("results/runs") / a.glob.format(s))[1] for s in range(3)]
    days = split_days("test")
    rl = lambda ag: (lambda e, o, m: ag.act(o, m, explore=False))
    fc = Forecast(0.0)
    res = {"conditions": {}}
    ref_states = None
    for cname, ov in CONDITIONS.items():
        env = make_env("intake", overrides=ov, scenarios=SPLITS["test"]["scenarios"])
        recs_f, _, rets_f = run_days(env, lambda e, o, m: fc.act(e, o, m), days)
        rows, rets, rets_abl, states_all = [], [], [], []
        for ag in agents:
            recs, states, r = run_days(env, rl(ag), days)
            _, _, r_abl = run_days(env, rl(ag), days, ablate_clock=True)
            rows.append(recs)
            states_all.append(states)
            rets.append(r)
            rets_abl.append(r_abl)
        recs = np.concatenate(rows)
        states = np.concatenate(states_all)
        if cname == "in_dist":
            ref_states = states
            mu = ref_states.mean(0)
            cov = np.cov(ref_states.T) + 1e-4 * np.eye(ref_states.shape[1])
            icov = np.linalg.inv(cov)
            dist = lambda X: np.sqrt(np.einsum("ij,jk,ik->i", X - mu, icov, X - mu))
            thr = float(np.percentile(dist(ref_states), 99))
        d = dist(states)
        rets, rets_abl = np.array(rets), np.array(rets_abl)
        res["conditions"][cname] = {
            "forecast_by_hour": by_hour(recs_f), "rl_by_hour": by_hour(recs),
            "corr_active_vs_offered": {"rl": float(np.corrcoef(recs[:, 1], recs[:, 2])[0, 1]),
                                       "forecast": float(np.corrcoef(recs_f[:, 1], recs_f[:, 2])[0, 1])},
            "return": {"forecast": float(rets_f.mean()), "rl": float(rets.mean()), "rl_clock_ablated": float(rets_abl.mean()),
                       "clock_ablation_delta": float((rets_abl - rets).mean()),
                       "clock_ablation_delta_per_seed": [float(x) for x in (rets_abl - rets).mean(1)]},
            "ood_share_above_in_dist_p99": float((d > thr).mean()), "mahalanobis_median": float(np.median(d))}
        c = res["conditions"][cname]
        print(f"== {cname}: ret forecast {c['return']['forecast']:.2f} rl {c['return']['rl']:.2f} "
              f"rl_no_clock {c['return']['rl_clock_ablated']:.2f} (delta {c['return']['clock_ablation_delta']:+.2f}) | "
              f"corr(active, load) rl {c['corr_active_vs_offered']['rl']:.2f} forecast "
              f"{c['corr_active_vs_offered']['forecast']:.2f} | OOD {c['ood_share_above_in_dist_p99']:.3f}", flush=True)
        print("   ratio active/load by hour  RL:", [round(x["ratio"], 2) for x in c["rl_by_hour"]],
              " Forecast:", [round(x["ratio"], 2) for x in c["forecast_by_hour"]], flush=True)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "diagnose.json").write_text(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
