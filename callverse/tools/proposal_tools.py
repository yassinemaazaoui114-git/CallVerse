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
