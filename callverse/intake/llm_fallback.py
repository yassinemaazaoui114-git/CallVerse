"""LLM fallback (M2) for the messages the embedding matcher could not understand (needs_llm).

Why only for those? The local matcher is free, fast and predictable; the API model costs money and time.
So M2 is a backup, not the default path.

The LLM must answer in JSON with reasons from the company's fixed list. We never trust its answer blindly:
the JSON is validated, unknown reasons are dropped, and anything invalid becomes reason "other".
The order_id it returns is only a hint: intake.py still checks it with the get_order tool.
"""

import json
import re

from callverse import companies, llm, trace
from callverse.intake.reasons import REASONS

PROMPT = """You sort customer messages of ShopNova, an online shop.
Possible contact reasons (use ONLY these names):
- order_status: where is my order, tracking, shipping status
- late_delivery: the order is late or the delivery date has passed
- refund_request: the client wants money back, a refund, compensation
- cancel_order: the client wants to cancel an order
- return_item: the client wants to return or exchange an item, or asks about the return policy
- damaged_item: the item arrived broken, defective, damaged or wrong
- other: anything else

A message can have several reasons. Answer with JSON only, no other text:
{"reasons": ["<reason>", ...], "order_id": <order number as an integer, or null>}"""

# T21: the same job for Atlas Travel, with its own reasons and words.
ATLAS_PROMPT = """You sort customer messages of Atlas Travel, a travel agency that sells hotel stays and flights.
Possible contact reasons (use ONLY these names):
- booking_status: details or status of a hotel or flight booking
- delay_disruption: a flight is delayed, or the client asks what is going on with a delay
- cancellation: the client wants to cancel a booking, or asks how cancelling works
- refund_request: the client wants money back
- compensation_request: the client claims compensation for a delay or a cancelled flight
- rebooking: the client wants to change a flight or a hotel stay to another date or trip
- special_assistance: wheelchair or other help at the airport or on the flight
- other: anything else

A message can have several reasons. Answer with JSON only, no other text:
{"reasons": ["<reason>", ...], "order_id": <booking number as an integer, or null>}"""

PROMPTS = {"shopnova": PROMPT, "atlas": ATLAS_PROMPT}


def parse_answer(text: str | None, allowed: list[str] = REASONS) -> dict:
    """Turn the LLM's text into {"reasons": [...], "order_id": int|None, "valid": bool}.

    Invalid JSON, a wrong shape or no known reason -> {"reasons": ["other"], "order_id": None, "valid": False}.
    """
    invalid = {"reasons": ["other"], "order_id": None, "valid": False}
    if not text:
        return invalid

    # Models sometimes wrap JSON in ```json ... ```: take the part between the first { and the last }.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return invalid
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return invalid
    if not isinstance(data, dict) or not isinstance(data.get("reasons"), list):
        return invalid

    reasons = [r for r in data["reasons"] if r in allowed]   # drop invented reason names
    reasons = list(dict.fromkeys(reasons))                   # remove duplicates, keep order
    if not reasons:
        return invalid
    if len(reasons) > 1 and "other" in reasons:
        reasons.remove("other")

    order_id = data.get("order_id")
    if not isinstance(order_id, int) or isinstance(order_id, bool):
        order_id = None
    return {"reasons": reasons, "order_id": order_id, "valid": True}


def classify(text: str, chat_fn=None, company: str = companies.DEFAULT) -> dict:
    """Ask M2 for the reasons of `text`. chat_fn can be replaced by a fake in tests (no API call)."""
    chat_fn = chat_fn or llm.chat
    messages = [{"role": "system", "content": PROMPTS[company]}, {"role": "user", "content": text}]
    try:
        reply = chat_fn("agents", messages)
        result = parse_answer(reply.content, companies.get(company)["reasons"])
    except llm.AllModelsFailed as e:
        result = {"reasons": ["other"], "order_id": None, "valid": False, "error": str(e)}
    trace.log("intake_llm_fallback", "intake", {"text": text, "result": result})
    return result
