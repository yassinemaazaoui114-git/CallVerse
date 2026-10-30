"""Router: decide which agent handles a ticket. Rules from config.yaml (queues.routes), no LLM.

Why rules? The ticket already carries a main_reason (Intake). Mapping a reason to an agent is a
fixed lookup: a rule is instant, free, always gives the same answer and is easy to show the teacher.

T21: each company has its own routes (config.yaml companies:). A route can be "escalate" instead of an agent: the
ticket goes to a human colleague, no agent runs (Atlas: rebooking and assistance, until agent C exists).
"""

from callverse import companies, trace
from callverse.config import load_config


def route(ticket: dict) -> dict:
    """Return {agent, layer, reason, priority_label} for the ticket and trace the decision."""
    cfg = load_config()["queues"]
    routes = companies.get(companies.of(ticket))["routes"]
    reason = ticket["main_reason"]
    decision = {
        "agent": routes.get(reason, routes["other"]),   # unknown reason -> same as "other"
        "layer": cfg["layer"],
        "reason": reason,
        "priority_label": ticket["priority_label"],
    }
    trace.log("route", "router", {"ticket_id": ticket.get("ticket_id"), **decision})
    return decision
