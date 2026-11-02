"""Agent C's links to the other agents (P20, spec "Communication links"). Tools, so they go through the allow-list.

    get_facts_from_a(order_id, deadline)     link (1) "C asks A: get the facts": Agent A reads the order with ITS tools
                                             and returns status, ETA, cause and "can meet the deadline: yes / no"
    check_availability_with_d(product_id)   link (4) "C asks D: is it available?": Agent D's stock rules answer
Link (2) "C asks B: urgent refund" is a handover (C ends with [HANDOVER: B], pipeline.py), not a tool: the refund is
B's job and B's proposal goes to the Coordinator as always, marked urgent. Link (5) "D tells A: stock-out warning" is
the line D adds to A's Intake note (agent_d.shortage_note).

Only facts from tools come back (not A's whole transcript), like ask.py for Agent B. "can meet the deadline" is worked
out here by code from A's tracking facts, never by a model:
    delivered                      -> yes
    stuck at the depot or late     -> no (no reliable ETA)
    else ETA = promised date       -> yes if ETA <= deadline
"""

from datetime import date

from callverse import companies, trace
from callverse.agents.ask import compact_facts

ASKER_ROLE_KEY = "agent_c"   # A's sub-run uses C's models (like B's sub-call uses B's)


def can_meet(facts: dict, deadline: str | None) -> tuple[str | None, bool | None, str]:
    """(eta, can_meet_deadline, cause) from A's tracking facts. None = unknown (no deadline or no facts)."""
    if "error" in facts:
        return None, None, facts["error"]
    if facts.get("delivered"):
        return facts.get("delivered_date"), True, "already delivered"
    if facts.get("status") == "stuck_at_depot" or (facts.get("days_late") or 0) > 0:
        cause = "stuck at the delivery depot" if facts.get("status") == "stuck_at_depot" else "late"
        return None, False if deadline else None, f"{cause}, {facts.get('days_late')} days late"
    eta = facts.get("promised_date")
    if not deadline:
        return eta, None, "on time"
    try:
        ok = date.fromisoformat(eta) <= date.fromisoformat(deadline)
    except (TypeError, ValueError):
        return eta, None, "deadline must be a date YYYY-MM-DD"
    return eta, ok, "on time"


def get_facts_from_a(order_id=None, deadline=None, chat_fn=None, company: str = companies.DEFAULT,
                     booking_type=None) -> dict:
    """Ask Agent A for the delivery facts of an order and whether it can arrive by `deadline` (YYYY-MM-DD)."""
    if isinstance(order_id, bool) or not isinstance(order_id, int):
        return {"error": "order_id must be an integer"}
    from callverse.agents.agent_a import AgentA   # imported here: agent_a -> registry -> this file
    # T26: the registry passes booking_type to every tool that runs an agent (main, T14f); A gets it too.
    agent_a = AgentA(chat_fn=chat_fn, company=company, booking_type=booking_type)
    agent_a.role_key = ASKER_ROLE_KEY
    result = agent_a.run(f"Delivery status, promised date and days_late of order {order_id}?")
    facts = compact_facts(result["tool_calls"])
    eta, ok, cause = can_meet(facts, deadline)
    out = {"agent": "A", "facts": facts, "eta": eta, "deadline": deadline, "can_meet_deadline": ok, "cause": cause}
    trace.log("ask_agent", "ask", {"from": "C", "to": "A", "order_id": order_id, **out})
    return out


def check_availability_with_d(order_id=None, product_id=None, qty=1, chat_fn=None,
                              company: str = companies.DEFAULT, booking_type=None) -> dict:
    """Ask Agent D (rules) whether the items of an order (order_id), or `qty` units of one product, are available.
    By order: the product ids come from the order itself, so the model never has to guess one (seen in the P20 eval).
    booking_type is set by the registry for every tool that runs an agent (T26 merge); D does not use it."""
    from callverse.agents.agent_d import availability   # imported here: agent_d -> coordinator -> registry
    if order_id is not None:
        from callverse.tools.shopnova_tools import get_order
        order = get_order(order_id) if isinstance(order_id, int) and not isinstance(order_id, bool) else {"error": "bad id"}
        if "error" in order:
            return {"error": f"order {order_id} not found"}
        out = {"agent": "D", "order_id": order_id,
               "items": [availability(i["product_id"], int(i.get("qty") or 1)) for i in order["items"]
                         if isinstance(i.get("product_id"), int)]}
    else:
        out = availability(product_id, qty)
    trace.log("ask_agent", "ask", {"from": "C", "to": "D", "product_id": product_id, "qty": qty, "result": out})
    return out


SCHEMAS = {
    "get_facts_from_a": {"type": "function", "function": {
        "name": "get_facts_from_a",
        "description": "Ask Agent A for an order's delivery facts and if it can arrive by the client's deadline.",
        "parameters": {"type": "object", "properties": {
            "order_id": {"type": "integer"},
            "deadline": {"type": "string", "description": "the date the client needs it, YYYY-MM-DD (if given)"}},
            "required": ["order_id"]}}},
    "check_availability_with_d": {"type": "function", "function": {
        "name": "check_availability_with_d",
        "description": "Ask Agent D if the items of an order (give order_id) or one product are available in stock.",
        "parameters": {"type": "object", "properties": {"order_id": {"type": "integer"}, "product_id": {"type": "integer"},
                                                        "qty": {"type": "integer"}}}}},
}
FUNCTIONS = {"get_facts_from_a": get_facts_from_a, "check_availability_with_d": check_availability_with_d}
