"""M7 v4 responsibility 5: F -> E feedback. The V3 gate is KEPT unchanged (`v3/m7/feedback_e.py`, GATE);
v4 only makes the answer explicit and per conversation.

    decision = e_reward_decision(card, sat_records)
      -> {"e_reward_allowed": bool, "reasons": [plain sentences], "gate": V3 gate output}
    rows = per_conversation_v4(reviews, sat_records, ends, decision)
      -> one row per conversation with e_reward_eligible (bool) + reasons, shortfall in EnvV3 units

e_reward_allowed is True only if the V3 gate passes (genuine customer ratings, support-conversation domain,
test n >= 300, Spearman CI low >= 0.30, beats the mean baseline, coverage >= 0.95). A conversation is eligible only
if, in addition, it has a score whose validity is "validated" (language AND domain). Otherwise rows are kpi_only.
E's mask, budget, fallback cap and HIGH protections never depend on F.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))          # experiments/agents_ef
from v3.m7 import feedback_e as fe3  # noqa: E402

GATE = fe3.GATE                         # unchanged thresholds, fixed before any evaluation


def e_reward_decision(card: dict | None, sat_records: list[dict]) -> dict:
    n = len(sat_records)
    coverage = sum(1 for r in sat_records if r["validity"] == "validated") / n if n else 0.0
    g = fe3.gate(card, coverage)
    reasons = []
    for c in g["checks"]:
        if not c["pass"]:
            reasons.append(f"{c['check']}: value {c.get('value', c.get('why'))}, needed {c.get('need', 'a card')}")
    if not card:
        reasons.append("no validation card: the satisfaction model was never validated")
    return {"e_reward_allowed": bool(g["usable_for_reward"]), "reasons": reasons, "gate": g,
            "validated_coverage": round(coverage, 4), "thresholds": GATE}


def per_conversation_v4(reviews: list[dict], sat_records: list[dict], ends: dict, decision: dict) -> list[dict]:
    sat = {r["conversation_id"]: r for r in sat_records}
    out = []
    for rv in reviews:
        s = sat.get(rv["conversation_id"]) or {}
        score = s.get("predicted_satisfaction")
        why = [] if decision["e_reward_allowed"] else ["gate closed: " + "; ".join(decision["reasons"])]
        if score is None:
            why.append("no score: " + "; ".join(s.get("reasons", ["not scored"])))
        elif s.get("validity") != "validated":
            why.append(f"score validity is {s.get('validity')}")
        out.append({"conversation_id": rv["conversation_id"], "closed_at": ends.get(rv["conversation_id"]),
                    "route": rv.get("route"), "priority": rv.get("priority"), "resolution": rv.get("resolution"),
                    "predicted_satisfaction": score,
                    "shortfall": None if score is None else round((5 - min(max(score, 1), 5)) / 4, 4),
                    "validity": s.get("validity"), "e_reward_eligible": not why, "reasons": why,
                    "use": "reward" if not why else "kpi_only"})
    return out


def aggregate(rows: list[dict], step_min: int = 5) -> list[dict]:
    """Per (5-minute step, route) shortfall sums — V3's aggregate (same EnvV3 units)."""
    return fe3.aggregate(rows, step_min)
