"""Train one Agent E v5 policy: V3 tiny DQN family + PER / n-step / domain randomisation / flip cost / QR-DQN.

    python -m v5.e.train_v5 --algo dueling_dqn --seed 0 [--per] [--nstep 3] [--dr] [--flip-cost 0.06] [--nquant 21]

Everything not listed is IDENTICAL to v3/e/train_v3.py (same 150k-step budget, same 64x64 network, same
hyper-parameters, same TRAIN-day stream rng(1_000_000 + seed), same V3 VAL manifest (48 days) and the same
checkpoint rule: best.pt = highest VAL return of the 10 evaluations). With no option set this reproduces V3
exactly (NOTEBOOK: identical VAL return at 15k steps).
  --per          proportional prioritized replay (agents5.DQN5), alpha 0.6, beta 0.4 -> 1 over the budget.
  --nstep n      n-step returns with terminal truncation at day end.
  --dr           domain randomisation: every TRAIN day gets a shift drawn from configs/dr_ranges.json train_ranges.
                 VAL stays the nominal V3 VAL (the same selection rule for every arm).
  --flip-cost c  TRAINING-ONLY shaping (E7): reward - c when the agent activates within 2 steps after it
                 deactivated (or the reverse). The logged / selected / evaluated return is always the unchanged
                 v3 reward.
Output v5/e/runs/<run_id>/{best.pt,last.pt,val_log.csv,train_log.csv,run.json}; registered in v5/registry.
Resumable: a run whose run.json says done is skipped. Checkpoints written atomically.
"""

import argparse
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

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
from env.callcenter_env import A_ACT, A_DEACT  # noqa: E402
from v3.e.scenarios_v3 import TRAIN_FAMILIES  # noqa: E402
from v4.e.common import QC  # noqa: E402
from v5.e.agents5 import make_agent5  # noqa: E402
from v5.e.common5 import DR, RUNS, EnvV5, load_manifest  # noqa: E402
from v5.registry.registry import finish, register  # noqa: E402


def atomic_save(obj, path: Path):
    tmp = path.with_suffix(path.suffix + ".tmp")
    torch.save(obj, tmp)
    os.replace(tmp, path)


def atomic_text(text: str, path: Path):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def evaluate(agent, env, days):
    """Greedy VAL evaluation: mean return, queue-C SLA %, HIGH SLA % (the latter two are logged only)."""
    rets, c_ok, c_n, h_ok, h_n = [], 0, 0, 0, 0
    for d in days:
        obs, info = env.reset(seed=d["seed"], family=d["family"])
        done, R = False, 0.0
        while not done:
            obs, r, done, _, info = env.step(agent.act(obs, info["action_mask"], explore=False))
            R += r
        rets.append(R)
        st, q, rank = env.status, env.tape["q"], env.tape["rank"]
        c_ok += int(((q == QC) & (st == 1)).sum())
        c_n += int((q == QC).sum())
        h_ok += int(((rank == 2) & (st == 1)).sum())
        h_n += int((rank == 2).sum())
    return float(np.mean(rets)), 100.0 * c_ok / max(c_n, 1), 100.0 * h_ok / max(h_n, 1)


def run_name(a) -> str:
    parts = [a.algo, f"h{a.hidden.replace(',', 'x')}", f"{a.steps // 1000}k"]
    if a.per:
        parts.append("per")
    if a.nstep > 1:
        parts.append(f"n{a.nstep}")
    if a.dr:
        parts.append("dr")
    if a.flip_cost:
        parts.append(f"flip{a.flip_cost:g}")
    if a.algo.startswith("qr_"):
        parts.append(f"q{a.nquant}")
    return "_".join(parts) + f"_s{a.seed}" + a.tag


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--algo", required=True, choices=["dqn", "double_dqn", "dueling_dqn", "dueling_double_dqn",
                                                     "qr_dqn", "qr_double_dqn"])
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--steps", type=int, default=150_000)
    p.add_argument("--hidden", default="64,64")
    p.add_argument("--eval-every", type=int, default=15_000)
    p.add_argument("--per", action="store_true")
    p.add_argument("--alpha", type=float, default=0.6)
    p.add_argument("--beta0", type=float, default=0.4)
    p.add_argument("--nstep", type=int, default=1)
    p.add_argument("--dr", action="store_true")
    p.add_argument("--flip-cost", type=float, default=0.0)
    p.add_argument("--nquant", type=int, default=21)
    p.add_argument("--tag", default="")
    p.add_argument("--note", default="")
    a = p.parse_args(argv)
    torch.set_num_threads(1)
    hidden = tuple(int(h) for h in a.hidden.split(","))
    run_id = run_name(a)
    out = RUNS / run_id
    if (out / "run.json").exists() and json.loads((out / "run.json").read_text()).get("status") == "done":
        print("skip (done):", run_id)
        return
    out.mkdir(parents=True, exist_ok=True)
    env = EnvV5(None, TRAIN_FAMILIES, dr_ranges=DR["train_ranges"] if a.dr else None)
    val_env = EnvV5(None, TRAIN_FAMILIES)
    val_days = load_manifest("val")
    kw = dict(prioritized=a.per, alpha=a.alpha, beta0=a.beta0, beta_steps=a.steps, n_step=a.nstep)
    if a.algo.startswith("qr_"):
        kw["n_quant"] = a.nquant
    agent = make_agent5(a.algo, env.obs_dim, env.n_actions, a.seed, hidden=hidden, **kw)
    rng = np.random.default_rng(1_000_000 + a.seed)          # SAME training-day stream as V3 for the same seed
    cfg = {"algo": a.algo, "steps": a.steps, "hidden": list(hidden), "per": a.per, "alpha": a.alpha, "beta0": a.beta0,
           "nstep": a.nstep, "dr": a.dr, "flip_cost": a.flip_cost, "n_quant": a.nquant if a.algo.startswith("qr_") else None,
           "lr": 5e-4, "gamma": 0.97, "buffer": 100_000, "batch": 128, "train_every": 4, "target_every": 2000,
           "eps": "1.0->0.05 over 60k", "learning_starts": 5000, "selection": "best V3 VAL return (48 days)"}
    rid = register("E", run_id, cfg, seed=a.seed, dataset={"name": "v3 VAL manifest (selection)",
                                                            "train": "TRAIN families, seeds 0..199999"}, note=a.note)
    meta = {"run_id": run_id, **cfg, "seed": a.seed, "train_families": TRAIN_FAMILIES, "status": "running",
            "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "n_params": agent.n_params(), "torch": torch.__version__,
            "python": sys.version.split()[0], "hardware": platform.platform()}
    atomic_text(json.dumps(meta, indent=2), out / "run.json")
    train_log, val_log, best, steps, ep, t0 = [], [], -1e9, 0, 0, time.perf_counter()
    try:
        while steps < a.steps:
            obs, info = env.reset(seed=int(rng.integers(0, 200_000)))
            mask, done, R, flips, last_cap = info["action_mask"], False, 0.0, 0, (None, -99)
            while not done:
                act = agent.act(obs, mask, explore=True)
                t_now = env.t
                obs2, r, done, _, info = env.step(act)
                r_train = r
                if act in (A_ACT, A_DEACT):
                    if last_cap[0] is not None and last_cap[0] != act and t_now - last_cap[1] <= 2:
                        flips += 1
                        r_train = r - a.flip_cost
                    last_cap = (act, t_now)
                agent.observe(obs, act, r_train, obs2, done, info["action_mask"], mask=mask)
                obs, mask, R = obs2, info["action_mask"], R + r
                steps += 1
                if steps % a.eval_every == 0:
                    v, c_sla, hi = evaluate(agent, val_env, val_days)
                    val_log.append({"step": steps, "val_return": round(v, 4), "val_c_sla": round(c_sla, 3),
                                    "val_high_sla": round(hi, 3), "wall_s": round(time.perf_counter() - t0, 1)})
                    if v > best:
                        best = v
                        atomic_save(agent.state_dict(), out / "best.pt")
                        meta.update(best_step=steps, best_val_return=v, best_val_c_sla=c_sla)
            ep += 1
            train_log.append({"episode": ep, "step": steps, "return": round(R, 4), "flips": flips,
                              "family": env.spec.family})
        atomic_save(agent.state_dict(), out / "last.pt")
        for name, rows in (("train_log.csv", train_log), ("val_log.csv", val_log)):
            with open(out / name, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
        meta.update(status="done", ended=time.strftime("%Y-%m-%dT%H:%M:%S"), steps=steps, episodes=ep,
                    train_wall_s=round(time.perf_counter() - t0, 1),
                    peak_rss_mb=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1))
    except BaseException as e:                                # recorded, never silent (also SIGINT / kill)
        meta.update(status="failed", failure=repr(e)[:500], ended=time.strftime("%Y-%m-%dT%H:%M:%S"))
        finish(rid, "failed" if not isinstance(e, KeyboardInterrupt) else "stopped", reason=repr(e)[:300],
               duration_s=round(time.perf_counter() - t0, 1))
        raise
    finally:
        atomic_text(json.dumps(meta, indent=2), out / "run.json")
    finish(rid, "completed", results={"best_val_return": meta.get("best_val_return"), "best_step": meta.get("best_step"),
                                      "best_val_c_sla": meta.get("best_val_c_sla")},
           checkpoint=str(out / "best.pt"), n_params=agent.n_params(), duration_s=meta["train_wall_s"])
    print(json.dumps({k: meta.get(k) for k in ("run_id", "status", "best_val_return", "best_step", "train_wall_s")}))


if __name__ == "__main__":
    main()
