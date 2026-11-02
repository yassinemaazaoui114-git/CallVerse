"""Fixed reply templates, one per outcome: the safety net when the SLM's reply fails the rule check twice.

They only use the decision's own facts, order id and next step, so they always pass the check.
They are plain on purpose (less adapted to the client's style than the SLM): correct comes before nice.
"""

from callverse import companies
from callverse.config import load_config
from callverse.slm import reply_styles

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
    # T14a: the reason itself is in must_say, added at the end of the template
    "decline": "we have checked your request",
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


def apology_text(style: dict | None) -> str:
    """The fixed apology sentence for this formality (config.yaml slm.calm_openers), upset client or not."""
    openers = load_config()["slm"]["calm_openers"]
    return openers.get((style or {}).get("formality"), openers["neutral"])


def calm_opener(style: dict | None) -> str | None:
    """The fixed calm first sentence for an upset client (config.yaml slm.calm_openers), else None."""
    if not is_upset(style):
        return None
    return apology_text(style)


def is_redirect(decision: dict) -> bool:
    """The off-topic answer ("I can help with your ... orders / bookings"). T14b: ShopNova; T14c: Atlas too."""
    return decision.get("action") == "redirect"


def decision_opener(decision: dict) -> str | None:
    """The calm opener for THIS decision. T14b: none for the off-topic redirect: the client is not upset about an order,
    so "I'm sorry for the trouble." before "I can help with your ShopNova orders" would be odd. The scope sentence stands alone.
    T14c: the same for Atlas's redirect.
    (RL1b: a reply style does not use this opener rule: see render_styled.)"""
    if is_redirect(decision):
        return None
    return calm_opener(decision.get("style"))


def render(decision: dict) -> str:
    """The template reply for this decision. With a reply style (RL1b) -> render_styled; none = today's template.
    The off-topic redirect is a fixed text and ignores the style (T14c)."""
    name = None if is_redirect(decision) else reply_styles.of(decision)
    if name:
        return render_styled(decision, name)
    return _render_plain(decision)


def decision_body(decision: dict) -> str:
    """RL1b: the decision only, without greeting or opener: the sentences the Coordinator requires (must_say), then the
    next step. Atlas must always name its booking (ShopNova: not needed since T14b). With nothing to copy: the plain
    template without its greeting."""
    said = []
    for item in list(decision.get("must_say") or []) + [decision.get("next_step") or ""]:
        item = str(item).strip()
        if item and item not in said:
            said.append(item)
    if not said:
        plain = _render_plain({**decision, "style": {**(decision.get("style") or {}), "shouting": False, "sentiment": None}})
        return plain.split(", ", 1)[1] if ", " in plain else plain   # drop "Hello, " / "Hi, "
    text = " ".join(said)
    order = decision.get("order_id")
    if order is not None and str(order) not in text and decision.get("company") not in (None, companies.DEFAULT):
        text = f"Regarding {case_word(decision)} {order}. {text}"
    return text


def render_styled(decision: dict, name: str) -> str:
    """RL1b template of a reply style: greeting (by code) + [warm: the fixed calm opener] + the decision
    + [warm_next_step: the closing line of the outcome]. Always passes the rule check (only the decision's own words)."""
    spec = reply_styles.REPLY_STYLES[name]
    parts = [reply_styles.greeting(decision)]
    if spec["empathy"]:
        parts.append(apology_text(decision.get("style")))
    parts.append(decision_body(decision))   # capitals after the greeting: writer.polish fixes them
    text = " ".join(parts)
    if spec["closing"] and reply_styles.closing_line(decision):
        text = reply_styles.put_last(text, reply_styles.closing_line(decision))
    return text


def _render_plain(decision: dict) -> str:
    """The template reply for this decision's outcome (falls back to "info" for an unknown outcome)."""
    outcome = decision.get("outcome") if decision.get("outcome") in OPENING else "info"
    facts = decision.get("facts") or {}
    style = decision.get("style") or {}
    order = decision.get("order_id")

    if is_redirect(decision):
        # T14b: the off-topic reply is the Coordinator's two sentences after a greeting; the generic "here is the latest
        # information" opening and the next step BEFORE the sentence read oddly for it. T14c: both companies, and it is
        # the reply itself (no SLM call, see writer.write_reply).
        said = [str(x).strip() for x in decision.get("must_say") or []] + [str(decision.get("next_step") or "").strip()]
        return f"{_greeting(style)}, {' '.join(x for x in said if x)}"
    if outcome == "decline" and decision.get("company") not in (None, companies.DEFAULT):
        # T14c, Atlas: the reason (must_say) first, then the next step ("You can still choose a full refund ...").
        opener = decision_opener(decision)
        first = f"{OPENING[outcome].capitalize()}{f' about your {case_word(decision)} {order}' if order is not None else ''}."
        said = [str(x).strip() for x in decision.get("must_say") or []] + [str(decision.get("next_step") or "").strip()]
        return " ".join([f"{opener} {first}" if opener else f"{_greeting(style)}, {first}"] + [x for x in said if x])

    about = f" about your {case_word(decision)} {order}" if order is not None else ""
    opener = decision_opener(decision)
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
