"""Agent E v4 standalone adapter: structured queue snapshot  ->  capacity PROPOSAL (never an action).

Following CLAUDE.md, Agent E never acts directly: it returns a proposal for the Coordinator (rules), which executes
or refuses it. The adapter never mutates the snapshot or any external state (it builds a private read-only view).

The observation and the action mask are built with the SAME code as the simulator: SnapshotViewV3 fills exactly
the attributes EnvV3._obs() and EnvV3.action_mask() read, then calls those unbound methods. The tests
(tests/test_adapter.py) check, on real simulator states, that adapter obs == env obs and adapter mask == env mask.

SNAPSHOT SCHEMA (v2 schema from integration/agent_e_policy.py, unchanged; extra optional fields marked *):
{
  "t_step": 37,                    # 5-minute decision step of the day, 0..95
  "fallback_on": false,            # is the cheap fallback mode currently on
  "fallback_steps_used": 3,        # steps with fallback on so far today (cap = 25 % of 96 = 24)
  "budget_spent": 610.0,           # session-steps paid so far today
  "capacity": 24,                  # sessions physically available now (24 minus failed ones)
  * "budget_total": 1766.4,        # default ConfigV3: 16 sessions x 96 steps x 1.15
  "queues": [                      # exactly 4, order A_status, B_refund, C_urgent, D_availability
     {"alloc": 5, "arrivals_last_step": 4, "ewma_arrivals": 4.2,
      "waiting": [{"priority_label": "high", "priority_score": 0.71, "waited_min": 3.5}, ...]}, ...]
}
priority_label in {low, medium, high} (simulator convention). Queue mapping (verified by Worker D):
order_status / late_delivery -> A_status, refund_request / return_item -> B_refund, damaged_item -> C_urgent,
other -> D_availability.

OUTPUT (dict): action_id, action (human readable), policy (the spec), q_values (RL only, list of 17, masked = None),
rl_preference (the network's own choice), decided_by, mask (17 bools, simulator rules), safety_veto (bool: the urgent
floor changed the decision), veto_reason, fallback_reason (why the classical backup rule was used instead of the
policy, or None), urgent_floor_c, audit {model_sha256, run_id, latency_ms, adapter_version, obs_sha256, n_params}.
Hard guarantees (tested): the proposed action is always valid under the simulator mask; with a shield, queue C is
never reduced below max(2, Erlang-C floor); HIGH tickets are never served by fallback (the fallback switch applies
to LOW/MEDIUM tickets of A and D only - enforced where tickets are served; the adapter states it in the output).
A mask/shield constrains ALLOCATION; it cannot guarantee that future SLAs are met.
"""

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from env.callcenter_env import A_ACT, A_DEACT, A_FB_OFF, A_FB_ON, A_KEEP, MOVES, N_ACTIONS, N_Q, QUEUES  # noqa: E402
from v3.e.env_v3 import ConfigV3, EnvV3  # noqa: E402
from v4.e.common import E4, QC, UrgentShield, file_sha256, find_run, load_agent, masked_argmax, q_values  # noqa: E402

ADAPTER_VERSION = "v4.0"
RANK = {"low": 0, "medium": 1, "high": 2}
LABEL = {0: "low", 1: "medium", 2: "high"}
RECOMMENDED = E4 / "configs" / "recommended.json"


def action_name(a: int) -> dict:
    if a == A_KEEP:
        return {"type": "keep", "text": "keep the current allocation"}
    if 1 <= a <= 12:
        i, j = MOVES[a - 1]
        return {"type": "move_session", "from": QUEUES[i], "to": QUEUES[j], "text": f"move 1 session {QUEUES[i]} -> {QUEUES[j]}"}
    return {A_FB_ON: {"type": "fallback_on", "text": "switch fallback ON (LOW/MEDIUM tickets of A and D only)"},
            A_FB_OFF: {"type": "fallback_off", "text": "switch fallback OFF"},
            A_ACT: {"type": "activate_session", "text": "activate 1 session (goes to the most loaded queue)"},
            A_DEACT: {"type": "deactivate_session", "text": "deactivate 1 session (from the least loaded queue)"}}[a]


class SnapshotViewV3:
    """Read-only stand-in for EnvV3 built from a snapshot. Only the attributes used by EnvV3._obs, EnvV3.action_mask,
    EnvV3._load (and the v3 rules / shield) are set; the snapshot itself is deep-copied into numpy arrays."""

    _obs = EnvV3._obs
    action_mask = EnvV3.action_mask
    _load = EnvV3._load
    waiting = EnvV3.waiting

    def __init__(self, snap: dict, cfg: ConfigV3 | None = None):
        self.cfg = c = cfg or ConfigV3()
        qs = snap["queues"]
        if len(qs) != N_Q:
            raise ValueError(f"snapshot must have {N_Q} queues in order {QUEUES}")
        self.t = int(snap["t_step"])
        if not 0 <= self.t < c.steps_per_day:
            raise ValueError("t_step out of range")
        now = self.t * c.step_min
        t_arr, rank, prio, self.queue = [], [], [], []
        for q in qs:
            ids = []
            for w in q["waiting"]:
                ids.append(len(t_arr))
                t_arr.append(now - float(w["waited_min"]))
                rank.append(RANK[w["priority_label"]])
                prio.append(float(w["priority_score"]))
            self.queue.append(ids)
        self.tape = {"t_arr": np.array(t_arr, float), "rank": np.array(rank, np.int8), "prio": np.array(prio, np.float32)}
        self.alloc = np.array([int(q["alloc"]) for q in qs])
        self.last_arr = np.array([float(q["arrivals_last_step"]) for q in qs])
        self.ewma = np.array([float(q["ewma_arrivals"]) for q in qs])
        self.fallback = bool(snap["fallback_on"])
        self.spent = float(snap["budget_spent"])
        self.kpi = {"fallback_steps": int(snap.get("fallback_steps_used", 0))}
        self._cap = int(snap.get("capacity", c.max_sessions))
        self.sla, self.patience = np.array(c.sla_min), np.array(c.patience_min)
        self.svc, self.pw, self.fb_ok = np.array(c.service_min), np.array(c.priority_w), np.array(c.fallback_eligible)
        self.budget = float(snap.get("budget_total", c.init_active * c.steps_per_day * c.session_cost * c.budget_factor))

    def available_capacity(self):
        return self._cap


def snapshot_from_env(env: EnvV3) -> dict:
    """The snapshot the prototype would send, built from a live simulator state (tests + integration)."""
    now = env.t * env.cfg.step_min
    tp = env.tape
    return {"t_step": int(env.t), "fallback_on": bool(env.fallback), "fallback_steps_used": int(env.kpi["fallback_steps"]),
            "budget_spent": float(env.spent), "capacity": int(env.available_capacity()), "budget_total": float(env.budget),
            "queues": [{"alloc": int(env.alloc[q]), "arrivals_last_step": float(env.last_arr[q]),
                        "ewma_arrivals": float(env.ewma[q]),
                        "waiting": [{"priority_label": LABEL[int(tp["rank"][i])], "priority_score": float(tp["prio"][i]),
                                     "waited_min": float(now - tp["t_arr"][i])} for i in env.queue[q]]}
                       for q in range(N_Q)]}


class AgentEAdapter:
    """Wraps ANY v4 policy spec (policies.make_policy), so the adapter behaves EXACTLY like the evaluated policy.
    Examples: "floor@3|guarded:<run>" (recommended structure), "floor@3|rl:<run>", "rl:<run>", "shield@0.2|rl:<run>".
    The policy runs on a read-only SnapshotViewV3; the network's Q-values are reported for audit."""

    def __init__(self, spec: str, backup="mpc:0.5"):
        from v4.e.policies import make_policy
        self.spec, self.backup_spec, self._backup = spec, backup, None
        self.load_error, self.policy, self.agent, self.info, self.run_dir = None, None, None, {}, None
        try:
            self.policy = make_policy(spec)
            self.agent = self.policy.agent
            run_dir = self.policy.meta.get("run_dir")
            self.run_dir = Path(run_dir) if run_dir else None
            if self.run_dir:
                self.info = json.loads((self.run_dir / "run.json").read_text())
        except Exception as e:                                   # never crash the Coordinator's loop
            self.load_error = repr(e)[:200]
        self.model_sha256 = file_sha256(self.run_dir / "best.pt") if self.run_dir else None
        head = spec.split("|")[0] if "|" in spec else ""
        self.floor_spec = head if head.startswith(("floor@", "shield@")) else None

    @classmethod
    def load(cls, run_id: str | None = None, shield_target="recommended", spec: str | None = None, floor: int | None = None,
             backup="mpc:0.5"):
        """spec wins. Else run_id (+ shield_target Erlang floor or static floor). No arguments -> configs/recommended.json."""
        if spec is None and run_id is None:
            spec = json.loads(RECOMMENDED.read_text())["spec"]
        if spec is None:
            if shield_target == "recommended":
                shield_target = None
            spec = f"rl:{run_id}"
            if floor is not None:
                spec = f"floor@{floor}|{spec}"
            elif shield_target is not None:
                spec = f"shield@{shield_target:g}|{spec}"
        return cls(spec, backup)

    def backup(self):
        if self._backup is None:
            from v4.e.policies import make_rule
            self._backup = make_rule(self.backup_spec)
        return self._backup

    def observe(self, snap: dict):
        v = SnapshotViewV3(snap)
        return v, v._obs(), v.action_mask()

    def propose(self, snap: dict) -> dict:
        from v4.e.common import UrgentShield
        from v4.e.policies import _default_in_mask
        t0 = time.perf_counter()
        view, obs, mask = self.observe(snap)
        fallback_reason, qv, raw, veto, reason, floor_c = None, None, None, False, None, None
        if self.policy is None:
            fallback_reason = f"policy not loaded: {self.load_error}"
        elif self.agent is not None:
            qv = q_values(self.agent, obs)
            if not np.isfinite(qv).all():
                fallback_reason = "non-finite Q-values"
        if fallback_reason is None:
            a = int(self.policy(view, obs, mask))
            if self.agent is not None:
                raw = masked_argmax(qv, mask)                     # the network's own preference (simulator mask only)
            inner = getattr(self.policy, "inner", None)
            if inner is not None:                                 # a floor/shield wraps the policy
                info = getattr(self.policy, "last_shield", {})
                floor_c = info.get("floor_c")
                unshielded = int(inner(view, obs, mask))          # what the same policy would do without the floor
                veto = unshielded != a
                if veto:
                    reason = (f"{info.get('reason') or 'action would lower queue C below its urgent floor'}; "
                              f"without the floor the policy would {action_name(unshielded)['text']}")
            policy_name = self.spec
        else:
            sh = UrgentShield(static=3)                           # backup keeps the urgent floor too
            smask, info = sh.mask(view, mask)
            floor_c = info["floor_c"]
            a = int(self.backup().act(view, obs, smask))
            if not smask[a]:
                a = _default_in_mask(view, smask)
            policy_name = f"backup:floor@3|rule:{self.backup_spec}"
        assert mask[a], "adapter produced an invalid action"      # cannot happen by construction
        out = {"agent": "E", "kind": "capacity_proposal", "action_id": int(a), "action": action_name(a),
               "policy": policy_name,
               "q_values": None if qv is None else [float(x) if m else None for x, m in zip(qv, mask)],
               "rl_preference": None if raw is None else action_name(raw)["text"],
               "decided_by": ("backup rule" if fallback_reason else "rl" if raw == a else
                              "floor/shield" if veto else "capacity-owner rule" if a in (A_ACT, A_DEACT) else "rl (within rules)"),
               "mask": [bool(x) for x in mask], "safety_veto": bool(veto), "veto_reason": reason,
               "fallback_reason": fallback_reason, "urgent_floor_c": floor_c,
               "fallback_scope": "fallback never serves HIGH tickets; only LOW/MEDIUM of A_status and D_availability",
               "note": "proposal only: the Coordinator executes or refuses it"}
        out["audit"] = {"adapter_version": ADAPTER_VERSION, "run_id": self.info.get("run_id"), "model_sha256": self.model_sha256,
                        "n_params": self.info.get("n_params"), "obs_sha256": hashlib.sha256(obs.tobytes()).hexdigest()[:16],
                        "latency_ms": round(1e3 * (time.perf_counter() - t0), 3)}
        return out
