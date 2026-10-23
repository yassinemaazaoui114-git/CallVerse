"""Classical (non-learning) Agent E policies. Each one sees only what the RL agents see (env state now / past).

- fixed:      keep the starting proportional allocation all day (does nothing).
- threshold:  move one session from the least loaded to the most loaded queue when the gap is big;
              fallback ON when the simple queues are overloaded, OFF when calm.
- priority:   like threshold, but load is weighted by priority, so urgent/refund queues are served first.
- forecast:   EWMA arrival forecast -> required sessions per queue (offered load + square-root safety staffing,
              the Erlang "square-root staffing" rule of thumb); moves one session toward that target per step,
              activates/deactivates sessions within capacity and budget.
Every action still goes through the environment's mask and safety layer.
"""

import numpy as np

from env.callcenter_env import A_ACT, A_DEACT, A_FB_OFF, A_FB_ON, A_KEEP, MOVES, N_Q


def _move(i: int, j: int) -> int:
    return MOVES.index((i, j)) + 1


def _load(env) -> np.ndarray:
    backlog = np.array([len(w) for w in env.waiting], float)
    return (backlog + env.ewma) * env.svc / np.maximum(env.alloc, 1)     # minutes of work per session


class Fixed:
    name = "fixed"

    def act(self, env, obs, mask):
        return A_KEEP


class Threshold:
    name = "threshold"
    weighted = False

    def act(self, env, obs, mask):
        load = _load(env) * (env.pw if self.weighted else 1.0)
        backlog = np.array([len(w) for w in env.waiting])
        simple_backlog = backlog[env.fb_ok].sum()
        if not env.fallback and simple_backlog > 25 and mask[A_FB_ON]:
            return A_FB_ON
        if env.fallback and simple_backlog < 6 and mask[A_FB_OFF]:
            return A_FB_OFF
        hi, lo = int(np.argmax(load)), int(np.argmin(load))
        if load[hi] > 2.0 * max(load[lo], 1.0) and hi != lo:
            a = _move(lo, hi)
            if mask[a]:
                return a
        return A_KEEP


class Priority(Threshold):
    name = "priority"
    weighted = True


class Forecast:
    """Square-root staffing on an EWMA forecast. z = safety-staffing factor (0.5 = default); sweeping z traces the
    heuristic's cost-vs-service frontier (bench/frontier.py)."""
    name = "forecast"

    def __init__(self, z: float = 0.5):
        self.z = z

    def act(self, env, obs, mask):
        c = env.cfg
        backlog = np.array([len(w) for w in env.waiting], float)
        svc = env.svc * np.where(env.fallback & env.fb_ok, c.fallback_speedup, 1.0)
        offered = env.ewma * svc / c.step_min + backlog * svc / (3 * c.step_min)   # sessions needed
        need = offered + self.z * np.sqrt(offered) * env.pw / env.pw.mean()
        need[2] = max(need[2], c.min_alloc_urgent)
        total_need = need.sum()
        active = env.alloc.sum()
        simple_backlog = backlog[env.fb_ok].sum()
        if not env.fallback and simple_backlog > 25 and mask[A_FB_ON]:
            return A_FB_ON
        if env.fallback and simple_backlog < 6 and mask[A_FB_OFF]:
            return A_FB_OFF
        if total_need > active + 0.8 and mask[A_ACT]:
            return A_ACT
        if total_need < active - 1.5 and mask[A_DEACT]:
            return A_DEACT
        gap = need - env.alloc
        hi, lo = int(np.argmax(gap)), int(np.argmin(gap))
        if gap[hi] > 0.7 and gap[lo] < -0.3:
            a = _move(lo, hi)
            if mask[a]:
                return a
        return A_KEEP


def erlang_c_wait_prob(c: int, a: float) -> float:
    """P(wait > 0) in an M/M/c queue with offered load a = lambda / mu (Erlang C)."""
    if c <= a:
        return 1.0
    s, term = 1.0, 1.0
    for k in range(1, c):
        term *= a / k
        s += term
    term *= a / c
    pc = term * c / (c - a)
    return pc / (s + pc)


class ErlangC:
    """Classical call-centre staffing: per queue, the fewest sessions c such that
    P(wait > SLA) = C(c, a) * exp(-(c*mu - lambda) * SLA) <= target, with lambda from the EWMA forecast (+ backlog)
    and mu = 1 / service time. Same action mechanics and fallback rule as Forecast. Strong textbook baseline."""
    name = "erlang_c"

    def __init__(self, target: float = 0.2):
        self.target = target

    def need(self, env):
        c = env.cfg
        backlog = np.array([len(w) for w in env.waiting], float)
        out = np.zeros(len(backlog))
        for q in range(len(backlog)):
            svc = env.svc[q] * (c.fallback_speedup if (env.fallback and env.fb_ok[q]) else 1.0)
            lam = (env.ewma[q] + backlog[q] / 3) / c.step_min          # per minute
            mu = 1.0 / svc
            a = lam / mu
            k = max(1, int(np.floor(a)) + 1)
            while k < c.max_sessions and erlang_c_wait_prob(k, a) * np.exp(-(k * mu - lam) * env.sla[q]) > self.target:
                k += 1
            out[q] = k if lam > 0 else 0
        out[2] = max(out[2], c.min_alloc_urgent)
        return out

    def act(self, env, obs, mask):
        need = self.need(env)
        backlog = np.array([len(w) for w in env.waiting], float)
        simple_backlog = backlog[env.fb_ok].sum()
        if not env.fallback and simple_backlog > 25 and mask[A_FB_ON]:
            return A_FB_ON
        if env.fallback and simple_backlog < 6 and mask[A_FB_OFF]:
            return A_FB_OFF
        active = env.alloc.sum()
        if need.sum() > active + 0.5 and mask[A_ACT]:
            return A_ACT
        if need.sum() < active - 1.5 and mask[A_DEACT]:
            return A_DEACT
        gap = need - env.alloc
        hi, lo = int(np.argmax(gap)), int(np.argmin(gap))
        if gap[hi] > 0.5 and gap[lo] < -0.5:
            a = _move(lo, hi)
            if mask[a]:
                return a
        return A_KEEP


BASELINES = {p.name: p for p in (Fixed, Threshold, Priority, Forecast)}
BASELINES_V2 = {p.name: p for p in (Fixed, Threshold, Priority, Forecast, ErlangC)}
