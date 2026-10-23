"""Intake-aware Agent E (env/intake_env.py): the Intake interface, semantic priority, safety and reproducibility."""

import sys
from pathlib import Path

import numpy as np
import pytest
import torch

from env.callcenter_env import A_FB_ON, A_KEEP, N_ACTIONS
from env.factory import SHAPES, make_env
from env.intake_adapter import LABELS, ROOT, TicketSampler, from_intake_ticket, load_priority_cfg, priority_vec
from env.intake_env import IntakeAwareEnv
from rl.agents import make_agent

sys.path.insert(0, str(ROOT))


def test_vectorised_priority_equals_the_prototype_formula():
    from callverse.intake.priority import compute
    cfg, base = load_priority_cfg(), load_priority_cfg()["severity_base"]
    rng = np.random.default_rng(0)
    for _ in range(300):
        reason = str(rng.choice(list(base)))
        days = int(rng.integers(0, 15)) if rng.random() < 0.6 else None
        delivered, paid, neg = bool(rng.random() < 0.4), float(rng.choice([50, 299, 301, 800])), float(rng.random())
        ref = compute([reason], {"days_late": days, "delivered": delivered, "paid": paid}, neg)
        _, _, _, score, rank = priority_vec([base[reason]], [np.nan if days is None else days], [delivered],
                                            [paid], [neg], cfg)
        assert score[0] == pytest.approx(ref["priority_score"], abs=1e-3)
        assert LABELS[rank[0]] == ref["priority_label"]


def test_semantic_priority_beats_emotional_intensity():
    """A calm client with a 6-day-late order outranks a furious client whose order is on time."""
    cfg = load_priority_cfg()
    b = cfg["severity_base"]
    _, _, _, s, r = priority_vec([b["late_delivery"], b["order_status"]], [6, 0], [False, False], [100, 100],
                                 [0.0, 1.0], cfg)
    assert s[0] > s[1] and r[0] > r[1]
    # emotion can move a score by at most its weight (0.15): never more than the severity weight of one step
    assert cfg["weights"]["emotion_intensity"] < cfg["weights"]["severity"]


def test_real_intake_ticket_adapter():
    t = {"ticket_id": "x", "text": "never used by E", "priority_score": 0.71, "priority_label": "high",
         "emotion_intensity": 0.4, "reasons": ["late_delivery"]}
    f = from_intake_ticket(t)
    assert f == {"priority_score": 0.71, "priority_rank": 2, "emotion_intensity": 0.4}
    assert "text" not in f


def run(env, policy, seed=3, scenario="spike"):
    obs, info = env.reset(seed=seed, scenario=scenario)
    done = False
    while not done:
        obs, r, done, _, info = env.step(policy(env, obs, info["action_mask"]))
        assert np.isfinite(obs).all() and np.isfinite(r)
    return env.episode_kpis()


def test_fallback_cap_and_never_for_high_priority():
    env = make_env("intake")
    always_fb = lambda e, o, m: A_FB_ON if m[A_FB_ON] else A_KEEP
    k = run(env, always_fb)
    assert env.kpi["fallback_steps"] <= 0.25 * env.cfg.steps_per_day
    assert k["high_on_fallback"] == 0 and k["violations"] == 0


def test_random_actions_keep_all_hard_constraints_and_conservation():
    env = make_env("intake")
    rng = np.random.default_rng(1)
    for sc in ("failure", "compound", "high"):
        k = run(env, lambda e, o, m: int(rng.integers(N_ACTIONS)), seed=5, scenario=sc)
        assert env.alloc[2] >= env.cfg.min_alloc_urgent and k["budget_ok"]
        backlog = sum(len(w) for w in env.waiting)
        assert env.kpi["arrived_r"].sum() == env.kpi["served_r"].sum() + env.kpi["abandoned_r"].sum() + backlog
        assert all(len(env.waiting[q]) == len(env.wrank[q]) == len(env.wprio[q]) for q in range(4))


def test_high_priority_served_before_low_in_same_queue():
    env = make_env("intake")
    env.reset(seed=0, scenario="normal")
    env.alloc[:] = [1, 6, 6, 6]
    env.waiting[0] = np.array([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1])  # all old
    env.wrank[0] = np.array([0] * 11 + [2], np.int8)                       # the NEWEST one is high priority
    env.wprio[0] = np.full(12, 0.3, np.float32)
    env.wemo[0] = np.zeros(12, np.float32)
    env.step(A_KEEP)
    assert 2 not in env.wrank[0][:11].tolist()                             # the high ticket left the queue first
    assert env.kpi["served_r"][2] >= 1


def test_determinism_and_obs_has_no_text():
    a, b = make_env("intake"), make_env("intake")
    pol = lambda e, o, m: A_KEEP
    assert run(a, pol, seed=7) == run(b, pol, seed=7)
    o, _ = a.reset(seed=1)
    assert o.shape == (IntakeAwareEnv.obs_dim,) and o.dtype == np.float32


def test_checkpoint_round_trip_on_intake_obs(tmp_path):
    env = make_env("intake")
    a1 = make_agent("dueling_double_dqn", env.obs_dim, env.n_actions, seed=0)
    torch.save(a1.state_dict(), tmp_path / "x.pt")
    a2 = make_agent("dueling_double_dqn", env.obs_dim, env.n_actions, seed=1)
    a2.load_state_dict(torch.load(tmp_path / "x.pt", weights_only=False))
    obs, info = env.reset(seed=2)
    for _ in range(20):
        m = info["action_mask"]
        assert a1.act(obs, m, explore=False) == a2.act(obs, m, explore=False)
        obs, _, _, _, info = env.step(a1.act(obs, m, explore=False))


def test_demand_options_and_v1_defaults():
    v1a, v1b = make_env("v1"), make_env("v1", overrides={})
    assert run(v1a, lambda e, o, m: A_KEEP) == run(v1b, lambda e, o, m: A_KEEP)
    ev = make_env("intake", overrides={"hourly_profile": "evening", "load_sigma": 0.43})
    assert ev.cfg.hourly_profile == SHAPES["evening"]
    pool = make_env("intake", overrides={"shape_pool": ["two_peak", "flat", "morning"]})
    seen = {pool.reset(seed=s)[0] is not None and pool._shape for s in range(20)}
    assert len(seen) == 3 and SHAPES["evening"] not in seen              # evening stays held out


def test_f_reward_is_monotone_and_bounded():
    p = Path(__file__).resolve().parent.parent / "results" / "f_reward" / "olist_isotonic.json"
    if not p.exists():
        pytest.skip("python -m agent_f.f_reward --raw <olist>")
    from agent_f.f_reward import load_f_reward
    f = load_f_reward(p)
    y = f(0, np.linspace(0, 4, 50), None, None, None)
    assert (np.diff(y) <= 1e-9).all() and y.min() >= 1 and y.max() <= 5


def test_sampler_label_mix_is_plausible():
    s, rng = TicketSampler(), np.random.default_rng(0)
    ranks = np.concatenate([s.sample(q, 5000, rng)[1] for q in range(4)])
    share = np.bincount(ranks, minlength=3) / len(ranks)
    assert 0.02 < share[2] < 0.3 and share[0] > 0.3
