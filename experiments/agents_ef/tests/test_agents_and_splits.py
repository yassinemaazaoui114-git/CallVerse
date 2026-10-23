"""RL agents respect the action mask and reload identically; data splits never overlap (no leakage)."""

import json
from pathlib import Path

import numpy as np
import pytest
import torch

from agent_f.make_dataset import SPLIT_SEEDS
from bench.evaluation import SPLITS, split_days
from env.callcenter_env import CallCenterEnv
from rl.agents import make_agent

ALGOS = ["tabular_q", "dqn", "double_dqn", "dueling_double_dqn", "ppo"]


@pytest.mark.parametrize("algo", ALGOS)
def test_agent_never_picks_a_masked_action(algo):
    env = CallCenterEnv()
    agent = make_agent(algo, env.obs_dim, env.n_actions, seed=0)
    obs, info = env.reset(seed=1, scenario="failure")
    done = False
    while not done:
        mask = info["action_mask"]
        for explore in (True, False):
            assert mask[agent.act(obs, mask, explore=explore)]
        obs, _, done, _, info = env.step(agent.act(obs, mask, explore=False))
    assert env.episode_kpis()["violations"] == 0


@pytest.mark.parametrize("algo", ALGOS)
def test_checkpoint_round_trip_gives_same_decisions(algo, tmp_path):
    env = CallCenterEnv()
    a1 = make_agent(algo, env.obs_dim, env.n_actions, seed=3)
    if algo == "tabular_q":
        a1.q = np.random.default_rng(0).normal(size=a1.q.shape)
    torch.save(a1.state_dict(), tmp_path / "x.pt")
    a2 = make_agent(algo, env.obs_dim, env.n_actions, seed=4)
    a2.load_state_dict(torch.load(tmp_path / "x.pt", weights_only=False))
    obs, info = env.reset(seed=2, scenario="spike")
    for _ in range(30):
        mask = info["action_mask"]
        assert a1.act(obs, mask, explore=False) == a2.act(obs, mask, explore=False)
        obs, _, _, _, info = env.step(a1.act(obs, mask, explore=False))


def test_agent_e_splits_do_not_overlap():
    lo, hi = SPLITS["train"]["seed_range"]
    val, test = {s for s, _ in split_days("val")}, {s for s, _ in split_days("test")}
    assert not val & test
    assert all(not (lo <= s <= hi) for s in val | test)
    assert "compound" in SPLITS["test"]["scenarios"] and "compound" not in SPLITS["train"]["scenarios"]


def test_agent_f_days_never_reuse_agent_e_days():
    f_days = {split: set(range(first, first + n)) for split, (first, n) in SPLIT_SEEDS.items()}
    assert not (f_days["train"] & f_days["val"]) and not (f_days["train"] & f_days["test"])
    lo, hi = SPLITS["train"]["seed_range"]
    e_eval = {s for s, _ in split_days("val")} | {s for s, _ in split_days("test")}
    for days in f_days.values():
        assert not days & e_eval and all(not (lo <= s <= hi) for s in days)


def test_agent_f_template_pools_are_disjoint():
    from agent_f.make_dataset import AGENT_CLOSING, LAST_MESSAGE, OPENINGS, split_pool
    for pools in (OPENINGS, AGENT_CLOSING, LAST_MESSAGE):
        for pool in pools.values():
            tr, va, te = (set(split_pool(pool, s)) for s in ("train", "val", "test"))
            assert not (tr & va) and not (tr & te) and not (va & te) and te


def test_agent_f_dataset_is_labelled_simulated():
    data = Path(__file__).resolve().parent.parent / "results" / "agent_f_data" / "test.jsonl"
    if not data.exists():
        pytest.skip("dataset not generated (python -m agent_f.make_dataset)")
    rows = [json.loads(line) for line in open(data)]
    assert all(r["source"] == "simulated" and 1 <= r["csat"] <= 5 for r in rows)
