"""F -> E feedback contract (Worker D): the ONLY door through which a satisfaction score may reach Agent E.

Agent F emits one record per closed conversation. Agent E's training reward may use a record only if F marked it
reward-eligible AND the record carries the validation card that justified it. Everything else goes to the KPI
channel (dashboards), never to the reward. This side re-checks F's flag instead of trusting it blindly.

Record (from Agent F):
    {"conversation_id", "closed_at" (ISO time), "main_reason", "predicted_satisfaction" (1-5 or None),
     "e_reward_eligible" (bool), "eligibility_reasons" [..], "validation_card" {label_type, domain, ...} or None}
Output: per (5-minute step, Agent E queue): n, shortfall_sum = sum((5 - s) / 4), in EnvV3's csat units
(v3/e/env_v3.py `csat_shortfall`), split into a "reward" and a "kpi_only" channel.
Safety: nothing here touches E's action mask, budget, fallback cap or HIGH protection.
"""

import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from v3.m7.feedback_e import gate  # noqa: E402   the gate thresholds fixed in V3, before any evaluation
from v4.d.bridge import E_QUEUE_OF_REASON, QUEUES  # noqa: E402


def reward_allowed(rec: dict) -> tuple[bool, list[str]]:
    """Accept a record for E's reward only if F says so AND its validation card passes the V3 gate here too."""
    why = []
    if rec.get("e_reward_eligible") is not True:
        why.append("Agent F marked it not eligible: " + "; ".join(rec.get("eligibility_reasons") or ["no reason given"]))
    card = rec.get("validation_card")
    g = gate(card)
    if not g["usable_for_reward"]:
        why.append("validation card fails the gate: " + ", ".join(c["check"] for c in g["checks"] if not c["pass"]))
    s = rec.get("predicted_satisfaction")
    if not isinstance(s, (int, float)) or not 1 <= s <= 5:
        why.append(f"no usable score ({s!r})")
    return (not why), why


def aggregate(records: list[dict], step_min: int = 5) -> dict:
    out = {"reward": defaultdict(lambda: {"n": 0, "shortfall_sum": 0.0}),
           "kpi_only": defaultdict(lambda: {"n": 0, "shortfall_sum": 0.0}), "refusals": []}
    for r in records:
        ok, why = reward_allowed(r)
        s = r.get("predicted_satisfaction")
        if not ok:
            out["refusals"].append({"conversation_id": r.get("conversation_id"), "why": why})
        if not isinstance(s, (int, float)) or not r.get("closed_at"):
            continue
        t = datetime.fromisoformat(r["closed_at"])
        step = t.replace(minute=t.minute - t.minute % step_min, second=0, microsecond=0).isoformat()
        q = QUEUES[E_QUEUE_OF_REASON.get(r.get("main_reason"), E_QUEUE_OF_REASON["other"])]
        cell = out["reward" if ok else "kpi_only"][(step, q)]
        cell["n"] += 1
        cell["shortfall_sum"] = round(cell["shortfall_sum"] + (5 - min(max(s, 1), 5)) / 4, 6)
    out["reward"], out["kpi_only"] = dict(out["reward"]), dict(out["kpi_only"])
    return out


def from_agent_f(out: dict, card: dict | None) -> dict:
    """Agent F's process() output -> contract record (field names of v4/f/agent_f.py)."""
    e = out.get("e_reward_eligible") or {}
    return {"conversation_id": out.get("conversation_id"), "closed_at": out.get("closed_at"),
            "main_reason": out.get("main_reason"), "predicted_satisfaction": out.get("predicted_satisfaction"),
            "e_reward_eligible": e.get("eligible") is True, "eligibility_reasons": e.get("reasons") or [],
            "validation_card": card}
