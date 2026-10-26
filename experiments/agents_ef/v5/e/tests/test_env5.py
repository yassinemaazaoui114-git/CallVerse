"""EnvV5 tests: no shift == frozen EnvV3; shifts are reproducible, identical across policies (common random
numbers), and do what they say (service slower, patience shorter, extra spikes); DR draws stay in range."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from v3.e.env_v3 import EnvV3  # noqa: E402
from v3.e.scenarios_v3 import TRAIN_FAMILIES  # noqa: E402
from v5.e.common5 import DR, EnvV5, draw_shift  # noqa: E402


def play(env, seed, family=None, shift=None, policy=lambda t, m: 0):
    env.pending_shift = shift if hasattr(env, "pending_shift") else None
    obs, info = env.reset(seed=seed, family=family)
    R, done = 0.0, False
    while not done:
        a = policy(env.t, info["action_mask"])
        obs, r, done, _, info = env.step(a if info["action_mask"][a] else 0)
        R += r
    return R, env.kpis()


def test_no_shift_identical_to_v3():
    for seed, fam in ((3, "normal"), (11, "failure"), (17, "slowdown")):
        r3, k3 = play(EnvV3(), seed, fam)
        r5, k5 = play(EnvV5(), seed, fam)
        assert r3 == r5 and k3 == k5


def test_shift_reproducible_and_policy_independent_world():
    sh = draw_shift(np.random.default_rng(0), DR["train_ranges"], "normal")
    e1, e2 = EnvV5(), EnvV5()
    e1.pending_shift, e2.pending_shift = sh, sh
    e1.reset(seed=5)
    e2.reset(seed=5)
    assert np.array_equal(e1.tape["t_arr"], e2.tape["t_arr"]) and np.array_equal(e1.abandon_at, e2.abandon_at)
    rA, _ = play(EnvV5(), 5, shift=sh, policy=lambda t, m: 0)
    rB, _ = play(EnvV5(), 5, shift=sh, policy=lambda t, m: 0)
    assert rA == rB


def test_slow_service_hurts_and_patience_shift_applies():
    base = draw_shift(np.random.default_rng(1), {}, "normal")
    slow = dict(base, svc_mult=[1.3] * 4)
    imp = dict(base, pat_mult=[0.5] * 4)
    r0, k0 = play(EnvV5(), 9, shift=base)
    r1, k1 = play(EnvV5(), 9, shift=slow)
    r2, k2 = play(EnvV5(), 9, shift=imp)
    assert k1["arrived"] == k0["arrived"] and r1 < r0           # same tickets, slower service = worse
    assert k2["abandon_pct"] > k0["abandon_pct"]
    e = EnvV5()
    e.pending_shift = imp
    e.reset(seed=9)
    e0 = EnvV5()
    e0.pending_shift = base
    e0.reset(seed=9)
    assert np.allclose(e.abandon_at - e.tape["t_arr"] - 2.0, 0.5 * (e0.abandon_at - e0.tape["t_arr"] - 2.0))


def test_dr_draws_in_range_and_reproducible():
    env = EnvV5(None, TRAIN_FAMILIES, dr_ranges=DR["train_ranges"])
    tr = DR["train_ranges"]
    for seed in range(40):
        env.reset(seed=seed)
        sh = env.shift
        assert sh["base_family"] in TRAIN_FAMILIES
        assert all(tr["svc_mult"][0] <= x <= tr["svc_mult"][1] for x in sh["svc_mult"])
        assert all(tr["pat_mult"][0] <= x <= tr["pat_mult"][1] for x in sh["pat_mult"])
        for q, a, b, m in sh["extra_spikes"]:
            assert q in (1, 2) and 0 <= a < b <= 96
            assert m <= max(tr["urgent_spike"]["mult"][1], tr["refund_surge"]["mult"][1])
    env.reset(seed=3)
    s1 = env.shift
    env.reset(seed=3)
    assert env.shift == s1


def test_unseen_shifts_outside_training_ranges():
    tr, un = DR["train_ranges"], DR["unseen_test_shifts"]
    assert un["shift_slow_service"]["svc_mult_common"][0] > tr["svc_mult"][1]
    assert un["shift_impatient"]["pat_mult_common"][1] < tr["pat_mult"][0]
    assert un["shift_urgent_wave"]["urgent_spike"]["mult"][0] > tr["urgent_spike"]["mult"][1]
