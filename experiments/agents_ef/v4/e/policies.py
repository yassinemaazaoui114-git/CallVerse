"""Agent E v4 policy factory: every policy is a function  policy(env, obs, mask) -> action id.

Spec grammar (composable, written in result file names with ':' -> '__' and '|' -> '+'):
  rule:mpc:<k> | rule:forecast:<z> | rule:erlang:<t> | rule:fixed | ...   classical rules (v3 code, unchanged)
  rl:<run_id>          greedy RL (best.pt of v4/e/runs/<id> or v3/e/runs/<id>)
  guarded:<run_id>     V3 hybrid: Forecast(z=0.25, the V3 VAL choice) owns activate/deactivate, RL the rest
  mpcguard:<run_id>    hierarchical: Fluid MPC (k=0.5) owns activate/deactivate (capacity envelope), RL allocates
                       (V3 guarded semantics: if RL picks activate/deactivate, the rule's action is used)
  hier:<owner>:<run>   hierarchical as TRAINED by train_v4 --owner: owner (mpc|forecast) owns activate/deactivate,
                       RL chooses among the remaining actions only (its mask never contains activate/deactivate)
  shield@<t>|<inner>   urgent-capacity shield (common.UrgentShield, Erlang-C target t) around any inner policy
  gate@<d>:<rule>|rl:<run>  confidence-gated hybrid: the classical rule's action is the DEFAULT; the RL action is
                       used only if the network values it at least d above the rule's action (Q(a_rl) - Q(a_rule) >= d,
                       Q in return units; d = 0 -> pure RL, d large -> pure rule). Uses the diagnosis that RL is
                       nearly indifferent in ~40 % of decisions and only clearly better in some states (overload).
  floor@<k>|<inner>    static stronger mask: queue C never below k sessions (k=2 is the V3 mask)
Each policy object exposes .stats (counters of shield vetoes) so the evaluator can report safety interventions.
"""

import numpy as np

from baselines.heuristics import ErlangC, Fixed, Forecast, Priority, Threshold
from env.callcenter_env import A_ACT, A_DEACT, A_KEEP, MOVES
from v3.e.baselines_v3 import FluidMPC, RandomValid
from v4.e.common import QC, UrgentShield, alloc_after, load_agent, masked_argmax, q_values

FORECAST_Z_V3 = 0.25       # v3/e/results/val_choice.json (chosen on V3 VAL)
MPC_K_V3 = 0.5


def make_rule(arg: str):
    name, _, p = arg.partition(":")
    simple = {"fixed": Fixed, "threshold": Threshold, "priority": Priority}
    if name in simple:
        return simple[name]()
    if name == "random_valid":
        return RandomValid(0)
    if name == "forecast":
        return Forecast(float(p))
    if name == "erlang":
        return ErlangC(float(p))
    if name == "mpc":
        return FluidMPC(6, float(p))
    raise ValueError(arg)


class Policy:
    """Callable wrapper with metadata and counters."""

    def __init__(self, fn, meta, agent=None):
        self.fn, self.meta, self.agent = fn, meta, agent
        self.stats = {"shield_vetoes": 0}

    def __call__(self, env, obs, mask):
        return self.fn(env, obs, mask)


def _rl_fn(agent):
    def fn(env, obs, mask):
        return masked_argmax(q_values(agent, obs), mask) if hasattr(agent, "q") else agent.act(obs, mask, explore=False)
    return fn


def _hier_fn(agent, owner):
    """owner (a rule) decides WHETHER to change the capacity level; RL decides everything else.
    Exactly the V3 semantics of bench/guarded_e.guarded (so 'guarded:' reproduces the V3 hybrid)."""
    rl = _rl_fn(agent)

    def fn(env, obs, mask):
        a_rule = owner.act(env, obs, mask)
        if a_rule in (A_ACT, A_DEACT):
            return a_rule
        a = rl(env, obs, mask)
        return a if a not in (A_ACT, A_DEACT) else a_rule      # RL never changes the capacity level itself
    return fn


def _default_in_mask(env, m):
    """Deterministic replacement when an inner RULE proposes an action the shield removed:
    move a session into queue C from the least-loaded donor if allowed, else keep, else the first valid action."""
    load = env._load()
    ups = [a for a in range(1, 13) if m[a] and MOVES[a - 1][1] == QC]
    if ups:
        return min(ups, key=lambda a: load[MOVES[a - 1][0]])
    if m[A_KEEP]:
        return A_KEEP
    return int(np.flatnonzero(m)[0])


def make_policy(spec: str) -> Policy:
    if spec.startswith("gate@"):
        head, _, inner_spec = spec.partition("|")
        d_s, _, rule_s = head[len("gate@"):].partition(":")
        delta, rule = float(d_s), make_rule(rule_s)
        inner = make_policy(inner_spec)
        pol = Policy(None, {**inner.meta, "gate_delta": delta, "gate_rule": rule_s}, inner.agent)
        pol.stats.update(rl_overrides=0)

        def fn(env, obs, mask):
            a_rule = int(rule.act(env, obs, mask))
            q = q_values(inner.agent, obs)
            a_rl = masked_argmax(q, mask)
            if a_rl != a_rule and q[a_rl] - q[a_rule] >= delta:
                pol.stats["rl_overrides"] += 1
                return a_rl
            return a_rule
        pol.fn = fn
        return pol
    if spec.startswith("shield@") or spec.startswith("floor@"):
        head, _, inner_spec = spec.partition("|")
        target = float(head.split("@")[1])
        inner = make_policy(inner_spec)
        sh = UrgentShield(target) if spec.startswith("shield@") else UrgentShield(static=int(target))
        pol = Policy(None, {**inner.meta, "shield_target": target}, inner.agent)

        pol.stats.update(shield_active=0, shield_forced=0)

        def fn(env, obs, mask):
            m2, info = sh.mask(env, mask)
            pol.last_shield = info
            a = inner(env, obs, m2)
            if (m2 != mask).any():
                pol.stats["shield_active"] += 1            # the shield removed at least one action this step
                if inner.agent is not None and inner_spec.startswith("rl:"):
                    if masked_argmax(q_values(inner.agent, obs), mask) != a:
                        pol.stats["shield_vetoes"] += 1    # the unshielded RL choice was different
            if not m2[a]:                                  # only rules can do this; RL already chose inside m2
                a = _default_in_mask(env, m2)
                pol.stats["shield_forced"] += 1
                pol.stats["shield_vetoes"] += 1
            return a
        pol.fn = fn
        pol.inner = inner
        return pol
    kind, _, arg = spec.partition(":")
    if kind == "hier":
        owner_name, _, run_id = arg.partition(":")
        agent, info, run = load_agent(run_id)
        owner = FluidMPC(6, MPC_K_V3) if owner_name == "mpc" else Forecast(FORECAST_Z_V3)
        rl = _rl_fn(agent)

        def fn(env, obs, mask):
            a_rule = owner.act(env, obs, mask)
            if a_rule in (A_ACT, A_DEACT) and mask[a_rule]:
                return a_rule
            m2 = mask.copy()
            m2[A_ACT] = m2[A_DEACT] = False
            return rl(env, obs, m2)
        return Policy(fn, {"n_params": info["n_params"], "algo": info["algo"], "run_dir": str(run), "owner": owner_name,
                           "ckpt_kb": round((run / "best.pt").stat().st_size / 1024, 1)}, agent)
    if kind == "rule":
        r = make_rule(arg)
        return Policy(lambda e, o, m: r.act(e, o, m), {"n_params": 0})
    agent, info, run = load_agent(arg)
    meta = {"n_params": info["n_params"], "algo": info["algo"], "run_dir": str(run),
            "ckpt_kb": round((run / "best.pt").stat().st_size / 1024, 1)}
    if kind == "rl":
        return Policy(_rl_fn(agent), meta, agent)
    if kind == "guarded":
        return Policy(_hier_fn(agent, Forecast(FORECAST_Z_V3)), {**meta, "owner": f"forecast:{FORECAST_Z_V3}"}, agent)
    if kind == "mpcguard":
        return Policy(_hier_fn(agent, FluidMPC(6, MPC_K_V3)), {**meta, "owner": f"mpc:{MPC_K_V3}"}, agent)
    raise ValueError(spec)


__all__ = ["make_policy", "Policy", "alloc_after"]
