"""Fixed reply templates, one per outcome: the safety net when the SLM's reply fails the rule check twice.

They only use the decision's own facts, order id and next step, so they always pass the check.
They are plain on purpose (less adapted to the client's style than the SLM): correct comes before nice.
"""

from callverse.config import load_config

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
    # T09
    "layer3_refused": "we are sorry, we cannot approve this refund",
    "notify": "here is news",
}


def case_word(decision: dict) -> str:
    """What the company calls the number of a case: "order", or "booking" at Atlas (T21)."""
    return decision.get("case_word") or "order"


def _greeting(style: dict) -> str:
    return "Hi" if (style or {}).get("formality") == "casual" else "Hello"


def is_upset(style: dict | None) -> bool:
    """The client shouts or writes negatively (from Intake's style): the reply starts with a calm opener."""
    style = style or {}
    return bool(style.get("shouting")) or style.get("sentiment") == "negative"


def calm_opener(style: dict | None) -> str | None:
    """The fixed calm first sentence for an upset client (config.yaml slm.calm_openers), else None."""
    if not is_upset(style):
        return None
    openers = load_config()["slm"]["calm_openers"]
    return openers.get((style or {}).get("formality"), openers["neutral"])


def render(decision: dict) -> str:
    """The template reply for this decision's outcome (falls back to "info" for an unknown outcome)."""
    outcome = decision.get("outcome") if decision.get("outcome") in OPENING else "info"
    facts = decision.get("facts") or {}
    style = decision.get("style") or {}
    order = decision.get("order_id")

    about = f" about your {case_word(decision)} {order}" if order is not None else ""
    opener = calm_opener(style)
    first = f"{OPENING[outcome].capitalize()}{about}."
    if outcome == "approve" and decision.get("action") == "subscribe":
        first = f"Sure, we can do that{' for your order ' + str(order) if order is not None else ''}."   # T10
    parts = [f"{opener} {first}" if opener else f"{_greeting(style)}, {first}"]

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
    # Exact sentences the Coordinator requires (must_say), unless already said word for word.
    for item in decision.get("must_say") or []:
        if " ".join(str(item).lower().split()) not in " ".join(" ".join(parts).lower().split()):
            parts.append(str(item).strip())
    return " ".join(parts)
