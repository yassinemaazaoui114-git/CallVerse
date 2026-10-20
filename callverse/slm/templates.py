"""Fixed reply templates, one per outcome: the safety net when the SLM's reply fails the rule check twice.

They only use the decision's own facts, order id and next step, so they always pass the check.
They are plain on purpose (less adapted to the client's style than the SLM): correct comes before nice.
"""

# How each known fact is said. Unknown fact keys are left out (safe: saying less is never wrong).
FACT_PHRASES = {
    "order_status": lambda v: f"its current status is {str(v).replace('_', ' ')}",
    "days_late": lambda v: f"it is {v} day{'s' if v != 1 else ''} late" if v else "it is on time",
    "promised_date": lambda v: f"the promised delivery date was {v}",
    "carrier": lambda v: f"the carrier is {v}",
    "amount_tnd": lambda v: f"the amount is {float(v):.2f} TND",
}

OPENING = {
    "approve": "your request has been approved",
    "send_back": "we are still checking your request",
    "ask_user": "we need one more detail from you",
    "ask_proof": "we need a proof before we can go further",
    "layer3": "your refund request needs approval from our finance team",
    "escalate": "a colleague will take over your request",
    "info": "here is the latest information",
}


def _greeting(style: dict) -> str:
    return "Hi" if (style or {}).get("formality") == "casual" else "Hello"


def _calm(style: dict) -> str:
    style = style or {}
    upset = style.get("shouting") or style.get("sentiment") == "negative" or \
        style.get("emotion") in ("anger", "disgust", "fear", "sadness")
    return "We understand this is frustrating. " if upset else ""


def render(decision: dict) -> str:
    """The template reply for this decision's outcome (falls back to "info" for an unknown outcome)."""
    outcome = decision.get("outcome") if decision.get("outcome") in OPENING else "info"
    facts = decision.get("facts") or {}
    style = decision.get("style") or {}
    order = decision.get("order_id")

    about = f" about your order {order}" if order is not None else ""
    parts = [f"{_greeting(style)}, {_calm(style)}{OPENING[outcome].capitalize()}{about}."]

    details = [FACT_PHRASES[k](v) for k, v in facts.items() if k in FACT_PHRASES and v is not None]
    if outcome == "approve" and decision.get("action") == "subscribe" and facts.get("event"):
        details.append(f"you will get a message when it is {str(facts['event']).replace('_', ' ')}")
    if outcome == "ask_proof" and facts.get("needed"):
        details.append(f"please send us: {facts['needed']}")
    if outcome == "layer3" and facts.get("threshold_tnd") is not None:
        details.append(f"refunds above {float(facts['threshold_tnd']):.2f} TND need this approval")
    if details:
        text = "; ".join(details)
        parts.append(text[0].upper() + text[1:] + ".")

    if decision.get("next_step"):
        parts.append(str(decision["next_step"]).strip())
    return " ".join(parts)
