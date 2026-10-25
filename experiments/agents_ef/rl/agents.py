"""Tiny RL agents for Agent E, written from scratch (CleanRL style) so every line is readable and no new library
is needed. All use the environment's ACTION MASK: invalid actions are never chosen (the env's safety layer is a
second, independent guard).

- TabularQ:  Q-learning on a 72-state discretisation (dominant queue x load level x fallback x headroom).
- DQN:       MLP Q-network, replay buffer, target network. Options: double=True (Double DQN),
             dueling=True (Dueling head).
- PPO:       actor-critic MLP, clipped objective, GAE, masked categorical policy.
"""

import copy

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


def mlp(inp, hidden, out):
    layers, d = [], inp
    for h in hidden:
        layers += [nn.Linear(d, h), nn.Tanh()]
        d = h
    layers.append(nn.Linear(d, out))
    return nn.Sequential(*layers)


def n_params(module) -> int:
    return sum(p.numel() for p in module.parameters())


NEG = -1e9


# ---------------------------------------------------------------------------------------------- tabular Q
class TabularQ:
    name = "tabular_q"
    n_states = 4 * 3 * 2 * 3

    def __init__(self, obs_dim, n_actions, lr=0.1, gamma=0.97, eps_start=1.0, eps_end=0.05, eps_steps=100_000,
                 seed=0):
        self.q = np.zeros((self.n_states, n_actions))
        self.lr, self.gamma = lr, gamma
        self.eps_start, self.eps_end, self.eps_steps = eps_start, eps_end, eps_steps
        self.rng = np.random.default_rng(seed)
        self.steps = 0

    @staticmethod
    def state(obs) -> int:
        util = obs[5:24:6]                                   # per-queue utilisation feature (index 5 of each block)
        dom = int(np.argmax(util))
        level = 0 if util[dom] < 0.8 else (1 if util[dom] < 1.3 else 2)
        fb = int(obs[26] > 0.5)
        headroom = obs[25] - obs[24]                          # available - active (fraction of max)
        hr = 0 if headroom <= 0.01 else (1 if headroom < 0.2 else 2)
        return ((dom * 3 + level) * 2 + fb) * 3 + hr

    def act(self, obs, mask, explore=True):
        s = self.state(obs)
        eps = max(self.eps_end, self.eps_start - (self.eps_start - self.eps_end) * self.steps / self.eps_steps)
        if explore and self.rng.random() < eps:
            return int(self.rng.choice(np.flatnonzero(mask)))
        q = np.where(mask, self.q[s], NEG)
        return int(np.argmax(q))

    def observe(self, obs, a, r, obs2, done, mask2, **kw):
        s, s2 = self.state(obs), self.state(obs2)
        target = r if done else r + self.gamma * np.max(np.where(mask2, self.q[s2], NEG))
        self.q[s, a] += self.lr * (target - self.q[s, a])
        self.steps += 1

    def state_dict(self):
        return {"q": self.q}

    def load_state_dict(self, d):
        self.q = d["q"]

    def n_params(self):
        return self.q.size


# ---------------------------------------------------------------------------------------------- DQN family
class QNet(nn.Module):
    def __init__(self, obs_dim, n_actions, hidden=(64, 64), dueling=False):
        super().__init__()
        self.dueling = dueling
        if dueling:
            self.body = mlp(obs_dim, hidden[:-1], hidden[-1])
            self.v = nn.Linear(hidden[-1], 1)
            self.a = nn.Linear(hidden[-1], n_actions)
        else:
            self.net = mlp(obs_dim, hidden, n_actions)

    def forward(self, x):
        if not self.dueling:
            return self.net(x)
        h = torch.tanh(self.body(x))
        a = self.a(h)
        return self.v(h) + a - a.mean(-1, keepdim=True)


class DQN:
    def __init__(self, obs_dim, n_actions, hidden=(64, 64), double=False, dueling=False, lr=5e-4, gamma=0.97,
                 buffer=100_000, batch=128, train_every=4, target_every=2000, eps_start=1.0, eps_end=0.05,
                 eps_steps=60_000, learning_starts=5_000, seed=0):
        torch.manual_seed(seed)
        self.name = ("dueling_" if dueling else "") + ("double_dqn" if double else "dqn")
        self.q = QNet(obs_dim, n_actions, hidden, dueling)
        self.q_target = copy.deepcopy(self.q)
        self.opt = torch.optim.Adam(self.q.parameters(), lr=lr)
        self.double, self.gamma, self.batch = double, gamma, batch
        self.train_every, self.target_every, self.learning_starts = train_every, target_every, learning_starts
        self.eps_start, self.eps_end, self.eps_steps = eps_start, eps_end, eps_steps
        self.rng = np.random.default_rng(seed)
        n = buffer
        self.o = np.zeros((n, obs_dim), np.float32)
        self.o2 = np.zeros((n, obs_dim), np.float32)
        self.a = np.zeros(n, np.int64)
        self.r = np.zeros(n, np.float32)
        self.d = np.zeros(n, np.float32)
        self.m2 = np.zeros((n, n_actions), bool)
        self.ptr, self.size, self.cap, self.steps = 0, 0, n, 0
        self.losses = []

    def act(self, obs, mask, explore=True):
        eps = max(self.eps_end, self.eps_start - (self.eps_start - self.eps_end) * self.steps / self.eps_steps)
        if explore and self.rng.random() < eps:
            return int(self.rng.choice(np.flatnonzero(mask)))
        with torch.no_grad():
            q = self.q(torch.as_tensor(obs).unsqueeze(0))[0].numpy()
        return int(np.argmax(np.where(mask, q, NEG)))

    def observe(self, obs, a, r, obs2, done, mask2, **kw):
        i = self.ptr
        self.o[i], self.a[i], self.r[i], self.o2[i], self.d[i], self.m2[i] = obs, a, r, obs2, float(done), mask2
        self.ptr, self.size = (i + 1) % self.cap, min(self.size + 1, self.cap)
        self.steps += 1
        if self.steps >= self.learning_starts and self.steps % self.train_every == 0:
            self._update()
        if self.steps % self.target_every == 0:
            self.q_target.load_state_dict(self.q.state_dict())

    def _update(self):
        idx = self.rng.integers(0, self.size, self.batch)
        o, o2 = torch.as_tensor(self.o[idx]), torch.as_tensor(self.o2[idx])
        a, r, d = torch.as_tensor(self.a[idx]), torch.as_tensor(self.r[idx]), torch.as_tensor(self.d[idx])
        m2 = torch.as_tensor(self.m2[idx])
        with torch.no_grad():
            q_next_t = self.q_target(o2).masked_fill(~m2, NEG)
            if self.double:     # online net chooses, target net evaluates (less over-estimation)
                a2 = self.q(o2).masked_fill(~m2, NEG).argmax(1, keepdim=True)
                q_next = q_next_t.gather(1, a2).squeeze(1)
            else:
                q_next = q_next_t.max(1).values
            target = r + self.gamma * (1 - d) * q_next
        q = self.q(o).gather(1, a.unsqueeze(1)).squeeze(1)
        loss = F.smooth_l1_loss(q, target)
        self.opt.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.q.parameters(), 10.0)
        self.opt.step()
        self.losses.append(float(loss))

    def state_dict(self):
        return self.q.state_dict()

    def load_state_dict(self, d):
        self.q.load_state_dict(d)

    def n_params(self):
        return n_params(self.q)

    def policy_module(self):
        return self.q


# ---------------------------------------------------------------------------------------------- PPO
class ActorCritic(nn.Module):
    def __init__(self, obs_dim, n_actions, hidden=(64, 64)):
        super().__init__()
        self.pi = mlp(obs_dim, hidden, n_actions)
        self.v = mlp(obs_dim, hidden, 1)

    def dist(self, obs, mask):
        logits = self.pi(obs).masked_fill(~mask, NEG)
        return torch.distributions.Categorical(logits=logits)


class PPO:
    name = "ppo"

    def __init__(self, obs_dim, n_actions, hidden=(64, 64), lr=3e-4, gamma=0.97, lam=0.95, clip=0.2,
                 rollout=2048, epochs=6, minibatch=256, ent_coef=0.01, vf_coef=0.5, seed=0):
        torch.manual_seed(seed)
        self.ac = ActorCritic(obs_dim, n_actions, hidden)
        self.opt = torch.optim.Adam(self.ac.parameters(), lr=lr, eps=1e-5)
        self.gamma, self.lam, self.clip = gamma, lam, clip
        self.rollout, self.epochs, self.mb = rollout, epochs, minibatch
        self.ent_coef, self.vf_coef = ent_coef, vf_coef
        self.buf = []
        self.steps = 0
        self.losses = []
        self._last = None

    def act(self, obs, mask, explore=True):
        o = torch.as_tensor(obs).unsqueeze(0)
        m = torch.as_tensor(mask).unsqueeze(0)
        with torch.no_grad():
            d = self.ac.dist(o, m)
            a = d.sample() if explore else d.probs.argmax(-1)
            self._last = (float(d.log_prob(a)), float(self.ac.v(o)))
        return int(a)

    def observe(self, obs, a, r, obs2, done, mask2, mask=None):
        logp, v = self._last
        self.buf.append((obs, mask, a, r, done, logp, v))
        self.steps += 1
        if len(self.buf) >= self.rollout and done:   # update at episode boundaries
            self._update(obs2)

    def _update(self, last_obs):
        obs = torch.as_tensor(np.array([b[0] for b in self.buf]))
        masks = torch.as_tensor(np.array([b[1] for b in self.buf]))
        acts = torch.as_tensor([b[2] for b in self.buf])
        rews = np.array([b[3] for b in self.buf], np.float32)
        dones = np.array([b[4] for b in self.buf], np.float32)
        logp_old = torch.as_tensor([b[5] for b in self.buf])
        vals = np.array([b[6] for b in self.buf], np.float32)
        adv = np.zeros_like(rews)
        last = 0.0
        for t in reversed(range(len(rews))):
            nv = 0.0 if dones[t] else (vals[t + 1] if t + 1 < len(vals) else 0.0)
            delta = rews[t] + self.gamma * nv - vals[t]
            last = delta + self.gamma * self.lam * (1 - dones[t]) * last
            adv[t] = last
        ret = torch.as_tensor(adv + vals)
        adv = torch.as_tensor((adv - adv.mean()) / (adv.std() + 1e-8))
        n = len(rews)
        for _ in range(self.epochs):
            perm = torch.randperm(n)
            for s in range(0, n, self.mb):
                i = perm[s:s + self.mb]
                d = self.ac.dist(obs[i], masks[i])
                ratio = torch.exp(d.log_prob(acts[i]) - logp_old[i])
                pg = -torch.min(ratio * adv[i], torch.clamp(ratio, 1 - self.clip, 1 + self.clip) * adv[i]).mean()
                vl = F.mse_loss(self.ac.v(obs[i]).squeeze(-1), ret[i])
                loss = pg + self.vf_coef * vl - self.ent_coef * d.entropy().mean()
                self.opt.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.ac.parameters(), 0.5)
                self.opt.step()
                self.losses.append(float(loss))
        self.buf = []

    def state_dict(self):
        return self.ac.state_dict()

    def load_state_dict(self, d):
        self.ac.load_state_dict(d)

    def n_params(self):
        return n_params(self.ac)

    def policy_module(self):
        return self.ac


def make_agent(algo, obs_dim, n_actions, seed, hidden=(64, 64), **kw):
    if algo == "tabular_q":
        return TabularQ(obs_dim, n_actions, seed=seed, **kw)
    if algo == "dqn":
        return DQN(obs_dim, n_actions, hidden, seed=seed, **kw)
    if algo == "double_dqn":
        return DQN(obs_dim, n_actions, hidden, double=True, seed=seed, **kw)
    if algo == "dueling_dqn":                         # dueling head, plain (max) target: isolates the Double part
        return DQN(obs_dim, n_actions, hidden, dueling=True, seed=seed, **kw)
    if algo == "dueling_double_dqn":
        return DQN(obs_dim, n_actions, hidden, double=True, dueling=True, seed=seed, **kw)
    if algo == "ppo":
        return PPO(obs_dim, n_actions, hidden, seed=seed, **kw)
    raise ValueError(algo)
