"""Integration-ready Agent E (research branch only; NOT wired into callverse/ - that needs an approved task).

Agent E reads an AGGREGATE snapshot of the queues (Intake's priority labels/scores + waiting times + capacity),
never message text, and returns a PROPOSAL. Following CLAUDE.md, agents never act directly: the proposal goes to
the Coordinator (rules), which executes it or refuses it. The same safety mask as the simulator is applied here
too, so an invalid proposal can never be produced.

    pol = AgentEPolicy.load("results/runs/dueling_double_dqn_intake_h64x64_s0")      # VAL-chosen best.pt
    proposal = pol.propose(snapshot)
snapshot = {
  "t_step": 37, "fallback_on": False, "fallback_steps_used": 3, "budget_spent": 610.0,
  "capacity": 24, "queues": [ {"alloc": 5, "arrivals_last_step": 4, "ewma_arrivals": 4.2,
                               "waiting": [{"priority_label": "high", "priority_score": 0.71, "waited_min": 3.5}, ...]},
                              ... 4 queues: A_status, B_refund, C_urgent, D_availability ] }
"""

import json
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from env.callcenter_env import (A_ACT, A_DEACT, A_FB_OFF, A_FB_ON, A_KEEP, MOVES, N_ACTIONS, N_Q, QUEUES,  # noqa: E402
                                REWARD_PRESETS, EnvConfig)
from env.intake_env import IntakeAwareEnv  # noqa: E402
from rl.agents import make_agent  # noqa: E402

RANK = {"low": 0, "medium": 1, "high": 2}     # simulator convention (prototype queue.py uses high=0)


def action_name(a: int) -> dict:
    if a == A_KEEP:
        return {"type": "keep"}
    if 1 <= a <= 12:
        i, j = MOVES[a - 1]
        return {"type": "move_session", "from": QUEUES[i], "to": QUEUES[j]}
    return {A_FB_ON: {"type": "fallback_on"}, A_FB_OFF: {"type": "fallback_off"},
            A_ACT: {"type": "activate_session"}, A_DEACT: {"type": "deactivate_session"}}[a]


class SnapshotView(IntakeAwareEnv):
    """Makes a snapshot look like the simulator's state, so observation and mask use the SAME code
    (the env's _obs and action_mask). It does not run the simulator's __init__: no random generator, no days."""

    def __init__(self, snap: dict, cfg: EnvConfig):
        self.cfg = c = cfg
        self.t = int(snap["t_step"])
        now = self.t * c.step_min
        qs = snap["queues"]
        self.alloc = np.array([q["alloc"] for q in qs])
        self.last_arr = np.array([q["arrivals_last_step"] for q in qs], float)
        self.ewma = np.array([q["ewma_arrivals"] for q in qs], float)
        self.waiting = [np.array([now - w["waited_min"] for w in q["waiting"]], float) for q in qs]
        self.wrank = [np.array([RANK[w["priority_label"]] for w in q["waiting"]], np.int8) for q in qs]
        self.wprio = [np.array([w["priority_score"] for w in q["waiting"]], np.float32) for q in qs]
        self.fallback = bool(snap["fallback_on"])
        self.spent = float(snap["budget_spent"])
        self.kpi = {"fallback_steps": int(snap.get("fallback_steps_used", 0))}
        self._cap = int(snap.get("capacity", c.max_sessions))
        self.sla, self.svc = np.array(c.sla_min), np.array(c.service_min)
        self.budget = c.init_active * c.steps_per_day * c.session_cost * c.budget_factor

    def available_capacity(self):
        return self._cap


class AgentEPolicy:
    def __init__(self, agent, cfg: EnvConfig, meta: dict):
        self.agent, self.cfg, self.meta = agent, cfg, meta

    @classmethod
    def load(cls, run_dir, cfg: EnvConfig | None = None):
        run_dir = Path(run_dir)
        info = json.loads((run_dir / "run.json").read_text())
        if info.get("env", "v1") != "intake":
            raise ValueError("Agent E integration expects an Intake-aware run (--env intake)")
        agent = make_agent(info["algo"], IntakeAwareEnv.obs_dim, N_ACTIONS, info["seed"], hidden=tuple(info["hidden"]))
        agent.load_state_dict(torch.load(run_dir / "best.pt", map_location="cpu", weights_only=False))
        return cls(agent, cfg or EnvConfig(**REWARD_PRESETS["intake"]), info)

    def observe(self, snap: dict) -> tuple[np.ndarray, np.ndarray]:
        v = SnapshotView(snap, self.cfg)
        return v._obs(), v.action_mask()

    def propose(self, snap: dict) -> dict:
        obs, mask = self.observe(snap)
        a = int(self.agent.act(obs, mask, explore=False))
        assert mask[a], "policy produced a masked action"          # cannot happen: agents only pick valid actions
        return {"agent": "E", "kind": "capacity_proposal", "action_id": a, **action_name(a),
                "valid_actions": [int(i) for i in np.flatnonzero(mask)], "policy": self.meta.get("algo"),
                "note": "proposal only: the Coordinator executes or refuses it"}


def snapshot_from_env(env: IntakeAwareEnv) -> dict:
    """Builds the snapshot the prototype would send, from a simulator state (used by the tests)."""
    now = env.t * env.cfg.step_min
    lab = {0: "low", 1: "medium", 2: "high"}
    return {"t_step": env.t, "fallback_on": env.fallback, "fallback_steps_used": env.kpi["fallback_steps"],
            "budget_spent": env.spent, "capacity": env.available_capacity(),
            "queues": [{"alloc": int(env.alloc[q]), "arrivals_last_step": float(env.last_arr[q]),
                        "ewma_arrivals": float(env.ewma[q]),
                        "waiting": [{"priority_label": lab[int(r)], "priority_score": float(p), "waited_min": now - w}
                                    for w, r, p in zip(env.waiting[q], env.wrank[q], env.wprio[q])]}
                       for q in range(N_Q)]}
