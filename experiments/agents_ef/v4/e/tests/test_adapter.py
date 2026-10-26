"""Tests of the Agent E v4 adapter and urgent shield (run from experiments/agents_ef:  python -m pytest v4/e/tests).

They use REAL simulator states (EnvV3 days driven by a mix of policies) and a real V3 checkpoint.
"""

import copy
import time

import numpy as np
import pytest

from env.callcenter_env import A_ACT, A_DEACT, A_FB_ON, A_KEEP, MOVES, N_ACTIONS
from v3.e.env_v3 import EnvV3
from v4.e.adapter import AgentEAdapter, SnapshotViewV3, snapshot_from_env
from v4.e.common import QC, EnvV4, UrgentShield, alloc_after

RUN = "dueling_double_dqn_equal_h64x64_150k_s0"          # a frozen V3 checkpoint (always present)


def states(fams=("normal", "failure", "severe_overload", "high_priority_surge", "combined_shock"), every=7, seed0=4242):
    """Yield live env states along days driven by a seeded random-valid policy (covers fallback on, failures, etc.)."""
    rng = np.random.default_rng(0)
    for k, fam in enumerate(fams):
        env = EnvV3()
        obs, info = env.reset(seed=seed0 + k, family=fam)
        done = False
        while not done:
            if env.t % every == 0:
                yield env, obs, info["action_mask"]
            a = int(rng.choice(np.flatnonzero(info["action_mask"])))
            obs, _, done, _, info = env.step(a)


def test_obs_and_mask_equivalence_on_real_states():
    n = 0
    for env, obs, mask in states():
        snap = snapshot_from_env(env)
        v = SnapshotViewV3(snap)
        np.testing.assert_allclose(v._obs(), obs, atol=1e-5)
        assert (v.action_mask() == mask).all()
        np.testing.assert_allclose(v._load(), env._load(), atol=1e-9)
        n += 1
    assert n > 50


def test_adapter_never_mutates_snapshot_and_is_valid():
    ad = AgentEAdapter.load(RUN, shield_target=0.2)
    for env, obs, mask in states(every=11):
        snap = snapshot_from_env(env)
        before = copy.deepcopy(snap)
        p = ad.propose(snap)
        assert snap == before
        assert mask[p["action_id"]]
        assert p["fallback_reason"] is None and len(p["q_values"]) == N_ACTIONS
        assert p["audit"]["model_sha256"] and len(p["audit"]["model_sha256"]) == 64


def test_unshielded_adapter_matches_env_greedy_policy():
    ad = AgentEAdapter.load(RUN, shield_target=None)
    for env, obs, mask in states(every=13):
        a_env = ad.agent.act(obs, mask, explore=False)
        assert ad.propose(snapshot_from_env(env))["action_id"] == a_env


def test_urgent_minimum_never_violated_and_shield_veto_reported():
    """Drive whole days WITH the shielded adapter: queue C never drops below the static minimum, and never below
    the dynamic floor through an action of Agent E (only exogenous failures could remove sessions, never from C first)."""
    ad = AgentEAdapter.load(RUN, shield_target=0.1)
    sh = UrgentShield(0.1)
    vetoes = 0
    for k, fam in enumerate(["severe_overload", "high_priority_surge", "normal"]):
        env = EnvV4()
        obs, info = env.reset(seed=777 + k, family=fam)
        done = False
        while not done:
            p = ad.propose(snapshot_from_env(env))
            fl = sh.floor(env)
            after = alloc_after(env, p["action_id"])[QC]
            assert after >= min(fl, env.alloc[QC]) or after > env.alloc[QC]
            if env.alloc[QC] >= fl:
                assert after >= fl
            vetoes += p["safety_veto"]
            if p["safety_veto"]:
                assert p["veto_reason"]
            obs, _, done, _, info = env.step(p["action_id"])
            assert env.alloc[QC] >= env.cfg.min_alloc_urgent
        assert env.kpis()["high_on_fallback"] == 0
    assert vetoes > 0                      # the shield did act on these hard days


def test_shield_mask_logic_below_floor_only_raises_c():
    env = EnvV3()
    env.reset(seed=1, family="normal")
    env.alloc[:] = [6, 4, 2, 4]
    env.queue[QC] = list(range(12))                     # big queue-C backlog -> floor well above 2
    sh = UrgentShield(0.2)
    m, info = sh.mask(env, env.action_mask())
    assert info["floor_c"] > 2
    for a in np.flatnonzero(m):
        assert alloc_after(env, a)[QC] > 2


def test_high_never_on_fallback_with_adapter_forcing_fallback():
    """Even if fallback is switched on all the time, HIGH tickets are never served by fallback (simulator rule)."""
    env = EnvV3()
    obs, info = env.reset(seed=99, family="high_priority_surge")
    done = False
    while not done:
        a = A_FB_ON if info["action_mask"][A_FB_ON] else A_KEEP
        obs, _, done, _, info = env.step(a)
    assert env.kpis()["high_on_fallback"] == 0 and env.kpis()["fallback_share"] <= 0.25


def test_deterministic_reload_of_checkpoint():
    a1, a2 = AgentEAdapter.load(RUN, shield_target=0.2), AgentEAdapter.load(RUN, shield_target=0.2)
    assert a1.model_sha256 == a2.model_sha256
    for env, obs, mask in states(every=17):
        s = snapshot_from_env(env)
        p1, p2 = a1.propose(s), a2.propose(s)
        assert p1["action_id"] == p2["action_id"] and p1["q_values"] == p2["q_values"]


def test_latency_bound():
    ad = AgentEAdapter.load(RUN, shield_target=0.2)
    snaps = [snapshot_from_env(env) for env, _, _ in states(every=9)]
    ad.propose(snaps[0])
    t0 = time.perf_counter()
    for s in snaps:
        ad.propose(s)
    per = 1e3 * (time.perf_counter() - t0) / len(snaps)
    assert per < 20.0, per                    # generous bound for a shared CPU; typical ~1 ms


def test_missing_checkpoint_falls_back_to_rule():
    ad = AgentEAdapter.load("does_not_exist_run", shield_target=0.2)
    env = EnvV3()
    env.reset(seed=5, family="normal")
    p = ad.propose(snapshot_from_env(env))
    assert p["fallback_reason"] and p["policy"].startswith("backup:") and p["mask"][p["action_id"]]


def test_bad_snapshot_rejected():
    env = EnvV3()
    env.reset(seed=5, family="normal")
    s = snapshot_from_env(env)
    s["queues"] = s["queues"][:3]
    with pytest.raises(ValueError):
        SnapshotViewV3(s)


@pytest.mark.parametrize("spec", [f"floor@3|guarded:{RUN}", f"floor@3|rl:{RUN}", "floor@3|rule:mpc:0.5"])
def test_adapter_reproduces_evaluated_policy_and_floor(spec):
    """Driving a full day through the adapter (snapshot -> proposal -> env.step) gives EXACTLY the same day as the
    evaluator's policy object acting on the env directly; queue C is never below 3 after Agent E's own action."""
    from v4.e.policies import make_policy
    from v4.e.evaluate_v4 import run_day
    day = {"day_id": "t", "family": "severe_overload", "seed": 31337}
    ref, _, _ = run_day(EnvV4(), make_policy(spec), day)
    ad = AgentEAdapter.load(spec=spec)
    env = EnvV4()
    env.reset(seed=day["seed"], family=day["family"])
    done = False
    while not done:
        p = ad.propose(snapshot_from_env(env))
        assert alloc_after(env, p["action_id"])[QC] >= min(3, env.alloc[QC] + 1) or env.alloc[QC] >= 3
        if env.alloc[QC] >= 3:
            assert alloc_after(env, p["action_id"])[QC] >= 3
        _, r, done, _, _ = env.step(p["action_id"])
    k = env.kpis()
    assert abs(k["sla_pct"] - ref["sla_pct"]) < 1e-9 and abs(k["cost"] - ref["cost"]) < 1e-9
    assert k["high_on_fallback"] == 0 and k["invalid_proposals"] == 0


def test_recommended_config_loads_and_matches_hash():
    """configs/recommended.json -> adapter with the frozen checkpoint (SHA256 must match the pre-registration)."""
    import json
    from v4.e.common import CFG
    rec = json.loads((CFG / "recommended.json").read_text())
    pr = json.loads((CFG / "preregistration.json").read_text())
    ad = AgentEAdapter.load()
    assert ad.spec == rec["spec"] and ad.model_sha256 == rec["best_pt_sha256"]
    assert pr["checkpoint_hashes"][rec["spec"]]["best_pt_sha256"] == rec["best_pt_sha256"]
    assert ad.info["n_params"] == rec["n_params"] < 100_000
    env = EnvV3()
    env.reset(seed=11, family="normal")
    p = ad.propose(snapshot_from_env(env))
    assert p["fallback_reason"] is None and p["mask"][p["action_id"]] and p["audit"]["model_sha256"] == rec["best_pt_sha256"]
