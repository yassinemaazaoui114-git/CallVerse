"""Stage 1 checks of the Agent E simulator: determinism, conservation, safety constraints, mask, reward parts."""

import numpy as np
import pytest

from env.callcenter_env import (A_ACT, A_DEACT, A_FB_ON, A_KEEP, MOVES, N_ACTIONS, SCENARIOS, CallCenterEnv,
                                EnvConfig)


def run(env, policy, seed, scenario):
    obs, info = env.reset(seed=seed, scenario=scenario)
    total, done, obs_list = 0.0, False, [obs]
    while not done:
        obs, r, done, _, info = env.step(policy(env, info["action_mask"]))
        total += r
        obs_list.append(obs)
    return total, env.episode_kpis(), obs_list


def random_valid(rng):
    return lambda env, mask: int(rng.choice(np.flatnonzero(mask)))


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_same_seed_same_day(scenario):
    env = CallCenterEnv()
    r1, k1, o1 = run(env, random_valid(np.random.default_rng(0)), 7, scenario)
    r2, k2, o2 = run(env, random_valid(np.random.default_rng(0)), 7, scenario)
    assert r1 == r2 and k1 == k2 and all(np.array_equal(a, b) for a, b in zip(o1, o2))


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_every_request_is_accounted_for(scenario):
    env = CallCenterEnv()
    run(env, random_valid(np.random.default_rng(1)), 3, scenario)
    k = env.kpi
    backlog = sum(len(w) for w in env.waiting)
    assert k["arrived"].sum() == k["served"].sum() + k["abandoned"].sum() + backlog


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_hard_constraints_hold_under_random_valid_actions(scenario):
    env = CallCenterEnv()
    rng = np.random.default_rng(2)
    obs, info = env.reset(seed=11, scenario=scenario)
    done = False
    while not done:
        obs, _, done, _, info = env.step(int(rng.choice(np.flatnonzero(info["action_mask"]))))
        assert (env.alloc >= 0).all()
        assert env.alloc[2] >= env.cfg.min_alloc_urgent           # urgent queue protected
        assert env.alloc.sum() <= env.available_capacity()        # capacity, also during failures
        assert env.spent <= env.budget + 1e-9                     # budget never exceeded
        assert obs.shape == (CallCenterEnv.obs_dim,) and np.isfinite(obs).all()
    assert env.episode_kpis()["violations"] == 0 and env.episode_kpis()["budget_ok"]


def test_invalid_action_becomes_keep_and_is_counted():
    env = CallCenterEnv()
    env.reset(seed=0, scenario="normal")
    env.alloc[:] = [5, 5, 2, 4]
    before = env.alloc.copy()
    urgent_out = MOVES.index((2, 0)) + 1                           # would drop urgent below its minimum
    env.step(urgent_out)
    assert env.alloc[2] == 2 and env.kpi["violations"] == 1
    env.step(99)                                                   # out of range
    assert env.kpi["violations"] == 2
    assert env.alloc.sum() == before.sum()


def test_fallback_never_applies_to_urgent_or_refund_queues():
    cfg = EnvConfig()
    assert cfg.fallback_eligible[1] is False and cfg.fallback_eligible[2] is False


def test_budget_blocks_activation():
    env = CallCenterEnv()
    env.reset(seed=0, scenario="normal")
    env.spent = env.budget - 1.0                                   # almost nothing left
    assert not env.action_mask()[A_ACT]


def test_failure_scenario_reduces_capacity_without_violation():
    env = CallCenterEnv()
    obs, info = env.reset(seed=5, scenario="failure")
    t0, t1 = env.sc.fail_t
    while env.t < t0 + 1:
        obs, _, _, _, info = env.step(A_ACT if info["action_mask"][A_ACT] else A_KEEP)
    assert env.alloc.sum() <= env.cfg.max_sessions - env.sc.fail_lost
    assert env.kpi["violations"] == 0


def test_reward_parts_are_finite_and_cost_is_charged():
    env = CallCenterEnv()
    obs, info = env.reset(seed=4, scenario="spike")
    _, r, _, _, info = env.step(A_FB_ON)
    parts = info["reward_parts"]
    assert np.isfinite(r) and all(np.isfinite(v) for v in parts.values())
    assert parts["cost"] > 0 and env.fallback


def test_observation_has_no_future_information():
    """Two days that are identical until step t but differ afterwards give identical observations up to t."""
    env = CallCenterEnv()
    _, _, o1 = run(env, lambda e, m: A_KEEP, 21, "spike")
    _, _, o2 = run(env, lambda e, m: A_KEEP if e.t < 30 else (A_DEACT if m[A_DEACT] else A_KEEP), 21, "spike")
    assert all(np.array_equal(a, b) for a, b in zip(o1[:31], o2[:31]))
    assert N_ACTIONS == 17
