"""Minimal Agent E v3 inference example: load a trained run and propose capacity actions for one simulated day.

    python -m v3.e.infer_example --run dueling_double_dqn_equal_h64x64_150k_s0 [--mode guarded|rl] [--family normal]
Agent E only PROPOSES (the Coordinator executes); the action mask is applied before the policy chooses.
Uses a VAL-style seed (not a locked TEST day). Prints the first proposals and the day's KPIs.
"""

import argparse
import json
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from baselines.heuristics import Forecast  # noqa: E402
from bench.guarded_e import guarded  # noqa: E402
from integration.agent_e_policy import action_name  # noqa: E402
from rl.agents import make_agent  # noqa: E402
from v3.e.env_v3 import EnvV3  # noqa: E402

E = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--mode", default="guarded", choices=["guarded", "rl"])
    ap.add_argument("--family", default="tracking_spike")
    ap.add_argument("--seed", type=int, default=500_123)
    a = ap.parse_args()
    info = json.loads((E / "runs" / a.run / "run.json").read_text())
    agent = make_agent(info["algo"], EnvV3.obs_dim, EnvV3.n_actions, info["seed"], hidden=tuple(info["hidden"]))
    agent.load_state_dict(torch.load(E / "runs" / a.run / "best.pt", map_location="cpu", weights_only=False))
    z = json.loads((E / "results" / "val_choice.json").read_text())["forecast_z"]
    policy = guarded(agent, Forecast(z)) if a.mode == "guarded" else (lambda e, o, m: agent.act(o, m, explore=False))
    env = EnvV3()
    obs, inf = env.reset(seed=a.seed, family=a.family)
    done, R, shown = False, 0.0, 0
    while not done:
        act = policy(env, obs, inf["action_mask"])
        if act != 0 and shown < 8:
            print(f"t={env.t:2d} waiting={[len(w) for w in env.queue]} sessions={env.alloc.tolist()} -> proposal:",
                  action_name(act))
            shown += 1
        obs, r, done, _, inf = env.step(act)
        R += r
    k = env.kpis()
    print(json.dumps({"return": round(R, 2), **{x: round(k[x], 2) if isinstance(k[x], float) else k[x]
                                                 for x in ("sla_pct", "sla_high_pct", "sla_queue_c_pct", "lost_pct", "cost",
                                                           "fallback_share", "high_on_fallback", "invalid_proposals")}},
                     indent=1))


if __name__ == "__main__":
    main()
