"""Unit tests for v5 agent extensions: sum tree, PER (priorities, IS weights, sampling distribution, terminal
handling, reproducibility), n-step targets (truncation at day end, discounting), QR-DQN shapes.
Run: python -m pytest v5/e/tests -q   (from experiments/agents_ef)"""

import sys
from pathlib import Path

import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from v5.e.agents5 import DQN5, QRDQN, SumTree, make_agent5  # noqa: E402

OBS, ACT = 5, 4


def small(**kw):
    base = dict(hidden=(8, 8), buffer=64, batch=8, learning_starts=10_000, seed=0, gamma=0.9)
    base.update(kw)
    return DQN5(OBS, ACT, **base)


# ------------------------------------------------------------------ sum tree
def test_sumtree_total_min_and_update_with_duplicates():
    t = SumTree(10)
    t.update(np.arange(10), np.arange(1, 11, dtype=float))
    assert t.total() == pytest.approx(55.0)
    assert t.min_prio() == pytest.approx(1.0)
    t.update([3, 3, 0], [7.0, 2.0, 5.0])            # duplicate index: last write wins
    assert t.leaf([3])[0] == pytest.approx(2.0)
    assert t.total() == pytest.approx(55.0 - 4.0 + 2.0 - 1.0 + 5.0)
    assert t.min_prio() == pytest.approx(2.0)
    with pytest.raises(ValueError):
        t.update([1], [0.0])


def test_sumtree_find_boundaries():
    t = SumTree(4)
    t.update([0, 1, 2, 3], [1.0, 2.0, 3.0, 4.0])     # cumsum 1,3,6,10
    v = np.array([0.0, 0.999, 1.0, 2.99, 3.0, 5.99, 6.0, 9.999])
    assert t.find(v).tolist() == [0, 0, 1, 1, 2, 2, 3, 3]


def test_per_sampling_distribution_matches_priorities():
    ag = small(prioritized=True, alpha=1.0, buffer=4)
    for i in range(4):
        ag._store(np.zeros(OBS), 0, 0.0, np.zeros(OBS), False, np.ones(ACT, bool), 0.9)
    ag.tree.update([0, 1, 2, 3], [1.0, 2.0, 3.0, 4.0])
    counts = np.zeros(4)
    for _ in range(3000):
        idx, _ = ag.sample(8)
        np.add.at(counts, idx, 1)
    freq = counts / counts.sum()
    assert np.allclose(freq, [0.1, 0.2, 0.3, 0.4], atol=0.015)


def test_per_is_weights_normalised_and_annealed():
    ag = small(prioritized=True, beta0=0.4, beta_steps=100, buffer=4)
    for i in range(4):
        ag._store(np.zeros(OBS), 0, 0.0, np.zeros(OBS), False, np.ones(ACT, bool), 0.9)
    ag.tree.update([0, 1, 2, 3], [1.0, 2.0, 3.0, 4.0])
    idx, w = ag.sample(64)
    assert w.max() <= 1.0 + 1e-6 and w.min() > 0
    p = ag.tree.leaf(idx)
    assert np.allclose(w, (1.0 / p) ** 0.4, rtol=1e-5)          # (p_min / p_i)^beta, beta = beta0 at step 0
    ag.steps = 50
    assert ag.beta() == pytest.approx(0.7)
    ag.steps = 1000
    assert ag.beta() == pytest.approx(1.0)                       # capped at 1


def test_priority_update_eps_clip_and_max():
    ag = small(prioritized=True, alpha=0.5, prio_eps=0.01, prio_clip=2.0, buffer=4)
    for i in range(4):
        ag._store(np.zeros(OBS), 0, 0.0, np.zeros(OBS), False, np.ones(ACT, bool), 0.9)
    assert np.allclose(ag.tree.leaf([0, 1, 2, 3]), 1.0)          # new transitions = current max priority (1)
    ag.update_priorities(np.array([0, 1, 2]), np.array([0.0, 1.0, 100.0]))
    assert ag.tree.leaf([0])[0] == pytest.approx(0.01 ** 0.5)    # zero TD still sampleable (eps)
    assert ag.tree.leaf([1])[0] == pytest.approx(1.01 ** 0.5)
    assert ag.tree.leaf([2])[0] == pytest.approx(2.01 ** 0.5)    # clipped at prio_clip
    assert ag.max_prio == pytest.approx(2.01 ** 0.5)
    ag._store(np.zeros(OBS), 0, 0.0, np.zeros(OBS), False, np.ones(ACT, bool), 0.9)   # overwrites slot 0
    assert ag.tree.leaf([0])[0] == pytest.approx(2.01 ** 0.5)


def test_per_sampling_reproducible_with_seed():
    def run(seed):
        ag = small(prioritized=True, seed=seed, buffer=32)
        for i in range(32):
            ag._store(np.full(OBS, i, np.float32), i % ACT, float(i), np.zeros(OBS), False, np.ones(ACT, bool), 0.9)
        ag.update_priorities(np.arange(32), np.linspace(0, 3, 32))
        return ag.sample(16)[0]
    assert np.array_equal(run(1), run(1))
    assert not np.array_equal(run(1), run(2))


def test_per_never_samples_unfilled_slots():
    ag = small(prioritized=True, buffer=64)
    for i in range(5):
        ag._store(np.zeros(OBS), 0, 0.0, np.zeros(OBS), False, np.ones(ACT, bool), 0.9)
    for _ in range(200):
        idx, _ = ag.sample(8)
        assert idx.max() < 5


# ------------------------------------------------------------------ n-step
def feed(ag, rewards, done_last=True):
    for t, r in enumerate(rewards):
        done = done_last and t == len(rewards) - 1
        ag.observe(np.full(OBS, t, np.float32), t % ACT, r, np.full(OBS, t + 1, np.float32), done,
                   np.ones(ACT, bool))


def test_nstep_targets_and_terminal_truncation():
    g = 0.9
    ag = small(n_step=3, gamma=g)
    rew = [1.0, 2.0, 3.0, 4.0, 5.0]
    feed(ag, rew, done_last=True)
    assert ag.size == 5                                         # one transition per step, none lost
    # transition starting at t=0: r0 + g r1 + g^2 r2, bootstrap from s3 with g^3, not terminal
    assert ag.r[0] == pytest.approx(1 + g * 2 + g * g * 3)
    assert ag.disc[0] == pytest.approx(g ** 3) and ag.d[0] == 0 and ag.o2[0][0] == 3
    # t=2 window [2,3,4] ends at the terminal step: done=1 (no bootstrap)
    assert ag.r[2] == pytest.approx(3 + g * 4 + g * g * 5) and ag.d[2] == 1 and ag.o2[2][0] == 5
    # partial windows flushed at the end of the day: t=3 -> r3 + g r4 ; t=4 -> r4 ; both terminal
    assert ag.r[3] == pytest.approx(4 + g * 5) and ag.d[3] == 1 and ag.disc[3] == pytest.approx(g ** 2)
    assert ag.r[4] == pytest.approx(5.0) and ag.d[4] == 1 and ag.o[4][0] == 4
    assert len(ag.pending) == 0


def test_nstep_window_does_not_cross_days():
    ag = small(n_step=3)
    feed(ag, [1.0, 1.0], done_last=True)                        # short day (2 steps)
    feed(ag, [10.0, 10.0, 10.0, 10.0], done_last=False)         # next day starts: no mixing of rewards
    assert ag.r[0] == pytest.approx(1 + 0.9) and ag.d[0] == 1
    assert ag.r[1] == pytest.approx(1.0) and ag.d[1] == 1
    assert ag.r[2] == pytest.approx(10 + 9 + 8.1) and ag.d[2] == 0


def test_nstep_one_equals_v3_dqn_transitions():
    from rl.agents import DQN
    a5, a3 = small(n_step=1), DQN(OBS, ACT, hidden=(8, 8), buffer=64, batch=8, learning_starts=10_000, seed=0, gamma=0.9)
    for ag in (a5, a3):
        feed(ag, [1.0, 2.0, 3.0])
    assert a5.plain
    assert np.array_equal(a5.r[:3], a3.r[:3]) and np.array_equal(a5.d[:3], a3.d[:3])


def test_bootstrap_target_uses_gamma_n_and_done():
    ag = small(n_step=3, double=True)
    o2 = torch.zeros(2, OBS)
    r, d = torch.tensor([1.0, 1.0]), torch.tensor([0.0, 1.0])
    g = torch.tensor([0.729, 0.729])
    m2 = torch.ones(2, ACT, dtype=torch.bool)
    with torch.no_grad():
        qn = ag.q_target(o2)[0, ag.q(o2)[0].argmax()].item()
    t = ag._targets(o2, r, d, g, m2)
    assert t[0].item() == pytest.approx(1 + 0.729 * qn, rel=1e-5)
    assert t[1].item() == pytest.approx(1.0)                      # terminal: no bootstrap


def test_per_update_runs_and_changes_priorities():
    ag = small(prioritized=True, n_step=3, learning_starts=0, train_every=1, buffer=64, batch=8)
    feed(ag, list(np.linspace(-1, 1, 20)))
    assert ag.last_is_w is not None and ag.tree.total() > 0
    assert not np.allclose(ag.tree.leaf(np.arange(ag.size)), ag.tree.leaf([0])[0])


# ------------------------------------------------------------------ QR-DQN
def test_qrdqn_shapes_and_update():
    ag = QRDQN(OBS, ACT, hidden=(8, 8), n_quant=5, buffer=64, batch=8, learning_starts=0, train_every=1, seed=0)
    z = ag.q.quantiles(torch.zeros(3, OBS))
    assert z.shape == (3, ACT, 5)
    assert torch.allclose(ag.q(torch.zeros(3, OBS)), z.mean(-1))
    feed(ag, [1.0] * 12)
    assert len(ag.losses) > 0 and np.isfinite(ag.losses[-1])


def test_make_agent5_names():
    assert make_agent5("dueling_dqn", OBS, ACT, 0, hidden=(8, 8), prioritized=True, n_step=3).name == "dueling_dqn_n3_per"
    assert make_agent5("dueling_double_dqn", OBS, ACT, 0, hidden=(8, 8)).double
