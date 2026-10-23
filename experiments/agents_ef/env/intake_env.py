"""Agent E simulator v2: INTAKE-AWARE. Same queues, actions, safety layer and scenarios as callcenter_env.py, plus:

1. Every arriving ticket carries Intake's structured output (priority_score, priority_label, emotion_intensity),
   computed with the prototype's own formula (env/intake_adapter.py). Agent E never sees message text.
2. Queue discipline = the prototype's Queues (callverse/queues/queue.py): highest priority label first, then
   arrival order. Agent E does not reorder tickets; it only decides CAPACITY (where sessions go, fallback,
   activate/deactivate), which is its job.
3. Observation (43 numbers) = v1's 31 aggregate features + per queue: waiting high-priority tickets, mean waiting
   priority score, oldest high-priority wait / SLA. Aggregates only.
   SLA per ticket = queue SLA x tier_sla_factor[label] (ASSUMPTION: high 0.3x, medium 1x, low 1.5x).
4. Reward = BUSINESS COSTS, not Intake's 60/25/15 weights: +1 per served ticket, minus abandon_tier_w[label] per
   lost ticket, minus late_tier_w[label] per ticket served after its queue SLA, minus session cost, plus SIM-CSAT
   (or Agent F's prediction, see agent_f/f_reward.py). The weights only decide the label; the label decides how
   costly a failure is.
5. Fallback safety: never used for HIGH-priority tickets (they are always served by the full model), and ON for
   at most fallback_max_share of the day (hard cap in the action mask + forced OFF).
6. ASSUMPTION: upset customers are less patient: patience x (1 - patience_emotion_k * emotion_intensity).
"""

import numpy as np

from env.callcenter_env import A_KEEP, N_ACTIONS, N_Q, REWARD_PRESETS, CallCenterEnv, EnvConfig
from env.intake_adapter import TicketSampler

_SAMPLER = None


def sampler():
    global _SAMPLER
    if _SAMPLER is None:
        _SAMPLER = TicketSampler()
    return _SAMPLER


class IntakeAwareEnv(CallCenterEnv):
    obs_dim = 6 * N_Q + 7 + 3 * N_Q
    n_actions = N_ACTIONS

    def __init__(self, config: EnvConfig | None = None, scenarios=("normal", "high", "spike", "drift", "slowdown",
                                                                    "failure"), log_tickets=False, f_reward=None):
        super().__init__(config or EnvConfig(**REWARD_PRESETS["intake"]), scenarios, log_tickets)
        self.sampler = sampler()
        self.f_reward = f_reward              # optional callable: outcome features -> predicted satisfaction (F)

    def reset(self, seed=None, scenario=None):
        self.wprio = [np.empty(0, np.float32) for _ in range(N_Q)]
        self.wrank = [np.empty(0, np.int8) for _ in range(N_Q)]
        self.wemo = [np.empty(0, np.float32) for _ in range(N_Q)]
        obs, info = super().reset(seed, scenario)
        self.kpi.update(arrived_r=np.zeros(3), served_sla_r=np.zeros(3), abandoned_r=np.zeros(3),
                        served_r=np.zeros(3), high_on_fallback=0, fb_served=0, waits_high=[], f_pred=[])
        self.trng = np.random.default_rng((seed or 0) + 7_777_777)   # ticket attributes: own stream
        return self._obs(), info

    def step(self, action: int):
        c = self.cfg
        blocks = self._obs()[:6 * N_Q].reshape(N_Q, 6) if self.log_tickets else None
        mask = self.action_mask()
        if not (0 <= int(action) < N_ACTIONS) or not mask[int(action)]:
            self.kpi["violations"] += 1
            action = A_KEEP
        self._apply(int(action))
        self._enforce_capacity()

        now = self.t * c.step_min
        lam = self._rates(self.t / c.steps_per_day)
        arrivals = self.rng.poisson(lam)
        for q in range(N_Q):
            if arrivals[q]:
                t_arr = np.sort(now + self.rng.uniform(0, c.step_min, arrivals[q]))
                p, r, e = self.sampler.sample(q, int(arrivals[q]), self.trng)
                self.waiting[q] = np.concatenate([self.waiting[q], t_arr])
                self.wprio[q] = np.concatenate([self.wprio[q], p])
                self.wrank[q] = np.concatenate([self.wrank[q], r])
                self.wemo[q] = np.concatenate([self.wemo[q], e])
                self.kpi["arrived_r"] += np.bincount(r, minlength=3)
        self.kpi["arrived"] += arrivals
        self.last_arr = arrivals.astype(float)
        self.ewma = 0.8 * self.ewma + 0.2 * arrivals

        end = now + c.step_min
        served_n = abandon_pen = late_pen = 0.0
        csat_step, f_step = [], []
        slow = self.sc.slow_mult if self.sc.slow_t[0] <= self.t < self.sc.slow_t[1] else 1.0
        tier_ab, tier_late = np.array(c.abandon_tier_w), np.array(c.late_tier_w)
        for q in range(N_Q):
            wq, pr, rk, em = self.waiting[q], self.wprio[q], self.wrank[q], self.wemo[q]
            if len(wq):
                order = np.lexsort((wq, -rk))                    # high label first, then arrival
                wq, pr, rk, em = wq[order], pr[order], rk[order], em[order]
            # 1) service: capacity in minutes of full-model work; fallback tickets cost less, never for HIGH
            fb_q = self.fallback and self.fb_ok[q]
            unit = self.svc[q] * slow
            cost_i = np.where(fb_q & (rk < 2), unit * c.fallback_speedup, unit)
            cap = self.alloc[q] * c.step_min + self.carry[q] * unit
            n = int(np.searchsorted(np.cumsum(cost_i), cap, side="right")) if len(wq) else 0
            used = float(cost_i[:n].sum())
            self.carry[q] = min((cap - used) / unit, 1.0) if n == len(wq) else (cap - used) / unit
            if n:
                waits = np.maximum(now + c.step_min / 2 - wq[:n], 0.0)
                fb_i = fb_q & (rk[:n] < 2)
                # tighter SLA for HIGH tickets, floored at 3 min (below that the 5-min step resolution decides)
                sla_i = np.maximum(self.sla[q] * np.array(c.tier_sla_factor)[rk[:n]], 3.0)
                cs = 5 - 2.0 * np.maximum(0, waits - sla_i / 2) / sla_i \
                    - c.fallback_csat_penalty * fb_i - np.abs(self.rng.normal(0, c.csat_noise, n))
                cs = np.clip(cs, 1, 5)
                in_sla = waits <= sla_i
                self.kpi["served"][q] += n
                self.kpi["served_in_sla"][q] += int(in_sla.sum())
                np.add.at(self.kpi["served_r"], rk[:n], 1)
                np.add.at(self.kpi["served_sla_r"], rk[:n][in_sla], 1)
                self.kpi["waits"].extend(waits.tolist())
                self.kpi["waits_high"].extend(waits[rk[:n] == 2].tolist())
                self.kpi["csat"].extend(cs.tolist())
                self.kpi["fb_served"] += int(fb_i.sum())
                self.kpi["high_on_fallback"] += int((fb_q & (rk[:n] == 2) & (cost_i[:n] < unit)).sum())
                csat_step.extend(cs.tolist())
                if self.f_reward is not None:
                    f_step.extend(self.f_reward(q, waits / sla_i, fb_i, rk[:n], em[:n]).tolist())
                served_n += n
                late_pen += float(tier_late[rk[:n][~in_sla]].sum())
                if self.log_tickets:
                    for w_, c_, f_, r_ in zip(waits, cs, fb_i, rk[:n]):
                        self.tickets.append({"queue": q, "t": self.t, "wait": float(w_), "fallback": bool(f_),
                                             "abandoned": False, "csat_sim": float(c_), "rank": int(r_),
                                             "state": blocks[q].tolist(), "scenario": self.sc.kind})
                wq, pr, rk, em = wq[n:], pr[n:], rk[n:], em[n:]
            # 2) abandonment: emotion shortens patience (assumption), after the grace period
            if len(wq):
                exposed = np.clip(end - np.maximum(wq + c.abandon_grace_min, now), 0, c.step_min)
                pat = self.patience[q] * (1 - c.patience_emotion_k * em)
                leave = self.rng.random(len(wq)) < 1 - np.exp(-exposed / pat)
                if leave.any():
                    self.kpi["abandoned"][q] += int(leave.sum())
                    np.add.at(self.kpi["abandoned_r"], rk[leave], 1)
                    self.kpi["csat"].extend([1.0] * int(leave.sum()))
                    abandon_pen += float(tier_ab[rk[leave]].sum())
                    if self.f_reward is not None:
                        f_step.extend([1.0] * int(leave.sum()))
                    if self.log_tickets:
                        for a_, r_ in zip(wq[leave], rk[leave]):
                            self.tickets.append({"queue": q, "t": self.t, "wait": float(end - a_), "fallback": False,
                                                 "abandoned": True, "csat_sim": 1.0, "rank": int(r_),
                                                 "state": blocks[q].tolist(), "scenario": self.sc.kind})
                    keep = ~leave
                    wq, pr, rk, em = wq[keep], pr[keep], rk[keep], em[keep]
            self.waiting[q], self.wprio[q], self.wrank[q], self.wemo[q] = wq, pr, rk, em

        cost = self.alloc.sum() * c.session_cost
        self.spent += cost
        self.kpi["cost"] += cost
        self.kpi["fallback_steps"] += int(self.fallback)
        if c.fallback_max_share < 1.0 and self.fallback and \
                self.kpi["fallback_steps"] >= c.fallback_max_share * c.steps_per_day:
            self.fallback = False
        self.kpi["f_pred"].extend(f_step)

        norm = float(self.base.sum())
        sat = f_step if self.f_reward is not None else csat_step          # which satisfaction signal is rewarded
        coverage = min(len(csat_step) / max(lam.sum(), 1e-6), 1.0)
        csat_term = (np.mean(sat) - 3.0) / 2.0 * coverage if sat else 0.0
        reward = (c.w_served * served_n / norm - c.w_abandon * abandon_pen / norm - c.w_sla * late_pen / norm
                  - c.w_cost * cost / (c.init_active * c.session_cost) + c.w_csat * csat_term)
        self.t += 1
        done = self.t >= c.steps_per_day
        info = {"action_mask": self.action_mask(), "scenario": self.sc.kind,
                "reward_parts": dict(served=served_n / norm, abandon=abandon_pen / norm, late=late_pen / norm,
                                     cost=cost / (c.init_active * c.session_cost), csat=csat_term)}
        return self._obs(), float(reward), done, False, info

    def _obs(self) -> np.ndarray:
        base = super()._obs()
        now = self.t * self.cfg.step_min
        extra = []
        for q in range(N_Q):
            rk = self.wrank[q] if hasattr(self, "wrank") else np.empty(0)
            hi = rk == 2
            oldest = float((now - self.waiting[q][hi]).max()) / (self.sla[q] * self.cfg.tier_sla_factor[2]) \
                if hi.any() else 0.0
            mean_p = float(self.wprio[q].mean()) if len(rk) else 0.0
            extra += [hi.sum() / 20.0, mean_p, oldest]
        return np.clip(np.concatenate([base, np.array(extra, np.float32)]), -10, 10).astype(np.float32)

    def episode_kpis(self) -> dict:
        k = super().episode_kpis()
        kp = self.kpi
        k["c_queue_sla_pct"] = k["urgent_sla_pct"]                       # v1 meaning (queue C)
        k["urgent_sla_pct"] = 100 * kp["served_sla_r"][2] / max(kp["arrived_r"][2], 1)   # HIGH-priority tickets
        k["abandon_high_pct"] = 100 * kp["abandoned_r"][2] / max(kp["arrived_r"][2], 1)
        k["abandon_low_pct"] = 100 * kp["abandoned_r"][0] / max(kp["arrived_r"][0], 1)
        k["p95_wait_high_min"] = float(np.percentile(kp["waits_high"], 95)) if kp["waits_high"] else 0.0
        k["high_on_fallback"] = int(kp["high_on_fallback"])
        k["fallback_ticket_share"] = kp["fb_served"] / max(kp["served"].sum(), 1)
        if kp["f_pred"]:                                                 # only when Agent F's reward is used
            k["f_pred_mean"] = float(np.mean(kp["f_pred"]))
        return k
