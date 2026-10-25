"""Agent E simulator v3: tape-based (common random numbers), event-driven service, balanced 3-objective reward.

WHY v3 (validity fixes over v1/v2, see 02_SIMULATOR_VALIDATION.md):
1. v1/v2 drew arrivals, CSAT noise and abandonment from ONE generator: policies that serve different numbers of
   tickets consumed it differently, so the SAME seed gave DIFFERENT arrivals after ~6 steps (measured). Here the
   whole world of a day (arrivals, ticket attributes, patience times, fallback outcomes, slowdowns, failures) is a
   TAPE generated from the seed before any decision; policies only change what happens to those tickets.
2. Abandonment = each ticket's pre-drawn patience time (Exp, mean patience_q*(1-0.3*emotion), after a 2-min grace):
   deterministic given the tape, and equivalent in distribution to v1's constant hazard.
3. Service is event-driven inside each 5-min step: a work-conserving queue with service rate = sessions, highest
   Intake priority first then arrival order (= callverse/queues/queue.py); a ticket cannot be served before it
   arrives and leaves if its patience expires before service starts.
4. Reward = balanced 3-objective, REFERENCE-normalised (locked on VAL before any RL training, see
   02_SIMULATOR_VALIDATION.md): every ticket has ONE outcome - on time | SLA miss (served late, or by fallback but
   unresolved) | lost (abandoned, or still waiting at day end). Per step
       r_t = -[ w_sla * (miss_t + lost_t) / F_ref  +  w_ab * lost_t / L_ref  +  w_cost * sessions_t / C_ref ]
   = the three business KPIs (SLA failures as in the SLA %, abandonment, cost), each divided by its value under
   planned staffing (Fixed 16 sessions, 200 TRAIN days): F_ref = 1.947, L_ref = 1.656 tickets/step, C_ref = 16.
   Equal weights = a 10 % relative improvement of any KPI is worth the same. Raw-percentage-point weighting was
   rejected: its VAL optimum lost 26 % of customers. Safety stays OUTSIDE the reward (mask + safety layer).
5. Explicit, separate metrics: SLA of HIGH / MEDIUM / LOW tickets and SLA of queue C (urgent problems).
"""

import math
from dataclasses import dataclass

import numpy as np

from env.callcenter_env import A_ACT, A_DEACT, A_FB_OFF, A_FB_ON, A_KEEP, MOVES, N_ACTIONS, N_Q
from env.intake_adapter import LATE_REASONS, QUEUE_REASONS, TicketSampler, priority_vec
from v3.e.scenarios_v3 import PLANNED, SERVICE_MIN, STEP_MIN, STEPS, make_spec

LAMBDA_REF = PLANNED * STEP_MIN / float(np.dot([5.0, 2.6, 1.8, 5.6], SERVICE_MIN) / 15.0)   # arrivals/step at rho=1


@dataclass
class ConfigV3:
    max_sessions: int = 24
    init_active: int = PLANNED
    min_active: int = 6
    min_alloc_urgent: int = 2
    sla_min: tuple = (15.0, 20.0, 5.0, 30.0)
    patience_min: tuple = (25.0, 35.0, 12.0, 40.0)
    service_min: tuple = tuple(SERVICE_MIN)
    priority_w: tuple = (1.0, 1.5, 3.0, 0.8)          # used by the Forecast/Priority rules only
    abandon_grace_min: float = 2.0
    patience_emotion_k: float = 0.3                   # ASSUMPTION
    tier_sla_factor: tuple = (1.5, 1.0, 0.3)          # ASSUMPTION: low / medium / high SLA = queue SLA x factor
    tier_sla_floor: float = 3.0
    fallback_eligible: tuple = (True, False, False, True)
    fallback_speedup: float = 0.45                    # ASSUMPTION
    fallback_fail_p: float = 0.2                      # ASSUMPTION: share of fallback answers that do not resolve
    fallback_max_share: float = 0.25
    session_cost: float = 1.0
    budget_factor: float = 1.15
    step_min: float = STEP_MIN
    steps_per_day: int = STEPS
    # balanced objective (equal importance by default; sensitivity presets in WEIGHTS)
    ref_fail_per_step: float = 1.9469791666666666     # v3/e/results/reward_reference.json (miss + lost)
    ref_lost_per_step: float = 1.6559895833333333
    ref_cost_per_step: float = 16.0
    w_sla: float = 1.0
    w_ab: float = 1.0
    w_cost: float = 1.0
    # OPTIONAL synthetic-satisfaction term (E+F experiment only; SIM-CSAT is a formula, NOT real satisfaction)
    w_csat: float = 0.0
    ref_csat_shortfall_per_step: float = 2.683860109241513   # reward_reference.json (Fixed, 200 TRAIN days)


WEIGHTS = {"equal": (1.0, 1.0, 1.0), "sla_heavy": (2.0, 1.0, 1.0), "abandon_heavy": (1.0, 2.0, 1.0),
           "cost_heavy": (1.0, 1.0, 2.0)}


class EnvV3:
    obs_dim = 43
    n_actions = N_ACTIONS

    def __init__(self, cfg: ConfigV3 | None = None, families=None, f_reward=None):
        self.cfg = c = cfg or ConfigV3()
        self.families = list(families or ["normal"])
        self.sla, self.patience = np.array(c.sla_min), np.array(c.patience_min)
        self.svc, self.pw, self.fb_ok = np.array(c.service_min), np.array(c.priority_w), np.array(c.fallback_eligible)
        self.budget = c.init_active * c.steps_per_day * c.session_cost * c.budget_factor
        self.sampler = TicketSampler()
        self.f_reward = f_reward

    # ------------------------------------------------------------------ tape (exogenous world of one day)
    def build_tape(self, seed: int, family: str | None = None, spec=None):
        ss = np.random.SeedSequence(int(seed))
        r_sc, r_arr, r_att, r_pat, r_out = (np.random.default_rng(s) for s in ss.spawn(5))
        fam = family or self.families[int(r_sc.integers(len(self.families)))]
        spec = spec or make_spec(fam, r_sc)
        c, T = self.cfg, self.cfg.steps_per_day
        x = (np.arange(T) + 0.5) / T
        shape = np.interp(x, (np.arange(8) + 0.5) / 8, spec.shape)
        mix = np.asarray(spec.mix)
        lam_tot = spec.rho * PLANNED * c.step_min / float(np.dot(mix, self.svc))
        lam = lam_tot * mix[None, :] * shape[:, None]                     # [T, 4]
        for q, a, b, m in spec.spikes:
            lam[a:b, q] *= m
        counts = r_arr.poisson(lam)
        rows = []
        for t in range(T):
            for q in range(N_Q):
                n = int(counts[t, q])
                if n:
                    times = np.sort(t * c.step_min + r_arr.uniform(0, c.step_min, n))
                    extra = spec.high_surge[2] if spec.high_surge and spec.high_surge[0] <= t < spec.high_surge[1] else 0.0
                    prio, rank, emo = self._attrs(q, n, r_att, extra)
                    for i in range(n):
                        rows.append((q, times[i], rank[i], prio[i], emo[i]))
        n = len(rows)
        tape = {"q": np.array([r[0] for r in rows], np.int8), "t_arr": np.array([r[1] for r in rows]),
                "rank": np.array([r[2] for r in rows], np.int8), "prio": np.array([r[3] for r in rows], np.float32),
                "emo": np.array([r[4] for r in rows], np.float32),
                "pat_e": r_pat.exponential(1.0, n), "u_fb": r_out.random(n),
                "csat_eps": np.abs(r_out.normal(0, 0.3, n)), "counts": counts, "lam": lam, "spec": spec}
        return tape

    def _attrs(self, q, n, rng, extra_late):
        """Intake fields with the prototype's priority formula; a HIGH-priority surge = more late orders."""
        s = self.sampler
        names, probs = zip(*QUEUE_REASONS[q])
        reasons = rng.choice(len(names), size=n, p=probs)
        sev_base = np.array([s.base.get(names[r], s.base["other"]) for r in reasons])
        late_r = np.array([names[r] in LATE_REASONS for r in reasons])
        late = late_r | (rng.random(n) < min(s.late_share + extra_late, 1.0))
        days = np.round(np.where(late, np.interp(rng.random(n), np.linspace(0, 1, len(s.late_q)), s.late_q), 0.0))
        delivered = np.where(late_r, rng.random(n) < 0.3, rng.random(n) < 0.7)
        paid = np.where(rng.random(n) < s.paid_over, 400.0, 100.0)
        emo = np.where(days > 5, rng.beta(5, 2, n), rng.beta(2, 5, n))
        _, _, emo, score, rank = priority_vec(sev_base, days, delivered, paid, emo, s.cfg)
        return score, rank, emo

    # ------------------------------------------------------------------ gym-style API
    def reset(self, seed: int = 0, family: str | None = None, spec=None):
        c = self.cfg
        self.tape = tp = self.build_tape(seed, family, spec)
        self.spec = tp["spec"]
        sl = np.array(c.tier_sla_factor)[tp["rank"]] * self.sla[tp["q"]]
        self.sla_i = np.maximum(sl, c.tier_sla_floor)
        pat = self.patience[tp["q"]] * (1 - c.patience_emotion_k * tp["emo"])
        self.abandon_at = tp["t_arr"] + c.abandon_grace_min + tp["pat_e"] * pat
        n = len(tp["q"])
        self.status = np.zeros(n, np.int8)       # 0 not arrived/waiting, 1 on time, 2 SLA miss, 3 abandoned, 4 left
        self.wait = np.full(n, np.nan)
        self.fb_used = np.zeros(n, bool)
        order = np.lexsort((tp["t_arr"], tp["q"]))
        self.by_q = [order[tp["q"][order] == q] for q in range(N_Q)]
        self.next_idx = [0] * N_Q                # tickets of queue q with index < next_idx have arrived
        self.queue = [[] for _ in range(N_Q)]    # waiting ticket ids
        self.server_t = np.zeros(N_Q)            # fluid server clock per queue (minutes)
        self.t, self.fallback, self.spent = 0, False, 0.0
        self.alloc = self._proportional(c.init_active)
        self.ewma = np.asarray(tp["lam"][0], float).copy()          # prior forecast = first-step rate (known plan)
        self.last_arr = np.zeros(N_Q)
        self.kpi = dict(cost=0.0, fallback_steps=0, invalid_proposals=0, forced_fb_off=0, failure_removals=0,
                        fb_tickets=0)
        return self._obs(), {"action_mask": self.action_mask(), "family": self.spec.family}

    @property
    def waiting(self):                           # compatibility with the v1/v2 rule baselines (arrival times)
        return [self.tape["t_arr"][np.array(w, int)] if w else np.empty(0) for w in self.queue]

    def _proportional(self, total):
        work = np.array([5.0, 2.6, 1.8, 5.6]) * self.svc          # planned (nominal) work share per queue
        a = np.floor(work / work.sum() * total).astype(int)
        a[2] = max(a[2], self.cfg.min_alloc_urgent)
        while a.sum() < total:
            a[int(np.argmax(work / np.maximum(a, 1)))] += 1
        while a.sum() > total:
            a[int(np.argmax(np.where(np.arange(N_Q) == 2, a - self.cfg.min_alloc_urgent, a)))] -= 1
        return a

    def available_capacity(self):
        f = self.spec.failure
        return self.cfg.max_sessions - (f[2] if f and f[0] <= self.t < f[1] else 0)

    def action_mask(self):
        c, m = self.cfg, np.zeros(N_ACTIONS, bool)
        m[A_KEEP] = True
        for k, (i, j) in enumerate(MOVES, start=1):
            m[k] = self.alloc[i] > (c.min_alloc_urgent if i == 2 else 0)
        m[A_FB_ON] = (not self.fallback) and self.kpi["fallback_steps"] < c.fallback_max_share * c.steps_per_day
        m[A_FB_OFF] = self.fallback
        active, left = int(self.alloc.sum()), c.steps_per_day - self.t
        m[A_ACT] = active < self.available_capacity() and self.spent + (active + 1) * c.session_cost * left <= self.budget
        m[A_DEACT] = active > c.min_active
        return m

    def _apply(self, a):
        if 1 <= a <= 12:
            i, j = MOVES[a - 1]
            self.alloc[i] -= 1
            self.alloc[j] += 1
        elif a == A_FB_ON:
            self.fallback = True
        elif a == A_FB_OFF:
            self.fallback = False
        elif a == A_ACT:
            self.alloc[int(np.argmax(self._load()))] += 1
        elif a == A_DEACT:
            load = self._load()
            cand = [q for q in range(N_Q) if self.alloc[q] > (self.cfg.min_alloc_urgent if q == 2 else 0)]
            self.alloc[min(cand, key=lambda q: load[q])] -= 1

    def _load(self):
        backlog = np.array([len(w) for w in self.queue], float)
        return (backlog + self.ewma) * self.svc / np.maximum(self.alloc, 1)

    def step(self, action: int):
        c, tp = self.cfg, self.tape
        mask = self.action_mask()
        if not (0 <= int(action) < N_ACTIONS) or not mask[int(action)]:
            self.kpi["invalid_proposals"] += 1               # safety layer: invalid proposal -> keep
            action = A_KEEP
        self._apply(int(action))
        while self.alloc.sum() > self.available_capacity():  # exogenous failure removes sessions (lowest priority first)
            for q in np.argsort(self.pw):
                if self.alloc[q] > (c.min_alloc_urgent if q == 2 else 0):
                    self.alloc[q] -= 1
                    self.kpi["failure_removals"] += 1
                    break
        now, end = self.t * c.step_min, (self.t + 1) * c.step_min
        sd = self.spec.slowdown
        slow = sd[2] if sd and sd[0] <= self.t < sd[1] else 1.0
        miss = ab = 0
        self._shortfall = 0.0
        for q in range(N_Q):
            ids = self.by_q[q]
            while self.next_idx[q] < len(ids) and tp["t_arr"][ids[self.next_idx[q]]] < end:
                self.queue[q].append(int(ids[self.next_idx[q]]))
                self.next_idx[q] += 1
            m, a = self._serve(q, now, end, slow)
            miss += m
            ab += a
        arrived_now = np.asarray(tp["counts"][self.t], float)
        self.last_arr = arrived_now
        self.ewma = 0.8 * self.ewma + 0.2 * arrived_now
        cost = float(self.alloc.sum()) * c.session_cost
        self.spent += cost
        self.kpi["cost"] += cost
        self.kpi["fallback_steps"] += int(self.fallback)
        if self.fallback and self.kpi["fallback_steps"] >= c.fallback_max_share * c.steps_per_day:
            self.fallback = False
            self.kpi["forced_fb_off"] += 1
        self.t += 1
        done = self.t >= c.steps_per_day
        left = 0
        if done:                                             # still waiting at day end = not served = counted as lost
            for q in range(N_Q):
                for i in self.queue[q]:
                    self.status[i] = 4
                left += len(self.queue[q])
                self.queue[q] = []
        lost = ab + left
        self._shortfall += lost                            # a lost ticket = SIM-CSAT 1 = shortfall 1
        parts_csat = self._shortfall / c.ref_csat_shortfall_per_step
        parts = {"csat_shortfall": parts_csat, "sla_fail": (miss + lost) / c.ref_fail_per_step, "abandon": lost / c.ref_lost_per_step,
                 "cost": cost / c.ref_cost_per_step, "n_miss": miss, "n_lost": lost}
        reward = -(c.w_sla * parts["sla_fail"] + c.w_ab * parts["abandon"] + c.w_cost * parts["cost"]
                   + c.w_csat * parts_csat)
        info = {"action_mask": self.action_mask(), "reward_parts": parts, "family": self.spec.family}
        return self._obs(), float(reward), done, False, info

    def _serve(self, q, now, end, slow):
        """Event-driven service of queue q during [now, end). Returns (#SLA misses, #abandonments) this step."""
        c, tp = self.cfg, self.tape
        n_sess = int(self.alloc[q])
        tq = max(self.server_t[q], now)
        miss = ab = 0
        w = self.queue[q]
        while w:
            # abandonments that happen before the server is free
            gone = [i for i in w if self.abandon_at[i] <= tq]
            for i in gone:
                self.status[i] = 3
                ab += 1
            if gone:
                w = [i for i in w if self.status[i] == 0]
            if not w or n_sess == 0 or tq >= end:
                break
            ready = [i for i in w if tp["t_arr"][i] <= tq]
            if not ready:
                tq = min(tp["t_arr"][i] for i in w)
                if tq >= end:
                    break
                continue
            i = min(ready, key=lambda k: (-tp["rank"][k], tp["t_arr"][k]))      # HIGH first, then FIFO
            fb = self.fallback and self.fb_ok[q] and tp["rank"][i] < 2              # never fallback for HIGH
            work = self.svc[q] * slow * (c.fallback_speedup if fb else 1.0)
            self.wait[i] = tq - tp["t_arr"][i]
            self.fb_used[i] = fb
            resolved = not (fb and tp["u_fb"][i] < c.fallback_fail_p)
            if resolved:                                    # SIM-CSAT shortfall (5 - csat)/4 of this ticket
                sl = self.sla_i[i]
                cs = min(max(5 - 2 * max(0.0, self.wait[i] - sl / 2) / sl - 0.6 * fb - tp["csat_eps"][i], 1), 5)
                self._shortfall += (5 - cs) / 4
            else:
                self._shortfall += 1.0
            if resolved and self.wait[i] <= self.sla_i[i]:
                self.status[i] = 1
            else:
                self.status[i] = 2
                miss += 1
            self.kpi["fb_tickets"] += int(fb)
            w.remove(i)
            tq += work / n_sess
        # end of step: abandonments of tickets still waiting
        gone = [i for i in w if self.abandon_at[i] <= end]
        for i in gone:
            self.status[i] = 3
            ab += 1
        self.queue[q] = [i for i in w if self.status[i] == 0]
        self.server_t[q] = tq if n_sess else end
        return miss, ab

    def _obs(self):
        c, tp = self.cfg, self.tape
        now = self.t * c.step_min
        f = []
        for q in range(N_Q):
            w = np.array(self.queue[q], int)
            ages = now - tp["t_arr"][w] if len(w) else np.zeros(1)
            ages = np.maximum(ages, 0)
            f += [self.last_arr[q] / 10.0, len(w) / 50.0, float(ages.mean()) / self.sla[q],
                  float(np.percentile(ages, 90)) / self.sla[q], self.alloc[q] / c.max_sessions,
                  self.ewma[q] * self.svc[q] / (c.step_min * max(self.alloc[q], 1))]
        tf = self.t / c.steps_per_day
        f += [self.alloc.sum() / c.max_sessions, self.available_capacity() / c.max_sessions, float(self.fallback),
              max(self.budget - self.spent, 0) / self.budget, tf,
              1 - self.kpi["fallback_steps"] / (c.fallback_max_share * c.steps_per_day), self.ewma.sum() / 10.0]
        for q in range(N_Q):
            w = np.array(self.queue[q], int)
            hi = w[tp["rank"][w] == 2] if len(w) else w
            oldest = float((now - tp["t_arr"][hi]).max()) / max(self.sla[q] * c.tier_sla_factor[2], c.tier_sla_floor) \
                if len(hi) else 0.0
            f += [len(hi) / 20.0, float(tp["prio"][w].mean()) if len(w) else 0.0, max(oldest, 0.0)]
        return np.clip(np.array(f, np.float32), -10, 10)

    # ------------------------------------------------------------------ KPIs of a finished day
    def kpis(self) -> dict:
        tp, st = self.tape, self.status
        n = len(st)
        rank, q = tp["rank"], tp["q"]
        served = (st == 1) | (st == 2)
        waits = self.wait[served]
        sla_i = self.sla_i
        fb_fail = self.fb_used & (tp["u_fb"] < self.cfg.fallback_fail_p)
        formula = np.clip(5 - 2 * np.maximum(0, np.nan_to_num(self.wait) - sla_i / 2) / sla_i
                          - 0.6 * self.fb_used - tp["csat_eps"], 1, 5)
        csat = np.where(served & ~fb_fail, formula, 1.0)     # SIM-CSAT (SYNTHETIC KPI, never a reward here)
        pct = lambda mask_all, mask_ok: 100.0 * mask_ok.sum() / max(mask_all.sum(), 1)
        return {"family": self.spec.family, "rho": self.spec.rho, "arrived": int(n),
                "sla_pct": pct(np.ones(n, bool), st == 1),
                "sla_high_pct": pct(rank == 2, (rank == 2) & (st == 1)),
                "sla_medium_pct": pct(rank == 1, (rank == 1) & (st == 1)),
                "sla_low_pct": pct(rank == 0, (rank == 0) & (st == 1)),
                "sla_queue_c_pct": pct(q == 2, (q == 2) & (st == 1)),
                "abandon_pct": pct(np.ones(n, bool), st == 3),
                "unresolved_end_pct": pct(np.ones(n, bool), st == 4),
                "lost_pct": pct(np.ones(n, bool), (st == 3) | (st == 4)),
                "fb_unresolved_pct": pct(np.ones(n, bool), fb_fail),
                "mean_wait_min": float(waits.mean()) if len(waits) else 0.0,
                "p95_wait_min": float(np.percentile(waits, 95)) if len(waits) else 0.0,
                "cost": float(self.kpi["cost"]), "budget_ok": bool(self.kpi["cost"] <= self.budget + 1e-6),
                "fallback_share": self.kpi["fallback_steps"] / self.cfg.steps_per_day,
                "fallback_ticket_share": self.kpi["fb_tickets"] / max(served.sum(), 1),
                "high_on_fallback": int((self.fb_used & (rank == 2)).sum()),
                "invalid_proposals": int(self.kpi["invalid_proposals"]),
                "safety_interventions": int(self.kpi["forced_fb_off"] + self.kpi["failure_removals"]),
                "sim_csat": float(csat.mean()) if n else 0.0}
