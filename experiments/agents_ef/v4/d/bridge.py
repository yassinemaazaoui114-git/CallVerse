"""Worker D: the bridge between prototype tickets and Agent E, plus an INDEPENDENT check of E's proposals.

Why this file exists
- Agent E plans staff for 4 workload categories (research simulator). The prototype has ONE priority queue and two
  agent routes (config.yaml queues.routes: A or B). This file makes that mapping explicit and checkable.
- Agent E must never act directly (CLAUDE.md). Its proposal is re-checked here by rules written from the simulator's
  configuration (ConfigV3), NOT by calling E's own mask, so a bug in E's mask would be caught, not copied.

Mapping (research assumption, from env/intake_adapter.QUEUE_REASONS; not a prototype contract):
    order_status, late_delivery -> A_status        (prototype route: Agent A)
    refund_request, return_item -> B_refund        (prototype route: Agent B)
    damaged_item                -> C_urgent        (prototype route: Agent B)
    other                       -> D_availability  (prototype route: Agent A)
"""

import copy
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

AEF = Path(__file__).resolve().parents[2]             # experiments/agents_ef
ROOT = AEF.parents[1]                                 # repository root
sys.path.insert(0, str(AEF))
from env.intake_adapter import QUEUE_REASONS  # noqa: E402
from v3.e.env_v3 import ConfigV3  # noqa: E402

QUEUES = ["A_status", "B_refund", "C_urgent", "D_availability"]
URGENT = 2
E_QUEUE_OF_REASON = {name: q for q, pairs in QUEUE_REASONS.items() for name, _ in pairs}
MOVES = [(i, j) for i in range(4) for j in range(4) if i != j]          # action 1..12 = MOVES[a-1]
KEEP, FB_ON, FB_OFF, ACT, DEACT = 0, 13, 14, 15, 16


def prototype_routes() -> dict:
    """Reason -> agent route, read from the prototype's config.yaml (never copied by hand)."""
    return yaml.safe_load(open(ROOT / "config.yaml"))["queues"]["routes"]


def check_mapping() -> list[str]:
    """Problems with the mapping: a prototype reason E does not know, or an E reason the prototype lacks."""
    routes = prototype_routes()
    out = [f"prototype reason '{r}' has no Agent E queue" for r in routes if r not in E_QUEUE_OF_REASON]
    out += [f"Agent E reason '{r}' is not a prototype route" for r in E_QUEUE_OF_REASON if r not in routes]
    return out


class TicketBook:
    """Waiting tickets per Agent E category, built from Intake ticket dicts, on a 5-minute step clock."""

    def __init__(self, step_min: float = 5.0, ewma_alpha: float = 0.3):
        self.step_min, self.alpha = step_min, ewma_alpha
        self.waiting = [[] for _ in QUEUES]           # [(ticket_id, arrived_min, label, score)]
        self.arr_this_step = np.zeros(4)
        self.last_arr = np.zeros(4)
        self.ewma = np.zeros(4)

    def add(self, ticket: dict, arrived_min: float) -> int:
        q = E_QUEUE_OF_REASON.get(ticket["main_reason"], E_QUEUE_OF_REASON["other"])
        self.waiting[q].append((ticket["ticket_id"], float(arrived_min), ticket["priority_label"],
                                float(ticket.get("priority_score", 0.0))))
        self.arr_this_step[q] += 1
        return q

    def end_step(self):
        """Close the 5-minute step: update arrival counts and their EWMA (same idea as the simulator)."""
        self.last_arr = self.arr_this_step.copy()
        self.ewma = self.alpha * self.last_arr + (1 - self.alpha) * self.ewma
        self.arr_this_step = np.zeros(4)

    def serve(self, q: int, n: int):
        """Remove the n most urgent tickets of queue q (high > medium > low, then oldest): prototype queue order."""
        rank = {"high": 0, "medium": 1, "low": 2}
        self.waiting[q].sort(key=lambda w: (rank[w[2]], w[1]))
        del self.waiting[q][:n]

    def snapshot(self, now_min: float, state: "CapacityState") -> dict:
        """The aggregate snapshot Agent E reads (schema of integration/agent_e_policy.py). No message text."""
        return {"t_step": state.t_step, "fallback_on": state.fallback_on,
                "fallback_steps_used": state.fallback_steps_used, "budget_spent": state.budget_spent,
                "capacity": state.capacity,
                "queues": [{"alloc": int(state.alloc[q]), "arrivals_last_step": float(self.last_arr[q]),
                            "ewma_arrivals": float(self.ewma[q]),
                            "waiting": [{"priority_label": w[2], "priority_score": w[3],
                                         "waited_min": round(now_min - w[1], 3)} for w in self.waiting[q]]}
                           for q in range(4)]}


@dataclass
class CapacityState:
    alloc: np.ndarray = field(default_factory=lambda: np.array([5, 3, 2, 6]))
    t_step: int = 0
    fallback_on: bool = False
    fallback_steps_used: int = 0
    budget_spent: float = 0.0
    capacity: int = 24


def validate(state: CapacityState, action: int, cfg: ConfigV3 | None = None) -> tuple[bool, list[str]]:
    """Independent rule check of one capacity proposal. Returns (ok, reasons it is refused)."""
    c = cfg or ConfigV3()
    why = []
    active = int(state.alloc.sum())
    budget = c.init_active * c.steps_per_day * c.session_cost * c.budget_factor
    left = c.steps_per_day - state.t_step
    if not isinstance(action, (int, np.integer)) or not 0 <= int(action) <= 16:
        return False, [f"unknown action {action!r}"]
    a = int(action)
    if 1 <= a <= 12:
        i, _ = MOVES[a - 1]
        floor = c.min_alloc_urgent if i == URGENT else 0
        if state.alloc[i] <= floor:
            why.append(f"cannot take a session from {QUEUES[i]}: it has {int(state.alloc[i])}, minimum {floor}")
    elif a == FB_ON:
        if state.fallback_on:
            why.append("fallback is already on")
        if state.fallback_steps_used >= c.fallback_max_share * c.steps_per_day:
            why.append(f"fallback cap reached ({c.fallback_max_share:.0%} of the day)")
    elif a == FB_OFF and not state.fallback_on:
        why.append("fallback is already off")
    elif a == ACT:
        if active >= state.capacity:
            why.append(f"no free capacity ({active}/{state.capacity})")
        if state.budget_spent + (active + 1) * c.session_cost * left > budget + 1e-9:
            why.append("activating would break the day's budget")
    elif a == DEACT and active <= c.min_active:
        why.append(f"cannot go below {c.min_active} active sessions")
    return (not why), why


def apply(state: CapacityState, action: int, load: np.ndarray, cfg: ConfigV3 | None = None) -> CapacityState:
    """Simulated resource update AFTER validation (a copy; the input is not changed). Activate goes to the most
    loaded queue, deactivate leaves the least loaded one (never below the urgent minimum): the simulator's rule."""
    c = cfg or ConfigV3()
    ok, why = validate(state, action, c)
    if not ok:
        raise ValueError("refused: " + "; ".join(why))
    s = copy.deepcopy(state)
    a = int(action)
    if 1 <= a <= 12:
        i, j = MOVES[a - 1]
        s.alloc[i] -= 1
        s.alloc[j] += 1
    elif a == FB_ON:
        s.fallback_on = True
    elif a == FB_OFF:
        s.fallback_on = False
    elif a == ACT:
        s.alloc[int(np.argmax(load))] += 1
    elif a == DEACT:
        cand = [q for q in range(4) if s.alloc[q] > (c.min_alloc_urgent if q == URGENT else 0)]
        s.alloc[min(cand, key=lambda q: load[q])] -= 1
    return s
