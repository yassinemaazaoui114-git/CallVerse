"""Extra Agent E v3 baselines (the v1/v2 rules in baselines/heuristics.py also run on EnvV3 unchanged).

RandomValid  uniform over the VALID actions only (the mask), seeded: the "no intelligence" floor.
FluidMPC     economical model-predictive control: for every valid action, roll a deterministic FLUID model of the
             4 queues forward H steps (demand = current EWMA forecast, sessions held after the action) and pick the
             action with the lowest predicted balanced cost (the SAME reference-normalised objective as env_v3).
             Fluid approximations: backlog_{k+1} = max(0, backlog_k + lambda - capacity); misses ~ tickets that
             would wait longer than the SLA (backlog beyond SLA-minutes of capacity) + fallback failures;
             abandonment ~ backlog * step / patience. A pure fluid model ignores randomness and under-staffs, so
             demand is inflated by k*sqrt(lambda) (square-root safety staffing); k is chosen on VAL only.
             No future information, no learning: a planning baseline.
"""

import numpy as np

from env.callcenter_env import A_ACT, A_DEACT, A_FB_OFF, A_FB_ON, MOVES


class RandomValid:
    name = "random_valid"

    def __init__(self, seed=0):
        self.rng = np.random.default_rng(seed)

    def act(self, env, obs, mask):
        return int(self.rng.choice(np.flatnonzero(mask)))


class FluidMPC:
    name = "fluid_mpc"

    def __init__(self, horizon=6, k=0.0):
        self.h, self.k = horizon, k            # k: square-root safety margin on forecast demand (tuned on VAL)
        self.name = f"fluid_mpc_k{k:g}"

    def _after(self, env, a):
        alloc, fb = env.alloc.copy(), env.fallback
        if 1 <= a <= 12:
            i, j = MOVES[a - 1]
            alloc[i] -= 1
            alloc[j] += 1
        elif a == A_FB_ON:
            fb = True
        elif a == A_FB_OFF:
            fb = False
        elif a == A_ACT:
            alloc[int(np.argmax(env._load()))] += 1
        elif a == A_DEACT:
            load = env._load()
            cand = [q for q in range(4) if alloc[q] > (env.cfg.min_alloc_urgent if q == 2 else 0)]
            alloc[min(cand, key=lambda q: load[q])] -= 1
        return alloc, fb

    def cost(self, env, a):
        c = env.cfg
        alloc, fb = self._after(env, a)
        fb_left = max(0, c.fallback_max_share * c.steps_per_day - env.kpi["fallback_steps"])
        backlog = np.array([len(w) for w in env.queue], float)
        lam = env.ewma + self.k * np.sqrt(np.maximum(env.ewma, 0))   # deterministic fluid model is optimistic
        total = 0.0
        for k in range(self.h):
            use_fb = fb and k < fb_left
            svc = env.svc * np.where(use_fb & env.fb_ok, c.fallback_speedup, 1.0)
            cap = alloc * c.step_min / svc                        # tickets per step
            backlog = backlog + lam
            served = np.minimum(backlog, cap)
            backlog = backlog - served
            sla_cap = cap * env.sla / c.step_min                  # tickets servable within one SLA
            misses = np.maximum(0.0, backlog - sla_cap).sum()
            if use_fb:
                misses += (served * env.fb_ok).sum() * c.fallback_fail_p * 0.85   # ~85 % of A/D tickets are not HIGH
            lost = (backlog * c.step_min / env.patience).sum()
            backlog = np.maximum(0.0, backlog - backlog * c.step_min / env.patience)
            total += (c.w_sla * (misses + lost) / c.ref_fail_per_step + c.w_ab * lost / c.ref_lost_per_step
                      + c.w_cost * alloc.sum() / c.ref_cost_per_step)          # same objective as the env reward
        return total

    def act(self, env, obs, mask):
        valid = np.flatnonzero(mask)
        costs = [self.cost(env, int(a)) for a in valid]
        return int(valid[int(np.argmin(costs))])
