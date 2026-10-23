"""One complete Agent E decision + one learning step, with the REAL checkpoint and the REAL simulator.

    python -m bench.explain_decision --run results/runs/dueling_double_dqn_intake_h64x64_s0_400k --out results/agent_e_v2_explain
Shows: the 43 named inputs, the action mask, V(s) and A(s,a) of the dueling head, Q = V + A - mean(A), the masked
argmax, what the hybrid guard (Forecast owns capacity) does, the reward decomposition after env.step, and one
Double-DQN update on this transition (TD target, Huber loss, gradient step) with Q(s,a) before/after.
The target network of a finished run is not saved (it is a periodic copy of the online net), so the example uses
target = a copy of the online net, i.e. the state right after a target sync.
"""

import argparse
import copy
import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from baselines.heuristics import Forecast  # noqa: E402
from bench.benchmark_e import load_run  # noqa: E402
from env.callcenter_env import N_ACTIONS, QUEUES  # noqa: E402
from env.factory import make_env  # noqa: E402
from integration.agent_e_policy import action_name  # noqa: E402

PER_Q = ["arrivals_last_step/10", "backlog/50", "mean_wait/SLA", "p90_wait/SLA", "sessions/24",
         "utilisation=EWMA*service/(5min*sessions)"]
GLOBAL = ["active_sessions/24", "available_capacity/24", "fallback_on", "budget_left_share", "sin(2*pi*t)",
          "cos(2*pi*t)", "EWMA_total_arrivals/10"]
INTAKE = ["high_priority_waiting/20", "mean_priority_score_waiting", "oldest_high_wait/(0.3*SLA)"]


def obs_names():
    n = [f"{q[:1]}.{f}" for q in QUEUES for f in PER_Q] + GLOBAL
    return n + [f"{q[:1]}.{f}" for q in QUEUES for f in INTAKE]


def describe(a):
    d = action_name(int(a))
    return d["type"] + (f" {d['from']}->{d['to']}" if "from" in d else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="results/runs/dueling_double_dqn_intake_h64x64_s0_400k")
    ap.add_argument("--seed", type=int, default=30200)          # TEST day 30200 = first 'spike' day
    ap.add_argument("--scenario", default="spike")
    ap.add_argument("--min-step", type=int, default=30)
    ap.add_argument("--out", default="results/agent_e_v2_explain")
    a = ap.parse_args()
    torch.manual_seed(0)
    info, agent = load_run(Path(a.run))
    net = agent.q
    env = make_env("intake", scenarios=("normal", "high", "spike", "drift", "slowdown", "failure", "compound"))
    obs, inf = env.reset(seed=a.seed, scenario=a.scenario)
    rule = Forecast(0.0)
    while True:                          # walk the day with the RL policy until its first non-"keep" decision
        mask = inf["action_mask"]
        act = agent.act(obs, mask, explore=False)
        if env.t >= a.min_step and act != 0:
            break
        obs, _, _, _, inf = env.step(act)
    x = torch.as_tensor(obs).unsqueeze(0)
    with torch.no_grad():
        h = torch.tanh(net.body(x))
        v, adv = net.v(h)[0, 0].item(), net.a(h)[0].numpy()
        q = net(x)[0].numpy()
    rule_a = rule.act(env, obs, mask)
    hybrid_a = rule_a if rule_a in (15, 16) else (act if act not in (15, 16) else rule_a)
    state = {"t_step": env.t, "minute": env.t * env.cfg.step_min, "scenario": a.scenario,
             "inputs": {n: round(float(v_), 4) for n, v_ in zip(obs_names(), obs)},
             "sessions_per_queue": dict(zip(QUEUES, env.alloc.tolist())),
             "waiting_per_queue": dict(zip(QUEUES, [len(w) for w in env.waiting])),
             "high_priority_waiting": dict(zip(QUEUES, [int((r == 2).sum()) for r in env.wrank]))}
    table = [{"id": i, "action": describe(i), "valid": bool(mask[i]), "A": round(float(adv[i]), 4),
              "Q": round(float(q[i]), 4)} for i in range(N_ACTIONS)]
    obs2, r, done, _, inf2 = env.step(act)
    parts = inf2["reward_parts"]
    c = env.cfg
    # ---- one Double DQN learning step on this transition (s, a, r, s')
    online, target = copy.deepcopy(net), copy.deepcopy(net)
    opt = torch.optim.Adam(online.parameters(), lr=5e-4)
    o2 = torch.as_tensor(obs2).unsqueeze(0)
    m2 = torch.as_tensor(inf2["action_mask"]).unsqueeze(0)
    with torch.no_grad():
        a_star = online(o2).masked_fill(~m2, -1e9).argmax(1).item()          # online net CHOOSES
        q_next = target(o2)[0, a_star].item()                                 # target net EVALUATES
        y = r + agent.gamma * (1 - float(done)) * q_next
    q_sa = online(x)[0, act]
    loss = F.smooth_l1_loss(q_sa, torch.tensor(y))
    opt.zero_grad()
    loss.backward()
    grad_norm = float(torch.nn.utils.clip_grad_norm_(online.parameters(), 10.0))
    opt.step()
    with torch.no_grad():
        q_after = online(x)[0, act].item()
    res = {"checkpoint": a.run, "state": state, "V(s)": round(v, 4), "mean_A": round(float(adv.mean()), 4),
           "actions": table, "rl_action": {"id": int(act), "action": describe(act)},
           "forecast_rule_action": {"id": int(rule_a), "action": describe(rule_a)},
           "hybrid_action": {"id": int(hybrid_a), "action": describe(hybrid_a)},
           "reward": {"total": round(r, 4), "parts": {k: round(float(v_), 4) for k, v_ in parts.items()},
                      "weights": {"w_served": c.w_served, "w_abandon": c.w_abandon, "w_sla": c.w_sla,
                                  "w_cost": c.w_cost, "w_csat": c.w_csat},
                      "check": round(c.w_served * parts["served"] - c.w_abandon * parts["abandon"]
                                     - c.w_sla * parts["late"] - c.w_cost * parts["cost"] + c.w_csat * parts["csat"], 4)},
           "learning_step": {"a_star_next (online argmax)": describe(a_star), "Q_target(s',a*)": round(q_next, 4),
                             "gamma": agent.gamma, "TD_target_y": round(y, 4), "Q(s,a)_before": round(q_sa.item(), 4),
                             "TD_error": round(y - q_sa.item(), 4), "huber_loss": round(float(loss), 6),
                             "grad_norm": round(grad_norm, 4), "Q(s,a)_after_one_adam_step": round(q_after, 4)}}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "decision_example.json").write_text(json.dumps(res, indent=2))
    print(json.dumps({k: res[k] for k in ("V(s)", "rl_action", "forecast_rule_action", "hybrid_action", "reward",
                                          "learning_step")}, indent=1))
    print("valid actions:", [(t["id"], t["action"], t["Q"]) for t in table if t["valid"]])
    print("state:", state["t_step"], state["sessions_per_queue"], state["waiting_per_queue"], state["high_priority_waiting"])


if __name__ == "__main__":
    main()
