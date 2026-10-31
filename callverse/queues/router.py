"""Router: decide which agent handles a ticket. Rules from config.yaml (queues.routes), no LLM.

Why rules? The ticket already carries a main_reason (Intake). Mapping a reason to an agent is a
fixed lookup: a rule is instant, free, always gives the same answer and is easy to show the teacher.

T21: each company has its own routes (config.yaml companies:). A route can be "escalate" instead of an agent: the
ticket goes to a human colleague, no agent runs.

P20 (spec: "C = Layer 2 for urgent, low-confidence, disputed, unresolved tickets"): a LOW-CONFIDENCE ticket goes to
Agent C (layer L2). Confidence is not a new model: it is the score Intake already gives the main reason (the best
cosine score of its sentences, ticket["reasons"]) minus the company's reason_threshold. A ticket about a case (it has
an order / booking number) whose main reason passed the threshold by less than queues.low_confidence_margin is "low
confidence": the reason may be wrong, so C, which combines A, B and D, takes it.
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
    margin = confidence_margin(ticket)
    if margin is not None and margin < cfg.get("low_confidence_margin", 0) and ticket.get("order_id") is not None:
        decision.update(agent="C", layer="L2", confidence_margin=margin)   # P20: low confidence -> Agent C
    trace.log("route", "router", {"ticket_id": ticket.get("ticket_id"), **decision})
    return decision


def confidence_margin(ticket: dict) -> float | None:
    """How far the main reason's Intake score is above the company's reason threshold (None: no score, e.g. the
    reason came from the LLM fallback or is "other")."""
    scores = [r.get("score") for r in ticket.get("reasons") or []
              if r.get("reason") == ticket.get("main_reason") and isinstance(r.get("score"), (int, float))]
    if not scores or ticket.get("main_reason") == "other":
        return None
    return round(max(scores) - companies.get(companies.of(ticket))["reason_threshold"], 3)
