"""ACTION tools: they never act. They only build a PROPOSAL for the Coordinator.

Rule of the project: agents never act directly. When Agent B thinks a refund is due, it calls
propose_refund(...). That call does NOT pay anything and does NOT touch the database:
  1. it checks that the fields are complete and of the right type (else the proposal is refused,
     so the agent can fix it at once);
  2. it writes the proposal to the trace (step "proposal") and answers "submitted to Coordinator".
Then the pipeline gives the proposal to the Coordinator (rules, no LLM), which records it in the
platform's `proposals` table (id P-0001, P-0002, ...), checks it against the re-read data and the
policy, and is the only part allowed to write.

What is checked here is only the SHAPE of the proposal. Whether the rule really applies
(days_late > 5, amount <= paid - refunded_total, ...) is the Coordinator's job, not this tool's.

T21: Atlas's proposal tools are at the end of this file. They take NO amount at all: the Atlas Coordinator computes it
from the rules, so a wrong or invented amount cannot even be written down by an agent.
"""

import math

from callverse import trace
from callverse.kb.policies import get_policy


def _problems(order_id, amount, rule_id, facts_used, user_confirmed, user_quote) -> list[str]:
    """Everything wrong with the fields (empty list = the proposal is well formed)."""
    problems = []
    # bool is a kind of int in Python, so True/False are refused explicitly.
    if isinstance(order_id, bool) or not isinstance(order_id, int):
        problems.append("order_id must be an integer")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount <= 0:
        problems.append("amount must be a number > 0")
    if not isinstance(rule_id, str) or not rule_id.strip():
        problems.append("rule_id is missing: cite the rule found with search_policy")
    elif get_policy(rule_id) is None:
        problems.append(f"rule_id {rule_id} does not exist")
    if not isinstance(facts_used, dict) or not facts_used:
        problems.append("facts_used must be a non-empty object of the facts read from tools")
    if not isinstance(user_confirmed, bool):
        problems.append("user_confirmed must be true or false")
    if not isinstance(user_quote, str) or not user_quote.strip():
        problems.append("user_quote must quote the client's own words")
    return problems


def refund_proposal(agent: str, args: dict) -> dict:
    """The proposal in the platform's shape (docs/platform_contract.md), built from propose_refund's arguments."""
    return {"agent": agent, "action": "refund",
            "params": {"order_id": args["order_id"], "amount": round(float(args["amount"]), 2)},
            "rule_id": args["rule_id"], "facts_used": args["facts_used"],
            "user_confirmed": args["user_confirmed"], "user_quote": args["user_quote"]}


def propose_refund(order_id=None, amount=None, rule_id=None, facts_used=None,
                   user_confirmed=None, user_quote=None) -> dict:
    """Submit a refund PROPOSAL to the Coordinator. Pays nothing, writes nothing in the database."""
    fields = {"order_id": order_id, "amount": amount, "rule_id": rule_id, "facts_used": facts_used,
              "user_confirmed": user_confirmed, "user_quote": user_quote}

    problems = _problems(**fields)
    if problems:
        trace.log("proposal_refused", "proposal_tools", {"fields": fields, "problems": problems})
        return {"error": "proposal refused: " + "; ".join(problems)}

    trace.log("proposal", "proposal_tools", fields)
    return {"status": "submitted to Coordinator"}


# --- T09: Agent A proposes a delivery notification (story S3) -------------------------------------------

def subscription_proposal(agent: str, args: dict) -> dict:
    """The subscribe proposal in the platform's shape, from propose_subscription's arguments.

    rule R-NOT-01 (notifications). user_confirmed is True: the agent calls this tool only when the client
    asked to be told (or accepted the offer); user_quote keeps the client's words as the evidence."""
    return {"agent": agent, "action": "subscribe",
            "params": {"order_id": args["order_id"], "event": args.get("event") or "delivered"},
            "rule_id": "R-NOT-01", "facts_used": {"event": args.get("event") or "delivered"},
            "user_confirmed": True, "user_quote": args["user_quote"]}


def propose_subscription(order_id=None, event="delivered", user_quote=None) -> dict:
    """Ask the Coordinator to record a delivery notification. Sends nothing, writes nothing in the database.

    event: shipped, out_for_delivery or delivered (the R-NOT-01 events); "when it arrives" = delivered."""
    from callverse.kb.policies import notification_events
    fields = {"order_id": order_id, "event": event or "delivered", "user_quote": user_quote}
    problems = []
    if isinstance(order_id, bool) or not isinstance(order_id, int):
        problems.append("order_id must be an integer")
    if fields["event"] not in notification_events():
        problems.append(f"event must be one of {notification_events()}")
    if not isinstance(user_quote, str) or not user_quote.strip():
        problems.append("user_quote must quote the client's own words")
    if problems:
        trace.log("proposal_refused", "proposal_tools", {"fields": fields, "problems": problems})
        return {"error": "proposal refused: " + "; ".join(problems)}

    trace.log("proposal", "proposal_tools", {"action": "subscribe", **fields})
    return {"status": "submitted to Coordinator"}


SUBSCRIPTION_SCHEMA = {
    "type": "function",
    "function": {
        "name": "propose_subscription",
        "description": "Ask for a message to the client when the order reaches an event. Sends nothing itself.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "integer"},
                "event": {"type": "string", "enum": ["shipped", "out_for_delivery", "delivered"],
                          "description": "'when it arrives' = delivered"},
                "user_quote": {"type": "string"},
            },
            "required": ["order_id", "event", "user_quote"],
        },
    },
}


# --- T21: Atlas Travel's proposals: no amount ----------------------------------------------------------

BOOKING_TYPES = ("hotel", "flight")


def _booking_problems(booking_type, booking_id, rule_id, facts_used, user_confirmed, user_quote) -> list[str]:
    """Everything wrong with the fields of an Atlas proposal (empty list = well formed)."""
    problems = []
    if booking_type not in BOOKING_TYPES:
        problems.append("booking_type must be hotel or flight")
    if isinstance(booking_id, bool) or not isinstance(booking_id, int):
        problems.append("booking_id must be an integer")
    if not isinstance(rule_id, str) or not rule_id.strip():
        problems.append("rule_id is missing: cite the rule found with search_policy")
    elif get_policy(rule_id, "atlas") is None:
        problems.append(f"rule_id {rule_id} does not exist")
    if not isinstance(facts_used, dict) or not facts_used:
        problems.append("facts_used must be a non-empty object of the facts read from tools")
    if not isinstance(user_confirmed, bool):
        problems.append("user_confirmed must be true or false")
    if not isinstance(user_quote, str) or not user_quote.strip():
        problems.append("user_quote must quote the client's own words")
    return problems


def _propose_for_atlas(action: str, fields: dict) -> dict:
    problems = _booking_problems(**fields)
    if problems:
        trace.log("proposal_refused", "proposal_tools", {"action": action, "fields": fields, "problems": problems})
        return {"error": "proposal refused: " + "; ".join(problems)}
    trace.log("proposal", "proposal_tools", {"action": action, **fields})
    return {"status": "submitted to Coordinator"}


def propose_atlas_refund(booking_type=None, booking_id=None, rule_id=None, facts_used=None,
                         user_confirmed=None, user_quote=None) -> dict:
    """Submit a refund PROPOSAL for an Atlas booking. Pays nothing, writes nothing, takes no amount."""
    return _propose_for_atlas("refund", {"booking_type": booking_type, "booking_id": booking_id, "rule_id": rule_id,
                                         "facts_used": facts_used, "user_confirmed": user_confirmed,
                                         "user_quote": user_quote})


def propose_compensation(booking_type=None, booking_id=None, rule_id=None, facts_used=None,
                         user_confirmed=None, user_quote=None) -> dict:
    """Submit a compensation PROPOSAL for an Atlas booking. Pays nothing, writes nothing, takes no amount."""
    return _propose_for_atlas("compensation", {"booking_type": booking_type, "booking_id": booking_id,
                                               "rule_id": rule_id, "facts_used": facts_used,
                                               "user_confirmed": user_confirmed, "user_quote": user_quote})


def propose_hotel_cancellation(booking_type=None, booking_id=None, rule_id=None, facts_used=None,
                               user_confirmed=None, user_quote=None) -> dict:
    """Submit a cancellation PROPOSAL for an Atlas hotel booking. Cancels nothing, writes nothing, takes no amount."""
    return _propose_for_atlas("cancel_hotel", {"booking_type": booking_type, "booking_id": booking_id,
                                               "rule_id": rule_id, "facts_used": facts_used,
                                               "user_confirmed": user_confirmed, "user_quote": user_quote})


def atlas_proposal(agent: str, action: str, args: dict) -> dict:
    """The proposal in the shape the Atlas Coordinator reads, from a proposal tool's arguments."""
    return {"agent": agent, "action": action,
            "params": {"booking_type": args["booking_type"], "booking_id": args["booking_id"]},
            "rule_id": args["rule_id"], "facts_used": args["facts_used"],
            "user_confirmed": args["user_confirmed"], "user_quote": args["user_quote"]}


def _atlas_schema(name: str, description: str) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object",
        "properties": {"booking_type": {"type": "string", "enum": list(BOOKING_TYPES)},
                       "booking_id": {"type": "integer"}, "rule_id": {"type": "string"},
                       "facts_used": {"type": "object"}, "user_confirmed": {"type": "boolean"},
                       "user_quote": {"type": "string"}},
        "required": ["booking_type", "booking_id", "rule_id", "facts_used", "user_confirmed", "user_quote"]}}}


# Tool name -> the action it proposes, the function and the schema the model sees (no amount in any of them).
ATLAS_ACTIONS = {"propose_refund": "refund", "propose_compensation": "compensation",
                 "propose_hotel_cancellation": "cancel_hotel"}
ATLAS_FUNCTIONS = {"propose_refund": propose_atlas_refund, "propose_compensation": propose_compensation,
                   "propose_hotel_cancellation": propose_hotel_cancellation}
ATLAS_SCHEMAS = {
    "propose_refund": _atlas_schema("propose_refund", "Send a refund proposal to the Coordinator. Pays nothing."),
    "propose_compensation": _atlas_schema("propose_compensation",
                                          "Send a compensation proposal to the Coordinator. Pays nothing."),
    "propose_hotel_cancellation": _atlas_schema("propose_hotel_cancellation",
                                                "Send a hotel cancellation proposal to the Coordinator. Cancels nothing."),
}


SCHEMA = {
    "type": "function",
    "function": {
        "name": "propose_refund",
        # Short on purpose (T07): schemas are re-sent with every model call; the prompt explains the fields.
        "description": "Send a refund proposal to the Coordinator. Pays nothing.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "integer"},
                "amount": {"type": "number"},
                "rule_id": {"type": "string"},
                "facts_used": {"type": "object"},
                "user_confirmed": {"type": "boolean"},
                "user_quote": {"type": "string"},
            },
            "required": ["order_id", "amount", "rule_id", "facts_used", "user_confirmed", "user_quote"],
        },
    },
}
