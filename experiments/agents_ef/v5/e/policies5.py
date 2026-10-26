"""Agent E v5 policy factory = the V4 grammar (v4/e/policies.py) + decision PROVENANCE + runtime hysteresis.

Same semantics as V4 for every spec it re-implements (floor@k / shield@t / guarded / mpcguard / rl / rule); checked
in NOTEBOOK: identical DEV rows to the v4 CSVs. Re-implemented here only so that each step records WHO decided:
  prov = "rl"            the RL network's own greedy choice over the FULL valid mask (unconstrained decision)
         "rl_rechoice"   the shield removed the RL's first choice; the RL picked its best action INSIDE the
                         shielded mask (the RL still decides, but constrained)
         "owner"         the classical owner rule (guarded = Forecast z=0.25, mpcguard = MPC k=0.5) decided the
                         capacity level (activate / deactivate), or replaced an RL activate/deactivate
         "rule"          a pure classical rule decided
         "shield_default" the shield replaced a RULE's action by its deterministic default (move into C / keep)
and `intervened` = the executed action differs from what the same controller would do WITHOUT the shield
(counterfactual call of the inner policy on the unshielded mask; all inner policies are deterministic and stateless).
This is what E2 needs: intervention rate, replacement rate, and how many decisions remain the RL's own
(a shielded controller must not silently become a rule in disguise).

Extra wrapper (E7, runtime anti-dithering, no training):
  hyst@k|<inner>  forbids 'activate' within k steps after a 'deactivate' executed by this controller, and the reverse
                  (a hysteresis on the capacity level). Keeps the 17-action semantics (it only shrinks the mask).
Loading: v5 runs (v5/e/runs) first, then v4/v3 runs (same networks), via common5.load_agent.
"""

import numpy as np

from env.callcenter_env import A_ACT, A_DEACT
from v4.e import policies as P4
from v4.e.common import UrgentShield, masked_argmax, q_values
from v5.e.common5 import load_agent

P4.load_agent = load_agent        # v4 factory (rule / gate / hier specs) now also finds v5 runs; v4 file unchanged


class Pol:
    """policy(env, obs, mask) -> action; .prov / .intervened describe the LAST decision; .agent = RL net or None."""

    def __init__(self, meta, agent=None):
        self.meta, self.agent = meta, agent
        self.prov, self.intervened = "rule", False
        self.stats = {}

    def reset_day(self):
        pass

    def set_full(self, mask):
        """Called by the evaluator before each decision with the UNSHIELDED mask (propagated to the RL leaf)."""
        inner = getattr(self, "inner", None) or getattr(self, "rl", None)
        if inner is not None:
            inner.set_full(mask)


class RulePol(Pol):
    def __init__(self, arg):
        super().__init__({"n_params": 0})
        self.rule = P4.make_rule(arg)

    def __call__(self, env, obs, mask):
        self.prov, self.intervened = "rule", False
        return int(self.rule.act(env, obs, mask))


class RLPol(Pol):
    def __init__(self, run_id, which="best.pt"):
        agent, info, run = load_agent(run_id, which)
        super().__init__({"n_params": info["n_params"], "algo": info["algo"], "run_dir": str(run),
                          "ckpt_kb": round((run / which).stat().st_size / 1024, 1), "checkpoint": which}, agent)
        self.full_mask = None                    # set by set_full(): the unshielded mask (rl vs rl_rechoice)

    def set_full(self, mask):
        self.full_mask = mask

    def __call__(self, env, obs, mask):
        q = q_values(self.agent, obs)
        a = masked_argmax(q, mask)
        full = self.full_mask if self.full_mask is not None else mask
        self.prov = "rl" if a == masked_argmax(q, full) else "rl_rechoice"
        self.intervened = False
        return a


class GuardedPol(Pol):
    """V3 hybrid (= v4 _hier_fn): owner rule decides activate/deactivate; RL decides the rest; an RL
    activate/deactivate is replaced by the owner's action."""

    def __init__(self, run_id, owner):
        self.rl = RLPol(run_id)
        super().__init__({**self.rl.meta, "owner": owner}, self.rl.agent)
        self.owner = P4.FluidMPC(6, P4.MPC_K_V3) if owner == "mpc" else P4.Forecast(P4.FORECAST_Z_V3)

    def __call__(self, env, obs, mask):
        self.intervened = False
        a_rule = self.owner.act(env, obs, mask)
        if a_rule in (A_ACT, A_DEACT):
            self.prov = "owner"
            return a_rule
        a = self.rl(env, obs, mask)
        if a in (A_ACT, A_DEACT):
            self.prov = "owner"
            return a_rule
        self.prov = self.rl.prov
        return a


class ShieldPol(Pol):
    """floor@k (static: queue C >= k) or shield@t (Erlang-C dynamic floor) around any inner policy; identical
    action semantics to v4 policies.make_policy('floor@..|..')."""

    def __init__(self, sh: UrgentShield, inner: Pol, label):
        super().__init__({**inner.meta, "shield": label}, inner.agent)
        self.sh, self.inner = sh, inner

    def __call__(self, env, obs, mask):
        a_free = self.inner(env, obs, mask)                       # counterfactual: no shield
        m2, info = self.sh.mask(env, mask)
        self.last_shield = info
        a = self.inner(env, obs, m2)
        self.prov = self.inner.prov
        if not m2[a]:                                              # only rules can do this (RL chose inside m2)
            a = P4._default_in_mask(env, m2)
            self.prov = "shield_default"
        self.intervened = a != a_free
        self.removed = bool((m2 != mask).any())
        return int(a)


class HystPol(Pol):
    """Runtime hysteresis on the capacity level (E7): no activate within k steps after a deactivate, and reverse."""

    def __init__(self, k: int, inner: Pol):
        super().__init__({**inner.meta, "hyst": k}, inner.agent)
        self.k, self.inner = k, inner
        self.last = (None, -99)

    def reset_day(self):
        self.last = (None, -99)
        self.inner.reset_day()

    def __call__(self, env, obs, mask):
        if env.t == 0:
            self.last = (None, -99)
        m2 = mask.copy()
        kind, t = self.last
        if kind is not None and env.t - t <= self.k:
            m2[A_ACT if kind == A_DEACT else A_DEACT] = False
        a = self.inner(env, obs, m2)
        if not m2[a]:
            a = 0
        self.prov, self.intervened = self.inner.prov, getattr(self.inner, "intervened", False)
        if a in (A_ACT, A_DEACT):
            self.last = (a, env.t)
        return int(a)


def make_policy(spec: str) -> Pol:
    head, sep, rest = spec.partition("|")
    if (head.startswith("floor@") or head.startswith("shield@")) and rest.startswith("hyst@"):
        raise ValueError("put hyst@ OUTSIDE floor@/shield@ (the shield calls its inner twice; hyst is stateful)")
    if head.startswith("floor@") and sep:
        return ShieldPol(UrgentShield(static=int(head[6:])), make_policy(rest), head)
    if head.startswith("shield@") and sep:
        return ShieldPol(UrgentShield(float(head[7:])), make_policy(rest), head)
    if head.startswith("hyst@") and sep:
        return HystPol(int(head[5:]), make_policy(rest))
    kind, _, arg = spec.partition(":")
    if kind == "rule":
        return RulePol(arg)
    if kind == "rl":
        return RLPol(arg)
    if kind == "rllast":
        return RLPol(arg, "last.pt")
    if kind == "guarded":
        return GuardedPol(arg, "forecast")
    if kind == "mpcguard":
        return GuardedPol(arg, "mpc")
    raise ValueError(f"spec not supported in v5: {spec}")
