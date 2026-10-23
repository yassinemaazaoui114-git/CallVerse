"""Train one tiny RL policy for Agent E.

    python -m rl.train --algo ppo --seed 0 --steps 150000 --preset balanced --out results/runs
(run from experiments/agents_ef). Training days: random seeds from the TRAIN range and TRAIN scenarios.
Every --eval-every steps the greedy policy is scored on the VALIDATION days; the best one is kept
(checkpoint chosen on VAL only, never on TEST). Writes <out>/<algo>_<preset>_s<seed>/: best.pt, last.pt,
train_log.csv, val_log.csv, run.json (hyper-parameters, timings, peak memory, parameter count).
"""

import argparse
import csv
import json
import os
import resource
import sys
import time
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bench.evaluation import SPLITS, evaluate, summarize  # noqa: E402
from rl.agents import make_agent  # noqa: E402


def greedy(agent):
    return lambda env, obs, mask: agent.act(obs, mask, explore=False)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--algo", required=True)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--steps", type=int, default=150_000)
    p.add_argument("--preset", default=None, help="reward preset (default: balanced for v1, intake for intake)")
    p.add_argument("--env", default="v1", choices=["v1", "intake"])
    p.add_argument("--overrides", default="{}", help='EnvConfig overrides as JSON, e.g. {"load_sigma": 0.43}')
    p.add_argument("--f-reward", default=None, help="Agent F reward model (agent_f/f_reward.py) instead of SIM-CSAT")
    p.add_argument("--hidden", default="64,64")
    p.add_argument("--eval-every", type=int, default=15_000)
    p.add_argument("--device", default="cpu")
    p.add_argument("--out", default="results/runs")
    p.add_argument("--tag", default="")
    p.add_argument("--calibration", default=None, help="e_calibration.json from real_data (queue mix)")
    args = p.parse_args()
    torch.set_num_threads(1)
    hidden = tuple(int(h) for h in args.hidden.split(","))

    from env.factory import make_env
    args.preset = args.preset or ("intake" if args.env == "intake" else "balanced")
    ov = json.loads(args.overrides)
    kw = {}
    if args.f_reward:
        from agent_f.f_reward import load_f_reward
        kw["f_reward"] = load_f_reward(args.f_reward)
    env = make_env(args.env, args.preset, args.calibration, ov, SPLITS["train"]["scenarios"], **kw)
    val_env = make_env(args.env, args.preset, args.calibration, ov, SPLITS["val"]["scenarios"], **kw)
    agent = make_agent(args.algo, env.obs_dim, env.n_actions, args.seed, hidden=hidden)
    run_dir = Path(args.out) / f"{args.algo}_{args.preset}_h{args.hidden.replace(',', 'x')}_s{args.seed}{args.tag}"
    run_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(10_000 + args.seed)
    lo, hi = SPLITS["train"]["seed_range"]
    train_log, val_log = [], []
    best = -1e9
    t0 = time.perf_counter()
    steps, ep = 0, 0
    while steps < args.steps:
        obs, info = env.reset(seed=int(rng.integers(lo, hi + 1)))
        mask, done, ret = info["action_mask"], False, 0.0
        while not done:
            a = agent.act(obs, mask, explore=True)
            obs2, r, done, _, info = env.step(a)
            agent.observe(obs, a, r, obs2, done, info["action_mask"], mask=mask)
            obs, mask, ret = obs2, info["action_mask"], ret + r
            steps += 1
            if steps % args.eval_every == 0:
                s = summarize(evaluate(greedy(agent), "val", val_env))
                val_log.append({"step": steps, "wall_s": round(time.perf_counter() - t0, 1), **s})
                if s["ret"] > best:
                    best = s["ret"]
                    torch.save(agent.state_dict(), run_dir / "best.pt")
        ep += 1
        train_log.append({"episode": ep, "step": steps, "return": round(ret, 3), "scenario": env.sc.kind})
    wall = time.perf_counter() - t0
    torch.save(agent.state_dict(), run_dir / "last.pt")
    for name, rows in (("train_log.csv", train_log), ("val_log.csv", val_log)):
        with open(run_dir / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    info = {"algo": args.algo, "seed": args.seed, "steps": steps, "episodes": ep, "preset": args.preset,
            "env": args.env, "overrides": ov, "calibration": args.calibration, "f_reward": args.f_reward,
            "tag": args.tag,
            "hidden": hidden, "train_wall_s": round(wall, 1), "steps_per_s": round(steps / wall, 1),
            "best_val_return": best, "n_params": agent.n_params(), "device": args.device,
            "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
            "torch": torch.__version__, "cpu_count": os.cpu_count()}
    (run_dir / "run.json").write_text(json.dumps(info, indent=2))
    print(json.dumps(info))


if __name__ == "__main__":
    main()
