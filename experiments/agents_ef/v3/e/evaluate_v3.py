"""Evaluate Agent E v3 policies on a fixed manifest -> one CSV of per-day KPIs per policy (resumable).

    python -m v3.e.evaluate_v3 --split test --policies rule:forecast:0 rl:<run_id> guarded:<run_id> ... --workers 2
Policy specs:
  rule:fixed | rule:threshold | rule:priority | rule:random_valid
  rule:forecast:<z> | rule:erlang:<target> | rule:mpc:<k>
  rl:<run_id>        greedy RL policy, VAL-chosen best.pt of v3/e/runs/<run_id>
  guarded:<run_id>   hybrid: Forecast(z*) owns activate/deactivate, RL owns allocation + capped fallback
                     (z* = the Forecast z chosen on VAL, read from results/val_choice.json; default 0)
Every policy sees the SAME exogenous tape per day (EnvV3 + manifest seed), so rows are paired by day_id.
Writes v3/e/results/eval_<split>/<policy>.csv ; skipped if it exists with the full number of rows.
Test manifest integrity is checked against configs/test_manifest.sha256 before evaluating.
"""

import argparse
import csv
import hashlib
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
E = Path(__file__).resolve().parent

KPI = ["sla_pct", "sla_high_pct", "sla_medium_pct", "sla_low_pct", "sla_queue_c_pct", "abandon_pct",
       "unresolved_end_pct", "lost_pct", "fb_unresolved_pct", "mean_wait_min", "p95_wait_min", "cost", "budget_ok",
       "fallback_share", "fallback_ticket_share", "high_on_fallback", "invalid_proposals", "safety_interventions",
       "sim_csat", "arrived", "rho"]


def load_manifest(split):
    path = E / "configs" / f"{split}_manifest.json"
    body = path.read_text()
    want = (E / "configs" / f"{split}_manifest.sha256").read_text().strip()
    if hashlib.sha256(body.encode()).hexdigest() != want:
        raise SystemExit(f"{split} manifest changed (hash mismatch): refusing to evaluate")
    return json.loads(body)["days"]


def make_policy(spec):
    import torch
    from baselines.heuristics import ErlangC, Fixed, Forecast, Priority, Threshold
    from bench.guarded_e import guarded
    from rl.agents import make_agent
    from v3.e.baselines_v3 import FluidMPC, RandomValid
    from v3.e.env_v3 import EnvV3
    torch.set_num_threads(1)
    kind, _, arg = spec.partition(":")
    if kind == "rule":
        name, _, p = arg.partition(":")
        obj = {"fixed": Fixed, "threshold": Threshold, "priority": Priority}.get(name)
        if obj:
            o = obj()
        elif name == "random_valid":
            o = RandomValid(0)
        elif name == "forecast":
            o = Forecast(float(p))
        elif name == "erlang":
            o = ErlangC(float(p))
        elif name == "mpc":
            o = FluidMPC(6, float(p))
        else:
            raise ValueError(spec)
        return (lambda e, ob, m: o.act(e, ob, m)), {"n_params": 0}
    run = E / "runs" / arg
    info = json.loads((run / "run.json").read_text())
    if info.get("status") != "done":
        raise SystemExit(f"run not done: {arg}")
    ag = make_agent(info["algo"], EnvV3.obs_dim, EnvV3.n_actions, info["seed"], hidden=tuple(info["hidden"]))
    ag.load_state_dict(torch.load(run / "best.pt", map_location="cpu", weights_only=False))
    meta = {"n_params": info["n_params"], "ckpt_kb": round((run / "best.pt").stat().st_size / 1024, 1)}
    if kind == "rl":
        return (lambda e, ob, m: ag.act(ob, m, explore=False)), meta
    z = 0.0
    vc = E / "results" / "val_choice.json"
    if vc.exists():
        z = float(json.loads(vc.read_text()).get("forecast_z", 0.0))
    meta["guard_forecast_z"] = z
    return guarded(ag, Forecast(z)), meta


def eval_policy(args):
    spec, split, out_dir = args
    from v3.e.env_v3 import EnvV3
    out = Path(out_dir) / (spec.replace(":", "__") + ".csv")
    days = load_manifest(split)
    if out.exists() and sum(1 for _ in open(out)) == len(days) + 1:
        return spec, "skip"
    pol, meta = make_policy(spec)
    env = EnvV3()
    rows, lat = [], []
    t0 = time.perf_counter()
    for k, d in enumerate(days):
        obs, info = env.reset(seed=d["seed"], family=d["family"])
        done, R = False, 0.0
        while not done:
            t1 = time.perf_counter()
            a = pol(env, obs, info["action_mask"])
            if k < 3:
                lat.append(time.perf_counter() - t1)
            obs, r, done, _, info = env.step(a)
            R += r
        kp = env.kpis()
        rows.append({"policy": spec, "day_id": d["day_id"], "family": d["family"], "seed": d["seed"], "return": R,
                     **{x: kp[x] for x in KPI}})
    tmp = out.with_suffix(".tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    tmp.replace(out)
    meta.update(policy=spec, split=split, n_days=len(rows), eval_s=round(time.perf_counter() - t0, 1),
                decision_ms_p50=round(1e3 * float(np.median(lat)), 4), decision_ms_p95=round(1e3 * float(np.percentile(lat, 95)), 4))
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    return spec, f"done {meta['eval_s']}s"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="val", choices=["val", "test"])
    ap.add_argument("--policies", nargs="+", required=True)
    ap.add_argument("--workers", type=int, default=1)
    a = ap.parse_args(argv)
    out_dir = E / "results" / f"eval_{a.split}"
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs = [(p, a.split, str(out_dir)) for p in a.policies]
    if a.workers > 1:
        with ProcessPoolExecutor(a.workers) as ex:
            for spec, st in ex.map(eval_policy, jobs):
                print(spec, st, flush=True)
    else:
        for j in jobs:
            print(*eval_policy(j), flush=True)


if __name__ == "__main__":
    main()
