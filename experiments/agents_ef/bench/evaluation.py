"""Shared evaluation: the SAME scenario seeds, the SAME KPIs and the SAME code for every Agent E policy."""

import json
from pathlib import Path

import numpy as np

from env.callcenter_env import CallCenterEnv

SPLITS = json.loads((Path(__file__).resolve().parent.parent / "configs" / "splits.json").read_text())
KPI_KEYS = ["ret", "handled_pct", "abandon_pct", "sla_pct", "urgent_sla_pct", "mean_wait_min", "p95_wait_min",
            "sim_csat", "cost", "violations", "fallback_share", "end_backlog"]


def split_days(name: str):
    """[(seed, scenario)] of a split. TRAIN draws random seeds instead (see train.py)."""
    sp = SPLITS[name]
    days = []
    for k, sc in enumerate(sp["scenarios"]):
        for i in range(sp["seeds_per_scenario"]):
            days.append((sp["seed_start"] + 100 * k + i, sc))
    return days


def run_day(env: CallCenterEnv, policy, seed: int, scenario: str, decision_times=None) -> dict:
    """policy(env, obs, mask) -> action. Returns the day's KPIs + return."""
    import time
    obs, info = env.reset(seed=seed, scenario=scenario)
    ret, done = 0.0, False
    while not done:
        t0 = time.perf_counter()
        a = policy(env, obs, info["action_mask"])
        if decision_times is not None:
            decision_times.append(time.perf_counter() - t0)
        obs, r, done, _, info = env.step(a)
        ret += r
    k = env.episode_kpis()
    k["ret"] = ret
    return k


def evaluate(policy, split: str, env=None, decision_times=None) -> list[dict]:
    env = env or CallCenterEnv(scenarios=SPLITS[split]["scenarios"])
    return [run_day(env, policy, s, sc, decision_times) for s, sc in split_days(split)]


def summarize(rows: list[dict]) -> dict:
    out = {k: float(np.mean([r[k] for r in rows])) for k in KPI_KEYS}
    out["budget_ok_pct"] = 100.0 * np.mean([r["budget_ok"] for r in rows])
    return out
