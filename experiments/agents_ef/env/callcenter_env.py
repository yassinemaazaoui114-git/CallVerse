"""CallVerse service-capacity simulator for Agent E (Demand & Staffing, model M6). RESEARCH CODE, not the prototype.

One episode = one simulated working day (8 h) in 5-minute steps (96 decisions). Four queues mirror CallVerse:
  A status/tracking, B payment/refund, C urgent problems, D availability/supply.
Every step: requests arrive (Poisson, time-of-day profile, scenario effects), AI sessions serve them FIFO,
waiting customers may abandon, and Agent E picks ONE action (Discrete, 17 choices):
  0 keep | 1-12 move one session from queue i to queue j | 13 fallback ON | 14 fallback OFF
  15 activate one idle session | 16 deactivate one session
Fallback = a cheaper/faster model for SIMPLE queues only (A, D). It is never used for C (urgent) or B (money).

Safety (hard constraints, enforced here, not learned):
- an action mask says which actions are valid; an invalid action is replaced by "keep" and counted as a violation;
- total active sessions <= available capacity (failures reduce it) and the day's budget is never exceeded;
- the urgent queue C always keeps at least `min_alloc_urgent` sessions;
- the observation only contains the past and present (no future arrivals).

SIM-CSAT v0 (TEMPORARY satisfaction signal, NOT Agent F): per served request
  csat = 5 - 2.0*max(0, wait - SLA/2)/SLA - 0.6*fallback - noise   (clipped to 1..5); an abandoned request = 1.
It is a documented stand-in so Agent E can be trained before Agent F exists. All numbers below are synthetic
assumptions (no real CallVerse operational data exists yet); results are SIMULATOR results only.
"""

from dataclasses import dataclass, field

import numpy as np

QUEUES = ["A_status", "B_refund", "C_urgent", "D_availability"]
N_Q = 4
MOVES = [(i, j) for i in range(N_Q) for j in range(N_Q) if i != j]          # 12 (from, to) pairs
A_KEEP, A_FB_ON, A_FB_OFF, A_ACT, A_DEACT = 0, 13, 14, 15, 16
N_ACTIONS = 17
SCENARIOS = ["normal", "high", "spike", "drift", "slowdown", "failure", "compound"]   # "compound" = test only


@dataclass
class EnvConfig:
    step_min: float = 5.0
    steps_per_day: int = 96
    max_sessions: int = 24                    # hard capacity cap (AI sessions that may run at once)
    init_active: int = 16
    min_active: int = 6
    min_alloc_urgent: int = 2
    priority_w: tuple = (1.0, 1.5, 3.0, 0.8)  # A, B, C, D
    sla_min: tuple = (15.0, 20.0, 5.0, 30.0)
    patience_min: tuple = (25.0, 35.0, 12.0, 40.0)
    service_min: tuple = (4.0, 8.0, 6.0, 3.0)  # minutes per request per session (normal model)
    base_rate: tuple = (5.0, 2.6, 1.8, 5.6)     # arrivals per 5-min step at the daily average (peaks need
                                               # more than init_active sessions: real staffing tension)
    abandon_grace_min: float = 2.0             # nobody hangs up in the first 2 minutes
    fallback_eligible: tuple = (True, False, False, True)
    fallback_speedup: float = 0.45             # service time x 0.45 with the cheap/fast model
    fallback_csat_penalty: float = 0.6
    session_cost: float = 1.0                  # cost units per active session per step
    budget_factor: float = 1.15                # day budget = init_active * steps * cost * factor
    csat_noise: float = 0.3
    # reward weights (see REWARD_PRESETS); components are normalized per step
    w_served: float = 1.0
    w_abandon: float = 2.0
    w_sla: float = 0.0
    w_cost: float = 0.5
    w_csat: float = 1.0


REWARD_PRESETS = {
    # wait time is already inside SIM-CSAT, so the SLA term is 0 by default to avoid double counting
    "balanced": dict(w_served=1.0, w_abandon=2.0, w_sla=0.0, w_cost=0.5, w_csat=1.0),
    "cost_heavy": dict(w_served=1.0, w_abandon=2.0, w_sla=0.0, w_cost=1.5, w_csat=1.0),
    "sla_heavy": dict(w_served=1.0, w_abandon=2.0, w_sla=1.0, w_cost=0.5, w_csat=0.5),
}


def profile(t_frac: float) -> float:
    """Daily arrival shape (mean ~1): a morning peak and an afternoon peak."""
    return 0.55 + 0.6 * np.exp(-((t_frac - 0.3) / 0.12) ** 2) + 0.5 * np.exp(-((t_frac - 0.72) / 0.1) ** 2)


@dataclass
class Scenario:
    """Everything random about one day, drawn ONCE from the seed, so a seed always gives the same day."""
    kind: str
    load: float = 1.0
    mix_end: np.ndarray = field(default_factory=lambda: np.ones(N_Q))   # drift: category mix at day end
    spike_q: int = -1
    spike_t: tuple = (0, 0)
    spike_mult: float = 1.0
    slow_t: tuple = (0, 0)
    slow_mult: float = 1.0
    fail_t: tuple = (0, 0)
    fail_lost: int = 0


def make_scenario(kind: str, rng: np.random.Generator, steps: int) -> Scenario:
    sc = Scenario(kind=kind, load=float(rng.uniform(0.9, 1.05)))
    if kind == "high":
        sc.load = float(rng.uniform(1.25, 1.4))
    if kind in ("spike", "compound"):
        sc.spike_q = int(rng.integers(N_Q))
        start = int(rng.integers(steps // 6, steps - 20))
        sc.spike_t = (start, start + int(rng.integers(6, 14)))
        sc.spike_mult = float(rng.uniform(2.5, 4.0))
    if kind == "drift":
        sc.mix_end = rng.uniform(0.5, 1.8, N_Q)
    if kind in ("slowdown", "compound"):
        start = int(rng.integers(steps // 8, steps // 2))
        sc.slow_t = (start, start + int(rng.integers(15, 30)))
        sc.slow_mult = float(rng.uniform(1.3, 1.7))
    if kind == "failure":
        start = int(rng.integers(steps // 8, steps // 2))
        sc.fail_t = (start, start + int(rng.integers(10, 25)))
        sc.fail_lost = int(rng.integers(4, 9))
    return sc


class CallCenterEnv:
    """Gymnasium-style API (reset/step) without the gymnasium dependency."""

    obs_dim = 6 * N_Q + 7
    n_actions = N_ACTIONS

    def __init__(self, config: EnvConfig | None = None, scenarios=("normal", "high", "spike", "drift",
                                                                    "slowdown", "failure")):
        self.cfg = config or EnvConfig()
        self.scenario_kinds = list(scenarios)
        c = self.cfg
        self.pw = np.array(c.priority_w)
        self.sla = np.array(c.sla_min)
        self.patience = np.array(c.patience_min)
        self.svc = np.array(c.service_min)
        self.base = np.array(c.base_rate)
        self.fb_ok = np.array(c.fallback_eligible)
        self.budget = c.init_active * c.steps_per_day * c.session_cost * c.budget_factor

    # ------------------------------------------------------------------ reset / step
    def reset(self, seed: int, scenario: str | None = None):
        c = self.cfg
        self.rng = np.random.default_rng(seed)
        kind = scenario or self.scenario_kinds[int(self.rng.integers(len(self.scenario_kinds)))]
        self.sc = make_scenario(kind, self.rng, c.steps_per_day)
        self.t = 0
        self.fallback = False
        self.alloc = self._proportional(c.init_active)
        self.waiting = [np.empty(0) for _ in range(N_Q)]     # arrival times (minutes) of waiting requests
        self.carry = np.zeros(N_Q)                           # fractional service capacity carried over
        self.spent = 0.0
        self.last_arr = np.zeros(N_Q)
        self.ewma = self.base * profile(0.0) * self.sc.load
        self.kpi = dict(arrived=np.zeros(N_Q), served=np.zeros(N_Q), abandoned=np.zeros(N_Q),
                        served_in_sla=np.zeros(N_Q), waits=[], csat=[], cost=0.0, violations=0,
                        invalid_attempts=0, fallback_steps=0, urgent_fallback=0)
        return self._obs(), {"action_mask": self.action_mask(), "scenario": kind}

    def _proportional(self, total: int) -> np.ndarray:
        """Sessions per queue proportional to expected work (arrival rate x service time), urgent minimum kept."""
        work = self.base * self.svc
        a = np.floor(work / work.sum() * total).astype(int)
        a[2] = max(a[2], self.cfg.min_alloc_urgent)
        while a.sum() < total:
            a[int(np.argmax(work / np.maximum(a, 1)))] += 1
        while a.sum() > total:
            k = int(np.argmax(np.where(np.arange(N_Q) == 2, a - self.cfg.min_alloc_urgent, a)))
            a[k] -= 1
        return a

    def available_capacity(self) -> int:
        lost = self.sc.fail_lost if self.sc.fail_t[0] <= self.t < self.sc.fail_t[1] else 0
        return self.cfg.max_sessions - lost

    def action_mask(self) -> np.ndarray:
        c, m = self.cfg, np.zeros(N_ACTIONS, dtype=bool)
        m[A_KEEP] = True
        for k, (i, j) in enumerate(MOVES, start=1):
            floor = c.min_alloc_urgent if i == 2 else 0
            m[k] = self.alloc[i] > floor
        m[A_FB_ON] = not self.fallback
        m[A_FB_OFF] = self.fallback
        active = int(self.alloc.sum())
        steps_left = c.steps_per_day - self.t
        affordable = self.spent + (active + 1) * c.session_cost * steps_left <= self.budget
        m[A_ACT] = active < self.available_capacity() and affordable
        m[A_DEACT] = active > c.min_active
        return m

    def step(self, action: int):
        c = self.cfg
        mask = self.action_mask()
        if not (0 <= int(action) < N_ACTIONS) or not mask[int(action)]:
            self.kpi["violations"] += 1          # safety layer: an invalid proposal becomes "keep"
            action = A_KEEP
        self._apply(int(action))
        self._enforce_capacity()

        now = self.t * c.step_min
        t_frac = self.t / c.steps_per_day
        lam = self._rates(t_frac)
        arrivals = self.rng.poisson(lam)
        for q in range(N_Q):                      # arrivals spread uniformly inside the step
            if arrivals[q]:
                self.waiting[q] = np.concatenate([self.waiting[q], np.sort(now + self.rng.uniform(0, c.step_min,
                                                                                                   arrivals[q]))])
        self.kpi["arrived"] += arrivals
        self.last_arr = arrivals.astype(float)
        self.ewma = 0.8 * self.ewma + 0.2 * arrivals

        end = now + c.step_min
        served_w = abandon_w = late_w = 0.0
        csat_step = []
        slow = self.sc.slow_mult if self.sc.slow_t[0] <= self.t < self.sc.slow_t[1] else 1.0
        for q in range(N_Q):
            wq = self.waiting[q]
            # 1) service first: sessions x minutes / service time (faster with fallback on eligible queues)
            svc = self.svc[q] * slow * (c.fallback_speedup if (self.fallback and self.fb_ok[q]) else 1.0)
            cap = self.alloc[q] * c.step_min / svc + self.carry[q]
            n = int(min(np.floor(cap), len(wq)))
            self.carry[q] = min(cap - n, 1.0) if n == len(wq) else cap - n
            if n:
                waits = np.maximum(now + c.step_min / 2 - wq[:n], 0.0)       # served around mid-step
                wq = wq[n:]
                fb = self.fallback and self.fb_ok[q]
                cs = 5 - 2.0 * np.maximum(0, waits - self.sla[q] / 2) / self.sla[q] \
                    - (c.fallback_csat_penalty if fb else 0) - np.abs(self.rng.normal(0, c.csat_noise, n))
                cs = np.clip(cs, 1, 5)
                self.kpi["served"][q] += n
                self.kpi["served_in_sla"][q] += int((waits <= self.sla[q]).sum())
                self.kpi["waits"].extend(waits.tolist())
                self.kpi["csat"].extend(cs.tolist())
                csat_step.extend(cs.tolist())
                served_w += self.pw[q] * n
                late_w += self.pw[q] * int((waits > self.sla[q]).sum())
            # 2) then abandonment of those still waiting: hazard 1/patience after a short grace period
            if len(wq):
                exposed = np.clip(end - np.maximum(wq + c.abandon_grace_min, now), 0, c.step_min)
                leave = self.rng.random(len(wq)) < 1 - np.exp(-exposed / self.patience[q])
                n_ab = int(leave.sum())
                if n_ab:
                    self.kpi["abandoned"][q] += n_ab
                    self.kpi["csat"].extend([1.0] * n_ab)
                    abandon_w += self.pw[q] * n_ab
                    wq = wq[~leave]
            self.waiting[q] = wq

        cost = self.alloc.sum() * c.session_cost
        self.spent += cost
        self.kpi["cost"] += cost
        self.kpi["fallback_steps"] += int(self.fallback)

        norm = float((self.base * self.pw).sum())        # typical weighted arrivals per step
        csat_term = (np.mean(csat_step) - 3.0) / 2.0 * min(len(csat_step) / max(lam.sum(), 1e-6), 1.0) \
            if csat_step else 0.0
        reward = (c.w_served * served_w / norm - c.w_abandon * abandon_w / norm - c.w_sla * late_w / norm
                  - c.w_cost * cost / (c.init_active * c.session_cost) + c.w_csat * csat_term)
        self.t += 1
        done = self.t >= c.steps_per_day
        info = {"action_mask": self.action_mask(), "scenario": self.sc.kind,
                "reward_parts": dict(served=served_w / norm, abandon=abandon_w / norm, late=late_w / norm,
                                     cost=cost / (c.init_active * c.session_cost), csat=csat_term)}
        return self._obs(), float(reward), done, False, info

    # ------------------------------------------------------------------ helpers
    def _rates(self, t_frac: float) -> np.ndarray:
        sc = self.sc
        mix = 1 + (sc.mix_end - 1) * t_frac
        lam = self.base * profile(t_frac) * sc.load * mix
        if sc.spike_q >= 0 and sc.spike_t[0] <= self.t < sc.spike_t[1]:
            lam[sc.spike_q] *= sc.spike_mult
        return lam

    def _apply(self, a: int):
        if 1 <= a <= 12:
            i, j = MOVES[a - 1]
            self.alloc[i] -= 1
            self.alloc[j] += 1
        elif a == A_FB_ON:
            self.fallback = True
        elif a == A_FB_OFF:
            self.fallback = False
        elif a == A_ACT:
            work = self._load_per_session()
            self.alloc[int(np.argmax(work))] += 1          # new session goes to the busiest queue
        elif a == A_DEACT:
            work = self._load_per_session()
            cand = [q for q in range(N_Q) if self.alloc[q] > (self.cfg.min_alloc_urgent if q == 2 else 0)]
            self.alloc[min(cand, key=lambda q: work[q])] -= 1

    def _load_per_session(self) -> np.ndarray:
        backlog = np.array([len(w) for w in self.waiting], float)
        return (backlog + self.ewma) * self.svc / np.maximum(self.alloc, 1)

    def _enforce_capacity(self):
        """A failure removes sessions (an event of the world, not a decision): lowest-priority queues first."""
        while self.alloc.sum() > self.available_capacity():
            order = np.argsort(self.pw)
            for q in order:
                if self.alloc[q] > (self.cfg.min_alloc_urgent if q == 2 else 0):
                    self.alloc[q] -= 1
                    break

    def _obs(self) -> np.ndarray:
        c = self.cfg
        now = self.t * c.step_min
        f = []
        for q in range(N_Q):
            wq = self.waiting[q]
            ages = now - wq if len(wq) else np.zeros(1)
            f += [self.last_arr[q] / 10.0, len(wq) / 50.0, float(ages.mean()) / self.sla[q],
                  float(np.percentile(ages, 90)) / self.sla[q], self.alloc[q] / c.max_sessions,
                  self.ewma[q] * self.svc[q] / (c.step_min * max(self.alloc[q], 1))]
        tf = self.t / c.steps_per_day
        f += [self.alloc.sum() / c.max_sessions, self.available_capacity() / c.max_sessions, float(self.fallback),
              max(self.budget - self.spent, 0) / self.budget, np.sin(2 * np.pi * tf), np.cos(2 * np.pi * tf),
              self.ewma.sum() / 10.0]
        return np.clip(np.array(f, dtype=np.float32), -10, 10)

    # ------------------------------------------------------------------ episode KPIs
    def episode_kpis(self) -> dict:
        k = self.kpi
        arrived = k["arrived"].sum()
        waits = np.array(k["waits"]) if k["waits"] else np.zeros(1)
        return {
            "scenario": self.sc.kind,
            "arrived": int(arrived),
            "handled_pct": 100 * k["served"].sum() / max(arrived, 1),
            "abandon_pct": 100 * k["abandoned"].sum() / max(arrived, 1),
            "sla_pct": 100 * k["served_in_sla"].sum() / max(arrived, 1),
            "urgent_sla_pct": 100 * k["served_in_sla"][2] / max(k["arrived"][2], 1),
            "mean_wait_min": float(waits.mean()),
            "p95_wait_min": float(np.percentile(waits, 95)),
            "sim_csat": float(np.mean(k["csat"])) if k["csat"] else 0.0,
            "cost": float(k["cost"]),
            "budget_ok": bool(k["cost"] <= self.budget + 1e-6),
            "violations": int(k["violations"]),
            "fallback_share": k["fallback_steps"] / self.cfg.steps_per_day,
            "end_backlog": int(sum(len(w) for w in self.waiting)),
        }
