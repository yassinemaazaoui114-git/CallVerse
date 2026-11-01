"""The situation of a reply (RL1): a few facts about one ticket and its decision, for the RL style policy (RL5) and agent F.

It is only a summary of what already exists (the Intake ticket and the Coordinator's decision). It decides nothing and
reads no database. Fields are fixed by docs/RL_interface_spec.md.
"""

from callverse import companies

FIELDS = ("company", "reason", "outcome", "action", "rule_id", "emotion", "sentiment", "priority", "days_late")


def situation(ticket: dict, decision: dict) -> dict:
    """Exactly the RL spec fields. A field the ticket or decision does not have is None (hand-made test tickets may lack some)."""
    facts = ticket.get("facts") or {}
    days_late = facts.get("days_late")
    if days_late is None:   # Atlas has no days_late; a ShopNova decision may carry it
        days_late = (decision.get("facts") or {}).get("days_late")
    return {
        "company": companies.of(ticket),
        "reason": ticket.get("main_reason"),
        "outcome": decision.get("outcome"),
        "action": decision.get("action"),
        "rule_id": decision.get("rule_id"),
        "emotion": (ticket.get("emotion") or {}).get("label"),
        "sentiment": (ticket.get("sentiment") or {}).get("label"),
        "priority": ticket.get("priority_label"),
        "days_late": days_late,
    }
