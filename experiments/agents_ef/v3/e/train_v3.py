"""Train one Agent E v3 policy (resumable, atomic writes, registered in the run manifest).

    python -m v3.e.train_v3 --algo dueling_double_dqn --seed 0 --steps 150000 [--weights equal] [--tag x]
TRAIN days: random seeds 0..199_999, random TRAIN family per day (held-out families never seen).
VAL: fixed manifest (6 days per TRAIN family = 48 days), greedy return every --eval-every steps; best.pt = best VAL
return (TEST is never touched here). Output: v3/e/runs/<run_id>/{best.pt,last.pt,val_log.csv,train_log.csv,run.json}
(checkpoints are git-ignored). If run.json says status=done, the run is skipped (resume without duplication).
"""

import argparse
import csv
import json
import os
import platform
import resource
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
from rl.agents import make_agent  # noqa: E402
from v3.e.env_v3 import WEIGHTS, ConfigV3, EnvV3  # noqa: E402
from v3.e.scenarios_v3 import TRAIN_FAMILIES, manifest  # noqa: E402

RUNS = Path(__file__).resolve().parent / "runs"
REGISTRY = Path(__file__).resolve().parent / "results" / "run_registry.jsonl"


def atomic_save(obj, path: Path):
    tmp = path.with_suffix(path.suffix + ".tmp")
    torch.save(obj, tmp)
    os.replace(tmp, path)


def atomic_text(text: str, path: Path):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def evaluate(agent_or_policy, env, days, greedy_agent=True):
    rets = []
    for d in days:
        obs, info = env.reset(seed=d["seed"], family=d["family"])
        done, R = False, 0.0
        while not done:
            a = agent_or_policy.act(obs, info["action_mask"], explore=False) if greedy_agent else \
                agent_or_policy(env, obs, info["action_mask"])
            obs, r, done, _, info = env.step(a)
            R += r
        rets.append(R)
    return float(np.mean(rets))


def make_cfg(weights: str, **kw):
    ws, wa, wc = WEIGHTS[weights]
    return ConfigV3(w_sla=ws, w_ab=wa, w_cost=wc, **kw)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--algo", required=True)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--steps", type=int, default=150_000)
    p.add_argument("--hidden", default="64,64")
    p.add_argument("--weights", default="equal", choices=list(WEIGHTS))
    p.add_argument("--eval-every", type=int, default=15_000)
    p.add_argument("--val-days", type=int, default=6)
    p.add_argument("--tag", default="")
    p.add_argument("--w-csat", type=float, default=0.0, help="SYNTHETIC SIM-CSAT shortfall term (E+F experiment)")
    a = p.parse_args(argv)
    torch.set_num_threads(1)
    hidden = tuple(int(h) for h in a.hidden.split(","))
    tag = a.tag + (f"_csat{a.w_csat:g}" if a.w_csat else "")
    run_id = f"{a.algo}_{a.weights}_h{a.hidden.replace(',', 'x')}_{a.steps // 1000}k_s{a.seed}{tag}"
    out = RUNS / run_id
    if (out / "run.json").exists() and json.loads((out / "run.json").read_text()).get("status") == "done":
        print("skip (done):", run_id)
        return
    out.mkdir(parents=True, exist_ok=True)
    cfg = make_cfg(a.weights, w_csat=a.w_csat)
    env, val_env = EnvV3(cfg, TRAIN_FAMILIES), EnvV3(cfg, TRAIN_FAMILIES)
    val_days = manifest("val", a.val_days)
    agent = make_agent(a.algo, env.obs_dim, env.n_actions, a.seed, hidden=hidden)
    rng = np.random.default_rng(1_000_000 + a.seed)
    meta = {"run_id": run_id, "algo": a.algo, "seed": a.seed, "steps_budget": a.steps, "hidden": list(hidden),
            "weights": a.weights, "reward": {"w_sla": cfg.w_sla, "w_ab": cfg.w_ab, "w_cost": cfg.w_cost,
                                                   "w_csat_synthetic": cfg.w_csat},
            "train_families": TRAIN_FAMILIES, "val_manifest_days": len(val_days), "status": "running",
            "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "n_params": agent.n_params(),
            "code_revision": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=HERE, capture_output=True,
                                            text=True).stdout.strip(),
            "torch": torch.__version__, "python": sys.version.split()[0], "hardware": platform.platform()}
    atomic_text(json.dumps(meta, indent=2), out / "run.json")
    train_log, val_log, best, steps, ep, t0 = [], [], -1e9, 0, 0, time.perf_counter()
    try:
        while steps < a.steps:
            day_seed = int(rng.integers(0, 200_000))
            obs, info = env.reset(seed=day_seed)
            mask, done, R = info["action_mask"], False, 0.0
            while not done:
                act = agent.act(obs, mask, explore=True)
                obs2, r, done, _, info = env.step(act)
                agent.observe(obs, act, r, obs2, done, info["action_mask"], mask=mask)
                obs, mask, R = obs2, info["action_mask"], R + r
                steps += 1
                if steps % a.eval_every == 0:
                    v = evaluate(agent, val_env, val_days)
                    val_log.append({"step": steps, "val_return": round(v, 4), "wall_s": round(time.perf_counter() - t0, 1)})
                    if v > best:
                        best = v
                        atomic_save(agent.state_dict(), out / "best.pt")
            ep += 1
            train_log.append({"episode": ep, "step": steps, "return": round(R, 4), "family": env.spec.family})
        atomic_save(agent.state_dict(), out / "last.pt")
        for name, rows in (("train_log.csv", train_log), ("val_log.csv", val_log)):
            with open(out / name, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
        meta.update(status="done", ended=time.strftime("%Y-%m-%dT%H:%M:%S"), steps=steps, episodes=ep,
                    best_val_return=best, train_wall_s=round(time.perf_counter() - t0, 1),
                    peak_rss_mb=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1))
    except Exception as e:                                   # recorded, never silent
        meta.update(status="failed", failure=repr(e)[:500], ended=time.strftime("%Y-%m-%dT%H:%M:%S"))
        raise
    finally:
        atomic_text(json.dumps(meta, indent=2), out / "run.json")
        REGISTRY.parent.mkdir(parents=True, exist_ok=True)
        with open(REGISTRY, "a") as f:
            f.write(json.dumps({k: meta.get(k) for k in ("run_id", "algo", "seed", "steps_budget", "weights", "status",
                                                          "started", "ended", "best_val_return", "train_wall_s",
                                                          "n_params", "code_revision", "failure")}) + "\n")
    print(json.dumps({k: meta.get(k) for k in ("run_id", "status", "best_val_return", "train_wall_s", "n_params")}))


if __name__ == "__main__":
    main()
