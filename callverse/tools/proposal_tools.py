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


# --- T14a: Agent B proposes a cancellation (rule R-CAN-01) -----------------------------------------------

def cancellation_proposal(agent: str, args: dict) -> dict:
    """The cancel proposal in the platform's shape, from propose_cancellation's arguments.

    No amount and no user_confirmed: the Coordinator computes the refund from the data and decides by code
    whether the client really asked (user_confirmed is False until then)."""
    return {"agent": agent, "action": "cancel", "params": {"order_id": args["order_id"]}, "rule_id": "R-CAN-01",
            "facts_used": {"order_id": args["order_id"]}, "user_confirmed": False, "user_quote": args["user_quote"]}


def propose_cancellation(order_id=None, user_quote=None) -> dict:
    """Ask the Coordinator to cancel an order. Cancels nothing, writes nothing in the database."""
    fields = {"order_id": order_id, "user_quote": user_quote}
    problems = []
    if isinstance(order_id, bool) or not isinstance(order_id, int):
        problems.append("order_id must be an integer")
    if not isinstance(user_quote, str) or not user_quote.strip():
        problems.append("user_quote must quote the client's own words")
    if problems:
        trace.log("proposal_refused", "proposal_tools", {"fields": fields, "problems": problems})
        return {"error": "proposal refused: " + "; ".join(problems)}

    trace.log("proposal", "proposal_tools", {"action": "cancel", **fields})
    return {"status": "submitted to Coordinator"}


CANCELLATION_SCHEMA = {
    "type": "function",
    "function": {
        "name": "propose_cancellation",
        "description": "Send an order cancellation proposal to the Coordinator. Cancels nothing.",
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "integer"}, "user_quote": {"type": "string"}},
            "required": ["order_id", "user_quote"],
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


# --- P20: Agent C's proposals (Urgent & Special Help) -----------------------------------------------------
# Each C action has exactly ONE rule (replace R-RPL-01, hold R-HLD-01, assistance R-AST-01), so the tool sets it:
# fewer fields for a small local model to get wrong. The Coordinator still checks that rule's condition on the
# facts it re-reads itself. user_confirmed is REQUIRED: false = the client has not said yes yet, and then the
# Coordinator only asks the client to confirm (nothing changes until the client says yes).

C_RULES = {"replace": "R-RPL-01", "hold": "R-HLD-01", "assistance": "R-AST-01"}
C_ACTIONS = {"propose_replacement": "replace", "propose_hold": "hold", "propose_assistance": "assistance"}


def _int_id(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _c_problems(fields: dict) -> list[str]:
    problems = []
    if "order_id" in fields and fields["order_id"] is not None and not _int_id(fields["order_id"]):
        problems.append("order_id must be an integer")
    for name in ("product_id", "qty", "hold_days"):
        if name in fields and not _int_id(fields[name]):
            problems.append(f"{name} must be an integer")
    if "reason" in fields and (not isinstance(fields["reason"], str) or not fields["reason"].strip()):
        problems.append("reason must say why a colleague is needed")
    if not isinstance(fields.get("user_confirmed"), bool):
        problems.append("user_confirmed must be true or false (true only if the client said yes)")
    if not isinstance(fields.get("user_quote"), str) or not fields["user_quote"].strip():
        problems.append("user_quote must quote the client's own words")
    return problems


def order_product(order_id):
    """The product of an order that has ONE product (its id), else None. A read, used when C gives no product_id."""
    from callverse.tools.shopnova_tools import get_order
    if not _int_id(order_id):
        return None
    order = get_order(order_id)
    ids = {i.get("product_id") for i in order.get("items", [])} if "error" not in order else set()
    return ids.pop() if len(ids) == 1 else None


def _with_product(fields: dict) -> dict:
    """No product_id given: the order's only product (traced in the proposal, so nothing is hidden)."""
    if fields.get("product_id") is None and "product_id" in fields:
        fields = {**fields, "product_id": order_product(fields.get("order_id"))}
    return fields


def _propose_c(action: str, fields: dict) -> dict:
    fields = _with_product(fields)
    problems = _c_problems(fields)
    if action in ("replace", "hold") and fields.get("order_id") is None:
        problems.insert(0, "order_id is required")
    if problems:
        trace.log("proposal_refused", "proposal_tools", {"action": action, "fields": fields, "problems": problems})
        return {"error": "proposal refused: " + "; ".join(problems)}
    trace.log("proposal", "proposal_tools", {"action": action, "rule_id": C_RULES[action], **fields})
    return {"status": "submitted to Coordinator"}


def propose_replacement(order_id=None, product_id=None, qty=1, user_confirmed=None, user_quote=None,
                        facts_used=None) -> dict:
    """Propose sending a new unit of an order's item (R-RPL-01). Sends nothing, writes nothing."""
    return _propose_c("replace", {"order_id": order_id, "product_id": product_id, "qty": qty,
                                  "user_confirmed": user_confirmed, "user_quote": user_quote})


def propose_hold(order_id=None, product_id=None, qty=1, hold_days=3, user_confirmed=None, user_quote=None,
                 facts_used=None) -> dict:
    """Propose keeping units of a product for the client for 1-3 days (R-HLD-01). Keeps nothing, writes nothing."""
    return _propose_c("hold", {"order_id": order_id, "product_id": product_id, "qty": qty, "hold_days": hold_days,
                               "user_confirmed": user_confirmed, "user_quote": user_quote})


def propose_assistance(order_id=None, reason=None, user_confirmed=None, user_quote=None, facts_used=None) -> dict:
    """Propose passing a hard or disputed case to a human colleague (R-AST-01). Writes nothing."""
    return _propose_c("assistance", {"order_id": order_id, "reason": reason, "user_confirmed": user_confirmed,
                                     "user_quote": user_quote})


def c_proposal(agent: str, tool: str, args: dict) -> dict:
    """The proposal in the platform's shape, from one of C's proposal tools and its (accepted) arguments."""
    action = C_ACTIONS[tool]
    keys = {"replace": ("order_id", "product_id", "qty"), "hold": ("order_id", "product_id", "qty", "hold_days"),
            "assistance": ("order_id", "reason")}[action]
    defaults = {"qty": 1, "hold_days": 3, "order_id": None}
    params = {k: args.get(k, defaults.get(k)) for k in keys}
    if "product_id" in params and params["product_id"] is None:
        params["product_id"] = order_product(params["order_id"])
    facts = args.get("facts_used") if isinstance(args.get("facts_used"), dict) else {}
    return {"agent": agent, "action": action, "params": params, "rule_id": C_RULES[action], "facts_used": facts,
            "user_confirmed": args["user_confirmed"], "user_quote": args["user_quote"]}


_CONFIRM = {"type": "boolean", "description": "true only if the client already said yes to this"}
C_SCHEMAS = {
    "propose_replacement": {"type": "function", "function": {
        "name": "propose_replacement",
        "description": "Propose a free replacement of an order's item from stock (rule R-RPL-01). Sends nothing.",
        "parameters": {"type": "object", "properties": {
            "order_id": {"type": "integer"}, "product_id": {"type": "integer", "description": "leave out: the order's item"},
            "qty": {"type": "integer"}, "user_confirmed": _CONFIRM, "user_quote": {"type": "string"}},
            "required": ["order_id", "user_confirmed", "user_quote"]}}},
    "propose_hold": {"type": "function", "function": {
        "name": "propose_hold",
        "description": "Propose keeping units of a product for the client, 1 to 3 days (rule R-HLD-01).",
        "parameters": {"type": "object", "properties": {
            "order_id": {"type": "integer"}, "product_id": {"type": "integer"}, "qty": {"type": "integer"},
            "hold_days": {"type": "integer"}, "user_confirmed": _CONFIRM, "user_quote": {"type": "string"}},
            "required": ["order_id", "product_id", "user_confirmed", "user_quote"]}}},
    "propose_assistance": {"type": "function", "function": {
        "name": "propose_assistance",
        "description": "Propose passing a hard or disputed case to a human colleague (rule R-AST-01).",
        "parameters": {"type": "object", "properties": {
            "order_id": {"type": "integer"}, "reason": {"type": "string"}, "user_confirmed": _CONFIRM,
            "user_quote": {"type": "string"}},
            "required": ["reason", "user_confirmed", "user_quote"]}}},
}
C_FUNCTIONS = {"propose_replacement": propose_replacement, "propose_hold": propose_hold,
               "propose_assistance": propose_assistance}


# --- P20: Agent D's promotion proposal (built by D's rules, not by a model) -------------------------------

def promotion_proposal(product_id: int, discount_pct: float, facts: dict, note: str) -> dict:
    """D's promotion PROPOSAL in the platform's shape. user_confirmed is False: no client is involved; the OWNER
    decides (Coordinator outcome owner_pending). note = D's sentence for the owner."""
    return {"agent": "D", "action": "promotion", "params": {"product_id": product_id, "discount_pct": discount_pct},
            "rule_id": "R-PRM-01", "facts_used": facts, "user_confirmed": False, "user_quote": "", "note": note}
