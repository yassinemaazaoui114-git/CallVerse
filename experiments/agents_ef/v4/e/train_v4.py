"""Train one Agent E v4 policy: the V3 tiny DQN family + two targeted, diagnosis-driven options.

    python -m v4.e.train_v4 --algo dueling_dqn --seed 0 [--shield 0.2] [--lam0 0 --dual-target 0.92 --dual-lr 2]

Options (each answers one question from the V3 failure analysis, see NOTEBOOK.md):
  --shield t        SHIELDED TRAINING: the urgent-capacity shield (common.UrgentShield, Erlang-C target t) is part
                    of the environment during training AND evaluation. The agent explores and bootstraps only over
                    shielded actions, so it learns what is best GIVEN the protection (instead of fighting it).
  --floor k         same, with a STATIC floor: queue C never below k sessions (a stronger version of the V3 mask).
  --lam0 / --dual-* CONSTRAINED OBJECTIVE (Lagrangian): training reward = v3 reward - lam * (queue-C failures)/F_ref.
                    lam is a Lagrange multiplier updated by dual ascent after every training day:
                        lam <- clip(lam + dual_lr * (dual_target - queue-C SLA of that day), 0, lam_max)
                    i.e. lam grows while queue C misses its pre-declared SLA target and shrinks when it is met.
                    The replay buffer stores the env reward and the C-failure count SEPARATELY, so every update
                    uses the CURRENT lam (no stale penalties). dual_lr = 0 gives a fixed-penalty run.
  --owner mpc|forecast  HIERARCHICAL TRAINING: a classical rule owns the capacity LEVEL (activate/deactivate),
                    the RL agent learns only allocation moves, keep and the capped fallback (its mask never contains
                    activate/deactivate). When the rule activates/deactivates, that transition is still stored (valid
                    off-policy data). Answers diagnosis H2 (RL dithers with activate/deactivate pairs).
  --dual-start N    no dual update before step N (lets epsilon-exploration finish; diagnosis of arm B).
Checkpoint selection on V3 VAL (48 days, never TEST): the env return is the unchanged v3 reward. To respect the
constraint, best.pt = highest VAL return among evaluations whose VAL queue-C SLA >= --sel-c-min (feasible first);
if no evaluation is feasible yet, the one with the highest queue-C SLA. Both criteria are logged.
Resumable: if run.json says done the run is skipped; checkpoints written atomically. Output: v4/e/runs/<run_id>/.
"""

import argparse
import copy
import csv
import json
import os
import platform
import resource
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
from rl.agents import DQN, NEG, make_agent  # noqa: E402
from v3.e.scenarios_v3 import TRAIN_FAMILIES  # noqa: E402
from v4.e.common import E4, QC, EnvV4, UrgentShield, load_manifest  # noqa: E402

RUNS = E4 / "runs"
REGISTRY = E4 / "results" / "run_registry.jsonl"


def atomic_save(obj, path: Path):
    tmp = path.with_suffix(path.suffix + ".tmp")
    torch.save(obj, tmp)
    os.replace(tmp, path)


def atomic_text(text: str, path: Path):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


class LagrangianDQN:
    """Wraps a v3 DQN-family agent: same network, buffer and update, but the reward used in each update is
    r_env - lam * c_cost (c_cost = queue-C failures / F_ref, stored per transition)."""

    def __init__(self, base: DQN):
        self.b = base
        self.c = np.zeros(base.cap, np.float32)
        self.lam = 0.0

    def act(self, obs, mask, explore=True):
        return self.b.act(obs, mask, explore)

    def observe(self, obs, a, r_env, obs2, done, mask2, c_cost):
        b = self.b
        self.c[b.ptr] = c_cost
        # replicate DQN.observe but call our update
        i = b.ptr
        b.o[i], b.a[i], b.r[i], b.o2[i], b.d[i], b.m2[i] = obs, a, r_env, obs2, float(done), mask2
        b.ptr, b.size = (i + 1) % b.cap, min(b.size + 1, b.cap)
        b.steps += 1
        if b.steps >= b.learning_starts and b.steps % b.train_every == 0:
            self._update()
        if b.steps % b.target_every == 0:
            b.q_target.load_state_dict(b.q.state_dict())

    def _update(self):
        b = self.b
        idx = b.rng.integers(0, b.size, b.batch)
        o, o2 = torch.as_tensor(b.o[idx]), torch.as_tensor(b.o2[idx])
        a, d = torch.as_tensor(b.a[idx]), torch.as_tensor(b.d[idx])
        r = torch.as_tensor(b.r[idx] - self.lam * self.c[idx])           # CURRENT multiplier
        m2 = torch.as_tensor(b.m2[idx])
        with torch.no_grad():
            q_next_t = b.q_target(o2).masked_fill(~m2, NEG)
            if b.double:
                a2 = b.q(o2).masked_fill(~m2, NEG).argmax(1, keepdim=True)
                q_next = q_next_t.gather(1, a2).squeeze(1)
            else:
                q_next = q_next_t.max(1).values
            target = r + b.gamma * (1 - d) * q_next
        q = b.q(o).gather(1, a.unsqueeze(1)).squeeze(1)
        loss = F.smooth_l1_loss(q, target)
        b.opt.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(b.q.parameters(), 10.0)
        b.opt.step()

    def state_dict(self):
        return self.b.state_dict()

    def n_params(self):
        return self.b.n_params()


def make_owner(name):
    if not name:
        return None
    from baselines.heuristics import Forecast
    from v3.e.baselines_v3 import FluidMPC
    return {"mpc": FluidMPC(6, 0.5), "forecast": Forecast(0.25)}[name]


def decide(agent, env, obs, m, owner, explore):
    """Returns (action executed, mask the agent saw)."""
    if owner is not None:
        from env.callcenter_env import A_ACT, A_DEACT
        a_rule = owner.act(env, obs, m)
        m_rl = m.copy()
        m_rl[A_ACT] = m_rl[A_DEACT] = False
        if a_rule in (A_ACT, A_DEACT) and m[a_rule]:
            return a_rule, m_rl
        return agent.act(obs, m_rl, explore=explore), m_rl
    return agent.act(obs, m, explore=explore), m


def evaluate(agent, env, days, shield, owner=None):
    rets, c_ok, c_n, high_ok, high_n = [], 0, 0, 0, 0
    for d in days:
        obs, info = env.reset(seed=d["seed"], family=d["family"])
        mask = info["action_mask"]
        done, R = False, 0.0
        while not done:
            m = shield.mask(env, mask)[0] if shield else mask
            obs, r, done, _, info = env.step(decide(agent, env, obs, m, owner, False)[0])
            mask = info["action_mask"]
            R += info["reward_env"]
        rets.append(R)
        st, q, rank = env.status, env.tape["q"], env.tape["rank"]
        c_ok += int(((q == QC) & (st == 1)).sum())
        c_n += int((q == QC).sum())
        high_ok += int(((rank == 2) & (st == 1)).sum())
        high_n += int((rank == 2).sum())
    return float(np.mean(rets)), 100.0 * c_ok / max(c_n, 1), 100.0 * high_ok / max(high_n, 1)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--algo", required=True, choices=["dqn", "double_dqn", "dueling_dqn", "dueling_double_dqn"])
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--steps", type=int, default=150_000)
    p.add_argument("--hidden", default="64,64")
    p.add_argument("--eval-every", type=int, default=15_000)
    p.add_argument("--shield", type=float, default=None)
    p.add_argument("--floor", type=int, default=None, help="static stronger mask: queue C never below k (trained in the loop)")
    p.add_argument("--lam0", type=float, default=0.0)
    p.add_argument("--dual-target", type=float, default=0.92)
    p.add_argument("--dual-lr", type=float, default=0.0)
    p.add_argument("--lam-max", type=float, default=10.0)
    p.add_argument("--sel-c-min", type=float, default=91.3, help="VAL queue-C SLA for feasibility (MPC VAL 92.28 - 1)")
    p.add_argument("--owner", default="", choices=["", "mpc", "forecast"])
    p.add_argument("--dual-start", type=int, default=0)
    p.add_argument("--tag", default="")
    a = p.parse_args(argv)
    torch.set_num_threads(1)
    hidden = tuple(int(h) for h in a.hidden.split(","))
    parts = [a.algo, f"h{a.hidden.replace(',', 'x')}", f"{a.steps // 1000}k"]
    if a.shield is not None:
        parts.append(f"sh{a.shield:g}")
    if a.floor is not None:
        parts.append(f"fl{a.floor}")
    if a.owner:
        parts.append(f"own{a.owner}")
    if a.lam0 or a.dual_lr:
        parts.append(f"lag{a.lam0:g}" + (f"d{a.dual_lr:g}t{a.dual_target:g}" if a.dual_lr else "")
                     + (f"w{a.dual_start // 1000}k" if a.dual_start else ""))
    run_id = "_".join(parts) + f"_s{a.seed}" + a.tag
    out = RUNS / run_id
    skip = E4 / "configs" / "skip_runs.txt"            # lets me drop queued runs without killing the queue
    if skip.exists() and run_id in skip.read_text().split():
        print("skip (descoped, see NOTEBOOK):", run_id)
        return
    if (out / "run.json").exists() and json.loads((out / "run.json").read_text()).get("status") == "done":
        print("skip (done):", run_id)
        return
    out.mkdir(parents=True, exist_ok=True)
    env, val_env = EnvV4(None, TRAIN_FAMILIES), EnvV4(None, TRAIN_FAMILIES)
    shield = UrgentShield(a.shield) if a.shield is not None else None
    if a.floor is not None:
        shield = UrgentShield(static=a.floor)
    owner = make_owner(a.owner)
    val_days = load_manifest("val")
    base = make_agent(a.algo, env.obs_dim, env.n_actions, a.seed, hidden=hidden)
    agent = LagrangianDQN(base)
    agent.lam = a.lam0
    rng = np.random.default_rng(1_000_000 + a.seed)          # SAME training-day stream as V3 for the same seed
    meta = {"run_id": run_id, "algo": a.algo, "seed": a.seed, "steps_budget": a.steps, "hidden": list(hidden),
            "weights": "equal", "shield_target": a.shield, "floor_c": a.floor, "lam0": a.lam0, "dual_lr": a.dual_lr,
            "dual_target": a.dual_target, "lam_max": a.lam_max, "owner": a.owner, "dual_start": a.dual_start, "sel_c_min": a.sel_c_min,
            "train_families": TRAIN_FAMILIES, "val_manifest_days": len(val_days), "status": "running",
            "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "n_params": agent.n_params(),
            "torch": torch.__version__, "python": sys.version.split()[0], "hardware": platform.platform()}
    atomic_text(json.dumps(meta, indent=2), out / "run.json")
    train_log, val_log, steps, ep, t0 = [], [], 0, 0, time.perf_counter()
    best_key = None
    try:
        while steps < a.steps:
            obs, info = env.reset(seed=int(rng.integers(0, 200_000)))
            mask = info["action_mask"]
            m = shield.mask(env, mask)[0] if shield else mask
            done, R = False, 0.0
            while not done:
                act, _ = decide(agent, env, obs, m, owner, True)
                obs2, r_env, done, _, info = env.step(act)
                mask2 = info["action_mask"]
                m2 = shield.mask(env, mask2)[0] if shield else mask2
                if owner is not None:                    # the agent never chooses the capacity level itself
                    from env.callcenter_env import A_ACT, A_DEACT
                    m2 = m2.copy()
                    m2[A_ACT] = m2[A_DEACT] = False
                c_cost = float(info["queue_fail"][QC]) / env.cfg.ref_fail_per_step
                agent.observe(obs, act, info["reward_env"], obs2, done, m2, c_cost)
                obs, m, R = obs2, m2, R + info["reward_env"]
                steps += 1
                if steps % a.eval_every == 0:
                    v, c_sla, hi = evaluate(agent, val_env, val_days, shield, owner)
                    feas = c_sla >= a.sel_c_min
                    key = (1, v) if feas else (0, c_sla)
                    val_log.append({"step": steps, "val_return": round(v, 4), "val_c_sla": round(c_sla, 3),
                                    "val_high_sla": round(hi, 3), "feasible": int(feas), "lam": round(agent.lam, 4),
                                    "wall_s": round(time.perf_counter() - t0, 1)})
                    if best_key is None or key > best_key:
                        best_key = key
                        atomic_save(agent.state_dict(), out / "best.pt")
                        meta.update(best_step=steps, best_val_return=v, best_val_c_sla=c_sla, best_feasible=bool(feas))
            c_n = int((env.tape["q"] == QC).sum())
            c_sla_ep = 1.0 - env.c_fail_day / max(c_n, 1)
            if a.dual_lr and steps >= a.dual_start:
                agent.lam = float(np.clip(agent.lam + a.dual_lr * (a.dual_target - c_sla_ep), 0.0, a.lam_max))
            ep += 1
            train_log.append({"episode": ep, "step": steps, "return": round(R, 4), "c_sla": round(c_sla_ep, 4),
                              "lam": round(agent.lam, 4), "family": env.spec.family})
        atomic_save(agent.state_dict(), out / "last.pt")
        for name, rows in (("train_log.csv", train_log), ("val_log.csv", val_log)):
            with open(out / name, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
        meta.update(status="done", ended=time.strftime("%Y-%m-%dT%H:%M:%S"), steps=steps, episodes=ep,
                    final_lam=agent.lam, train_wall_s=round(time.perf_counter() - t0, 1),
                    peak_rss_mb=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1))
    except Exception as e:
        meta.update(status="failed", failure=repr(e)[:500], ended=time.strftime("%Y-%m-%dT%H:%M:%S"))
        raise
    finally:
        atomic_text(json.dumps(meta, indent=2), out / "run.json")
        REGISTRY.parent.mkdir(parents=True, exist_ok=True)
        with open(REGISTRY, "a") as f:
            f.write(json.dumps({k: meta.get(k) for k in ("run_id", "status", "started", "ended", "best_val_return",
                                                          "best_val_c_sla", "best_feasible", "final_lam",
                                                          "train_wall_s", "n_params", "failure")}) + "\n")
    print(json.dumps({k: meta.get(k) for k in ("run_id", "status", "best_val_return", "best_val_c_sla", "final_lam",
                                                "train_wall_s")}))


if __name__ == "__main__":
    main()
