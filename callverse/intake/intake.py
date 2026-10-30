"""Intake: turn a raw client message into a labelled TICKET. A fixed pipeline, not an agent.

Steps (each one is traced):
  1. extract   - order number, email, phone (regular expressions, extract.py)
  2. reasons   - why the client writes, by meaning (embeddings M3, reasons.py)
  3. fallback  - only if no reason was found: ask M2 (llm_fallback.py)
  4. facts     - days_late, delivered, paid from the READ tools get_order / get_tracking (never writes)
  5. sentiment - emotion + sentiment (local classifiers M4, sentiment.py)
  6. priority  - from the facts first, emotion second (priority.py, weights in config.yaml)
  7. style     - how the client writes (style.py)

Why not an agent? Every message must go through the same steps in the same order, cheaply and
predictably. There is no decision to "reason" about, so an LLM loop would only add cost and risk.
The ticket is what the Queues will route (Agent A or B, by reason and priority).

T21: the same steps for every company, with its own reasons, facts and priority. The company comes from the channel,
never from the text, and it goes on the ticket. At Atlas the number is a booking: `order_id` stays the shared name of
"the number of the case", and `booking_type` (hotel / flight) comes from looking the number up, not from the words.
"""

import time
import uuid

from callverse import companies, trace
from callverse.data.atlas import reads as atlas_reads
from callverse.intake import extract, llm_fallback, priority, reasons, sentiment, style
from callverse.tools.registry import run_tool


def pick_main_reason(found: list[str], company: str = companies.DEFAULT) -> str:
    """The first reason of the company's main_reason_order that is in `found` (e.g. refund beats late)."""
    order = companies.get(company)["main_reason_order"]
    return next((r for r in order if r in found), found[0])


def get_facts(order_id: int | None) -> dict:
    """Facts about the order, read with the existing READ tools. All None when there is no (known) order.

    Intake goes through the registry like the agents (allow-list "INTAKE" = get_order, get_tracking),
    so the same gate checks and traces every read.
    """
    facts = {"order_found": False, "days_late": None, "delivered": None, "paid": None}
    if order_id is None:
        return facts

    order = run_tool("INTAKE", "get_order", {"order_id": order_id})
    if "error" in order:
        return facts

    tracking = run_tool("INTAKE", "get_tracking", {"order_id": order_id})
    return {"order_found": True, "days_late": tracking.get("days_late"),
            "delivered": tracking.get("delivered"), "paid": order.get("paid")}


def get_booking_facts(booking_id: int | None) -> dict:
    """Atlas: facts about the booking, read with the READ tools (the same gate, never a write). The number says
    which table it is in; hours_to_start = hours to the departure or the arrival."""
    facts = {"order_found": False, "booking_type": None, "status": None, "paid": None, "hours_to_start": None}
    kind = atlas_reads.booking_type(booking_id) if booking_id is not None else None
    if kind is None:
        return facts
    tool = "get_flight_booking" if kind == "flight" else "get_hotel_booking"
    booking = run_tool("INTAKE", tool, {"booking_id": booking_id}, company="atlas")
    if "error" in booking:
        return facts
    hours = booking["hours_before_departure"] if kind == "flight" else booking["hours_before_arrival"]
    return {"order_found": True, "booking_type": kind, "status": booking["status"], "paid": booking["paid_tnd"],
            "hours_to_start": hours}


def process(text: str, use_llm: bool = True, chat_fn=None, company: str = companies.DEFAULT) -> dict:
    """Run the whole pipeline on one message and return the ticket.

    use_llm=False: never call M2 (tests); a message without a reason then gets reason "other".
    chat_fn: optional fake LLM for tests.
    company: from the channel; every step below uses this company's reasons, facts and priority.
    """
    start = time.perf_counter()
    ticket_id = "T-" + uuid.uuid4().hex[:8]
    trace.log("intake_start", "intake", {"ticket_id": ticket_id, "text": text})

    # 1. Identifiers (regex).
    ids = extract.extract(text, company)
    trace.log("intake_extract", "intake", {"ticket_id": ticket_id, **ids})

    # 2. Reasons by meaning (embeddings).
    matched = reasons.match_reasons(text, company=company)
    trace.log("intake_reasons", "intake", {"ticket_id": ticket_id, **matched})
    found = [r["reason"] for r in matched["reasons"]]
    order_id = ids["order_id"]

    # 3. LLM fallback, only when the matcher found nothing.
    if matched["needs_llm"]:
        if use_llm:
            answer = llm_fallback.classify(text, chat_fn=chat_fn, **companies.extra_args(company))
            found = answer["reasons"]
            if order_id is None:
                order_id = answer["order_id"]   # only a hint: checked with get_order just below
        else:
            found = ["other"]

    # 4. Facts from the read tools.
    facts = get_booking_facts(order_id) if company == "atlas" else get_facts(order_id)
    trace.log("intake_facts", "intake", {"ticket_id": ticket_id, "order_id": order_id, **facts})

    # 5. Emotion and sentiment.
    feelings = sentiment.analyze(text)
    trace.log("intake_sentiment", "intake", {"ticket_id": ticket_id, **feelings})

    # 6. Priority.
    prio = priority.compute(found, facts, feelings["negative_score"], company)
    trace.log("intake_priority", "intake", {"ticket_id": ticket_id, "reasons": found, **prio})

    # 7. Style.
    writing = style.profile(text)

    ticket = {
        "ticket_id": ticket_id,
        "company": company,
        "text": text,
        "order_id": order_id,
        "email": ids["email"],
        "phone": ids["phone"],
        # each reason = one sub-case; score/sentence are None when the reason came from the LLM fallback
        "reasons": matched["reasons"] if not matched["needs_llm"] else
                   [{"reason": r, "score": None, "sentence": None} for r in found],
        "main_reason": pick_main_reason(found, company),   # by precedence (config), not by score
        "emotion": feelings["emotion"],
        "sentiment": feelings["sentiment"],
        "facts": ({"status": facts["status"], "paid": facts["paid"], "hours_to_start": facts["hours_to_start"]}
                  if company == "atlas" else
                  {"days_late": facts["days_late"], "delivered": facts["delivered"], "paid": facts["paid"]}),
        **prio,
        "style": writing,
        "needs_llm": matched["needs_llm"],
        "seconds": round(time.perf_counter() - start, 3),
    }
    if company == "atlas":
        ticket["booking_type"] = facts["booking_type"]
    trace.log("intake_ticket", "intake", ticket)
    return ticket


def load_models() -> None:
    """Load all local models once (M3 + M4), so the first message is not slow."""
    for company in companies.names():
        reasons.example_vectors(company)
    reasons.get_model()
    sentiment.load_models()
