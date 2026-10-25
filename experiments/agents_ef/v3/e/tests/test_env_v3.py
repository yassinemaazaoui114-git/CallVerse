"""Gate A invariants of the v3 simulator (validity of the benchmark itself)."""

import numpy as np
import pytest
import torch

from baselines.heuristics import ErlangC, Fixed, Forecast
from env.callcenter_env import A_ACT, A_DEACT, A_FB_ON, A_KEEP, N_ACTIONS
from rl.agents import make_agent
from v3.e.env_v3 import ConfigV3, EnvV3
from v3.e.scenarios_v3 import HELDOUT_FAMILIES, TRAIN_FAMILIES, manifest

FAMS = TRAIN_FAMILIES + HELDOUT_FAMILIES


def run(env, policy, seed, fam, record=False):
    obs, info = env.reset(seed=seed, family=fam)
    done, R, parts, obs_log = False, 0.0, [], []
    while not done:
        obs_log.append(obs.copy())
        obs, r, done, _, info = env.step(policy(env, obs, info["action_mask"]))
        assert np.isfinite(obs).all() and np.isfinite(r)
        R += r
        parts.append(info["reward_parts"])
    return R, parts, obs_log


POLICIES = {
    "keep": lambda e, o, m: A_KEEP,
    "forecast": lambda e, o, m, p=Forecast(0.0): p.act(e, o, m),
    "deact": lambda e, o, m: A_DEACT if m[A_DEACT] else A_KEEP,
    "act_fb": lambda e, o, m: A_FB_ON if m[A_FB_ON] else (A_ACT if m[A_ACT] else A_KEEP),
}


@pytest.mark.parametrize("fam", ["normal", "tracking_spike", "failure", "combined_shock", "severe_overload"])
def test_exogenous_world_is_identical_for_every_policy(fam):
    tapes = []
    for name, pol in POLICIES.items():
        env = EnvV3()
        run(env, pol, 900123, fam)
        tp = env.tape
        tapes.append((tp["t_arr"].copy(), tp["q"].copy(), tp["rank"].copy(), tp["pat_e"].copy(), tp["u_fb"].copy(),
                      env.spec.to_dict()))
    for t in tapes[1:]:
        for a, b in zip(tapes[0][:5], t[:5]):
            assert np.array_equal(a, b)
        assert tapes[0][5] == t[5]


@pytest.mark.parametrize("fam", FAMS)
def test_every_ticket_has_exactly_one_outcome_and_constraints_hold(fam):
    rng = np.random.default_rng(0)
    env = EnvV3()
    run(env, lambda e, o, m: int(rng.integers(N_ACTIONS)), 7, fam)       # random, often invalid proposals
    st = env.status
    assert set(np.unique(st)) <= {1, 2, 3, 4}                            # served on time / miss / abandoned / left
    k = env.kpis()
    assert k["budget_ok"] and k["high_on_fallback"] == 0
    assert k["fallback_share"] <= env.cfg.fallback_max_share + 1e-9
    assert env.alloc[2] >= env.cfg.min_alloc_urgent and env.alloc.sum() <= env.cfg.max_sessions
    assert k["sla_pct"] + k["abandon_pct"] + k["unresolved_end_pct"] <= 100 + 1e-9


def test_masked_actions_are_exactly_the_safe_ones():
    env = EnvV3()
    obs, info = env.reset(seed=3, family="failure")
    rng = np.random.default_rng(1)
    for _ in range(96):
        m = info["action_mask"]
        before = (env.alloc.copy(), env.fallback)
        a = int(rng.integers(N_ACTIONS))
        n_inv = env.kpi["invalid_proposals"]
        obs, _, done, _, info = env.step(a)
        assert env.kpi["invalid_proposals"] == n_inv + (0 if m[a] else 1)
        if done:
            break


def test_reward_decomposition_matches_ticket_outcomes():
    env = EnvV3()
    _, parts, _ = run(env, POLICIES["forecast"], 11, "tracking_spike")
    st = env.status
    c = env.cfg
    miss, lost = sum(p["n_miss"] for p in parts), sum(p["n_lost"] for p in parts)
    assert miss == (st == 2).sum() and lost == ((st == 3) | (st == 4)).sum()
    assert sum(p["sla_fail"] for p in parts) * c.ref_fail_per_step == pytest.approx(miss + lost, abs=1e-6)
    assert sum(p["abandon"] for p in parts) * c.ref_lost_per_step == pytest.approx(lost, abs=1e-6)
    assert sum(p["cost"] for p in parts) * c.ref_cost_per_step == pytest.approx(env.kpis()["cost"], abs=1e-6)
    R = -sum(c.w_sla * p["sla_fail"] + c.w_ab * p["abandon"] + c.w_cost * p["cost"] for p in parts)
    k = env.kpis()                                       # the return is a function of the reported KPIs only
    n = k["arrived"]
    R_kpi = -((100 - k["sla_pct"]) / 100 * n / c.ref_fail_per_step + k["lost_pct"] / 100 * n / c.ref_lost_per_step
              + k["cost"] / c.ref_cost_per_step)
    assert R == pytest.approx(R_kpi, rel=1e-6)


def test_no_future_information_in_observations():
    """Two worlds identical up to step 40 and different afterwards give identical observations up to step 40."""
    env = EnvV3()
    env.reset(seed=5, family="normal")
    base = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in env.tape.items()}
    pol = POLICIES["forecast"]

    def obs_seq(mutate):
        e = EnvV3()
        e.build_tape = lambda seed, family=None, spec=None: mutate({k: (v.copy() if isinstance(v, np.ndarray) else v)
                                                                   for k, v in base.items()})
        _, _, log = run(e, pol, 5, "normal")
        return log

    def future_change(tp):
        late = tp["t_arr"] >= 41 * 5.0
        tp["rank"][late] = 2
        tp["pat_e"][late] *= 0.1
        tp["counts"] = tp["counts"].copy()
        tp["counts"][41:] += 3
        return tp
    a, b = obs_seq(lambda tp: tp), obs_seq(future_change)
    for t in range(41):
        assert np.array_equal(a[t], b[t]), t


def test_kpis_are_deterministic_and_stable():
    k1 = [None, None]
    for i in range(2):
        env = EnvV3()
        R, _, _ = run(env, POLICIES["forecast"], 21, "combined_shock")
        k1[i] = (R, env.kpis())
    assert k1[0][0] == k1[1][0] and k1[0][1] == k1[1][1]


def test_rule_baselines_run_and_checkpoint_reload_is_exact(tmp_path):
    env = EnvV3()
    for p in (Fixed(), Forecast(0.5), ErlangC(0.6)):
        run(env, lambda e, o, m, p=p: p.act(e, o, m), 2, "normal")
    a1 = make_agent("dueling_double_dqn", env.obs_dim, env.n_actions, seed=0)
    torch.save(a1.state_dict(), tmp_path / "x.pt")
    a2 = make_agent("dueling_double_dqn", env.obs_dim, env.n_actions, seed=9)
    a2.load_state_dict(torch.load(tmp_path / "x.pt", weights_only=False))
    obs, info = env.reset(seed=4, family="failure")
    for _ in range(30):
        m = info["action_mask"]
        assert a1.act(obs, m, explore=False) == a2.act(obs, m, explore=False)
        obs, _, _, _, info = env.step(a1.act(obs, m, explore=False))


def test_manifests_are_disjoint_and_heldout_families_only_in_test():
    val, test = manifest("val", 5), manifest("test", 5)
    assert not {d["seed"] for d in val} & {d["seed"] for d in test}
    assert all(d["seed"] >= 500_000 for d in val + test)                 # TRAIN seeds are < 200_000
    assert {d["family"] for d in val} == set(TRAIN_FAMILIES)
    assert set(HELDOUT_FAMILIES) <= {d["family"] for d in test}


def test_rho_controls_offered_load():
    env = EnvV3()
    for rho in (0.6, 1.3):
        from v3.e.scenarios_v3 import Spec
        env.reset(seed=1, spec=Spec(family="normal", rho=rho))
        offered = (env.tape["lam"] * env.svc[None, :] / env.cfg.step_min).sum(1).mean()
        assert offered == pytest.approx(rho * env.cfg.init_active, rel=1e-6)
