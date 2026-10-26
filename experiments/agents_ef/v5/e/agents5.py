"""Agent E v5 - extensions of the frozen V3 DQN family (rl/agents.py is NOT modified; we subclass it).

What is added, and why (each answers one question of the V5 plan, see NOTEBOOK.md):
- SumTree + Prioritized Experience Replay (PER, Schaul et al. 2016, proportional variant).
  WHY: the V4 diagnosis found that queue-C failures are rare and delayed (~12 % of tickets) and the network
  under-values moves into C exactly in those rare states. PER replays transitions with a large TD error more often,
  so rare, surprising transitions (e.g. a queue-C miss) are learned from more often.
  Details: priority p_i = (min(|TD_i|, clip) + eps)^alpha; new transitions get the current max priority;
  sampling is stratified (one draw per equal slice of the total priority); importance-sampling weights
  w_i = (N * P(i))^-beta / max_j (N * P(j))^-beta = (p_min / p_i)^beta  (in (0, 1]), beta annealed linearly
  from beta0 to 1 over the training budget; all random draws use the agent's seeded numpy Generator.
- N-step returns (Sutton & Barto ch. 7; Rainbow). WHY: the cost of NOT protecting queue C arrives several
  5-minute steps later (service 6 min, SLA 5 min, abandonment after patience). An n-step target
      R_t^(n) = r_t + g r_{t+1} + ... + g^(n-1) r_{t+n-1} + g^n * (1-done) * Q_target(s_{t+n}, a*)
  propagates that delayed cost n times faster. The day ends after step 96 (a TRUE terminal: tickets still waiting
  are counted as lost), so at the end of a day the remaining partial windows are flushed with done = 1 and no
  bootstrap. Each stored transition keeps its own discount g^k (k = number of rewards summed).
  Caveat: n-step targets with an epsilon-greedy behaviour policy are slightly biased (no off-policy correction).
- QRDQN (Dabney et al. 2018, small): N quantiles per action, quantile-Huber loss. Only run if the plan justifies it.
  Its `.q` module returns the MEAN over quantiles, so every V4 policy wrapper (greedy argmax, guarded, floor) works.

With prioritized=False and n_step=1, DQN5 calls the unchanged V3 code paths (observe/_update of rl.agents.DQN),
so it reproduces V3 training exactly (checked in NOTEBOOK: same VAL return at 15k steps as the V3 run).
"""

from collections import deque

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from rl.agents import DQN, NEG, mlp


# ---------------------------------------------------------------------------------------------- sum tree
class SumTree:
    """Binary tree over `cap` leaves storing priorities; every inner node = sum (and min) of its children.
    Leaves live at positions [P, 2P) of the arrays (P = next power of two >= cap). All operations are vectorised
    over a batch of indices (numpy), so one update/sample costs O(batch * log2(P))."""

    def __init__(self, cap: int):
        self.cap = int(cap)
        self.P = 1 << int(np.ceil(np.log2(max(cap, 2))))
        self.depth = int(np.log2(self.P))
        self.sum = np.zeros(2 * self.P, np.float64)
        self.min = np.full(2 * self.P, np.inf, np.float64)

    def update(self, idx, prio):
        idx = np.asarray(idx, np.int64)
        prio = np.asarray(prio, np.float64)
        if np.any(prio <= 0) or not np.all(np.isfinite(prio)):
            raise ValueError("priorities must be finite and > 0")
        node = idx + self.P
        self.sum[node] = prio          # with duplicate indices, the last write wins (numpy semantics)
        self.min[node] = prio
        node = np.unique(node // 2)
        while node[0] >= 1:            # recompute parents from children: correct even with duplicates
            self.sum[node] = self.sum[2 * node] + self.sum[2 * node + 1]
            self.min[node] = np.minimum(self.min[2 * node], self.min[2 * node + 1])
            if node[0] == 1:
                break
            node = np.unique(node // 2)

    def total(self) -> float:
        return float(self.sum[1])

    def min_prio(self) -> float:
        return float(self.min[1])

    def leaf(self, idx):
        return self.sum[np.asarray(idx, np.int64) + self.P]

    def find(self, values):
        """For each value v in [0, total): the leaf i with cumsum(i-1) <= v < cumsum(i)."""
        v = np.asarray(values, np.float64).copy()
        node = np.ones(len(v), np.int64)
        for _ in range(self.depth):
            left = 2 * node
            right_go = v >= self.sum[left]
            v = np.where(right_go, v - self.sum[left], v)
            node = left + right_go
        return node - self.P


# ---------------------------------------------------------------------------------------------- DQN5
class DQN5(DQN):
    """V3 DQN (+double/dueling options) with optional PER and n-step returns.

    Extra arguments: prioritized, alpha (0.6), beta0 (0.4), beta_steps (anneal length, = training budget),
    prio_eps (1e-3: keeps zero-TD transitions sampleable), prio_clip (5.0: caps |TD| before it becomes a priority,
    so one outlier cannot dominate sampling), n_step (1 = V3)."""

    def __init__(self, obs_dim, n_actions, hidden=(64, 64), double=False, dueling=False, prioritized=False,
                 alpha=0.6, beta0=0.4, beta_steps=150_000, prio_eps=1e-3, prio_clip=5.0, n_step=1, **kw):
        super().__init__(obs_dim, n_actions, hidden, double=double, dueling=dueling, **kw)
        self.prioritized, self.n_step = bool(prioritized), int(n_step)
        self.alpha, self.beta0, self.beta_steps = float(alpha), float(beta0), int(beta_steps)
        self.prio_eps, self.prio_clip = float(prio_eps), float(prio_clip)
        self.disc = np.full(self.cap, self.gamma, np.float32)      # per-transition bootstrap discount g^k
        self.tree = SumTree(self.cap) if self.prioritized else None
        self.max_prio = 1.0                                          # priority given to new transitions
        self.pending = deque()                                       # n-step window (obs, action, reward)
        self.plain = (not self.prioritized) and self.n_step == 1
        self.last_is_w = None                                        # for tests / diagnostics
        self.last_idx = None
        base = self.name
        if self.n_step > 1:
            base += f"_n{self.n_step}"
        if self.prioritized:
            base += "_per"
        self.name = base

    # ---------------------------------------------------------------- storage
    def beta(self) -> float:
        return min(1.0, self.beta0 + (1.0 - self.beta0) * self.steps / max(self.beta_steps, 1))

    def _store(self, o, a, r, o2, d, m2, g):
        i = self.ptr
        self.o[i], self.a[i], self.r[i], self.o2[i], self.d[i], self.m2[i] = o, a, r, o2, float(d), m2
        self.disc[i] = g
        if self.prioritized:
            self.tree.update([i], [self.max_prio])
        self.ptr, self.size = (i + 1) % self.cap, min(self.size + 1, self.cap)

    def _push_nstep(self, obs2, done, mask2):
        """Store the transition that starts at the oldest pending step, summing the pending rewards."""
        R, g = 0.0, 1.0
        for (_, _, r) in self.pending:
            R += g * r
            g *= self.gamma
        o0, a0, _ = self.pending[0]
        self._store(o0, a0, R, obs2, done, mask2, g)                # g = gamma^(number of rewards summed)
        self.pending.popleft()

    def observe(self, obs, a, r, obs2, done, mask2, **kw):
        if self.plain:                                               # exact V3 behaviour
            return super().observe(obs, a, r, obs2, done, mask2, **kw)
        self.pending.append((np.asarray(obs, np.float32).copy(), int(a), float(r)))
        if len(self.pending) == self.n_step:
            self._push_nstep(obs2, done, mask2)
        if done:                                                     # day over: flush partial windows, no bootstrap
            while self.pending:
                self._push_nstep(obs2, True, mask2)
        self.steps += 1
        if self.steps >= self.learning_starts and self.steps % self.train_every == 0 and self.size >= self.batch:
            self._update()
        if self.steps % self.target_every == 0:
            self.q_target.load_state_dict(self.q.state_dict())

    # ---------------------------------------------------------------- sampling
    def sample(self, batch: int):
        """Returns (indices, importance weights). Uniform replay: weights = 1."""
        if not self.prioritized:
            return self.rng.integers(0, self.size, batch), np.ones(batch, np.float32)
        total = self.tree.total()
        seg = total / batch
        u = (np.arange(batch) + self.rng.random(batch)) * seg        # stratified: one draw per slice
        u = np.minimum(u, np.nextafter(total, 0))
        idx = np.minimum(self.tree.find(u), self.size - 1)
        p = self.tree.leaf(idx)
        w = (self.tree.min_prio() / p) ** self.beta()                 # = (N P_i)^-b / max_j (N P_j)^-b
        return idx, w.astype(np.float32)

    def update_priorities(self, idx, td_abs):
        pr = (np.minimum(np.asarray(td_abs, np.float64), self.prio_clip) + self.prio_eps) ** self.alpha
        self.tree.update(idx, pr)
        self.max_prio = max(self.max_prio, float(pr.max()))

    # ---------------------------------------------------------------- learning
    def _targets(self, o2, r, d, g, m2):
        with torch.no_grad():
            q_next_t = self.q_target(o2).masked_fill(~m2, NEG)
            if self.double:
                a2 = self.q(o2).masked_fill(~m2, NEG).argmax(1, keepdim=True)
                q_next = q_next_t.gather(1, a2).squeeze(1)
            else:
                q_next = q_next_t.max(1).values
            return r + g * (1 - d) * q_next

    def _update(self):
        if self.plain:
            return super()._update()
        idx, w = self.sample(self.batch)
        self.last_idx, self.last_is_w = idx, w
        o, o2 = torch.as_tensor(self.o[idx]), torch.as_tensor(self.o2[idx])
        a, r, d = torch.as_tensor(self.a[idx]), torch.as_tensor(self.r[idx]), torch.as_tensor(self.d[idx])
        g, m2, wt = torch.as_tensor(self.disc[idx]), torch.as_tensor(self.m2[idx]), torch.as_tensor(w)
        target = self._targets(o2, r, d, g, m2)
        q = self.q(o).gather(1, a.unsqueeze(1)).squeeze(1)
        loss = (wt * F.smooth_l1_loss(q, target, reduction="none")).mean()
        self.opt.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.q.parameters(), 10.0)
        self.opt.step()
        self.losses.append(float(loss))
        if self.prioritized:
            self.update_priorities(idx, (target - q).detach().abs().numpy())


# ---------------------------------------------------------------------------------------------- QR-DQN
class QRNet(nn.Module):
    """MLP body -> n_actions x n_quant quantile estimates. forward() = mean over quantiles (= Q-values)."""

    def __init__(self, obs_dim, n_actions, hidden=(64, 64), n_quant=21):
        super().__init__()
        self.n_actions, self.n_quant = n_actions, n_quant
        self.body = mlp(obs_dim, hidden[:-1], hidden[-1])
        self.head = nn.Linear(hidden[-1], n_actions * n_quant)

    def quantiles(self, x):
        h = torch.tanh(self.body(x))
        return self.head(h).view(-1, self.n_actions, self.n_quant)

    def forward(self, x):
        return self.quantiles(x).mean(-1)


class QRDQN(DQN5):
    """Quantile-regression DQN (risk-NEUTRAL greedy action = argmax of the mean). Supports n-step / PER / double."""

    def __init__(self, obs_dim, n_actions, hidden=(64, 64), n_quant=21, seed=0, **kw):
        super().__init__(obs_dim, n_actions, hidden, seed=seed, **kw)
        torch.manual_seed(seed)
        import copy
        self.q = QRNet(obs_dim, n_actions, hidden, n_quant)
        self.q_target = copy.deepcopy(self.q)
        self.opt = torch.optim.Adam(self.q.parameters(), lr=self.opt.param_groups[0]["lr"])
        self.n_quant = n_quant
        self.tau = torch.as_tensor((np.arange(n_quant) + 0.5) / n_quant, dtype=torch.float32)
        self.plain = False                    # always use the QR update
        self.name = "qr_" + self.name

    def _update(self):
        idx, w = self.sample(self.batch)
        o, o2 = torch.as_tensor(self.o[idx]), torch.as_tensor(self.o2[idx])
        a, r, d = torch.as_tensor(self.a[idx]), torch.as_tensor(self.r[idx]), torch.as_tensor(self.d[idx])
        g, m2, wt = torch.as_tensor(self.disc[idx]), torch.as_tensor(self.m2[idx]), torch.as_tensor(w)
        B = len(idx)
        with torch.no_grad():
            zt = self.q_target.quantiles(o2)                                  # [B, A, N]
            sel = self.q if self.double else self.q_target
            a2 = sel(o2).masked_fill(~m2, NEG).argmax(1)                      # greedy on the mean
            z_next = zt[torch.arange(B), a2]                                  # [B, N]
            target = r[:, None] + (g * (1 - d))[:, None] * z_next             # [B, N]
        z = self.q.quantiles(o)[torch.arange(B), a]                           # [B, N]
        u = target[:, None, :] - z[:, :, None]                                # [B, N(pred), N(target)]
        hub = F.smooth_l1_loss(z[:, :, None].expand_as(u), target[:, None, :].expand_as(u), reduction="none")
        rho = (self.tau[None, :, None] - (u.detach() < 0).float()).abs() * hub
        per_sample = rho.sum(1).mean(1)                                       # sum over pred quantiles, mean over targets
        loss = (wt * per_sample).mean()
        self.opt.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.q.parameters(), 10.0)
        self.opt.step()
        self.losses.append(float(loss))
        if self.prioritized:
            self.update_priorities(idx, per_sample.detach().numpy())


def make_agent5(algo: str, obs_dim: int, n_actions: int, seed: int, hidden=(64, 64), **kw):
    """algo in {dueling_dqn, dueling_double_dqn, double_dqn, dqn, qr_dqn, qr_double_dqn}; kw = DQN5 options."""
    if algo.startswith("qr_"):
        return QRDQN(obs_dim, n_actions, hidden, seed=seed, double="double" in algo, **kw)
    return DQN5(obs_dim, n_actions, hidden, double="double" in algo, dueling=algo.startswith("dueling"), seed=seed, **kw)
