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
"""

import time
import uuid

from callverse import trace
from callverse.intake import extract, llm_fallback, priority, reasons, sentiment, style
from callverse.config import load_config
from callverse.tools.registry import run_tool


def pick_main_reason(found: list[str]) -> str:
    """The first reason of config intake.main_reason_order that is in `found` (e.g. refund beats late)."""
    order = load_config()["intake"]["main_reason_order"]
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


def process(text: str, use_llm: bool = True, chat_fn=None) -> dict:
    """Run the whole pipeline on one message and return the ticket.

    use_llm=False: never call M2 (tests); a message without a reason then gets reason "other".
    chat_fn: optional fake LLM for tests.
    """
    start = time.perf_counter()
    ticket_id = "T-" + uuid.uuid4().hex[:8]
    trace.log("intake_start", "intake", {"ticket_id": ticket_id, "text": text})

    # 1. Identifiers (regex).
    ids = extract.extract(text)
    trace.log("intake_extract", "intake", {"ticket_id": ticket_id, **ids})

    # 2. Reasons by meaning (embeddings).
    matched = reasons.match_reasons(text)
    trace.log("intake_reasons", "intake", {"ticket_id": ticket_id, **matched})
    found = [r["reason"] for r in matched["reasons"]]
    order_id = ids["order_id"]

    # 3. LLM fallback, only when the matcher found nothing.
    if matched["needs_llm"]:
        if use_llm:
            answer = llm_fallback.classify(text, chat_fn=chat_fn)
            found = answer["reasons"]
            if order_id is None:
                order_id = answer["order_id"]   # only a hint: checked with get_order just below
        else:
            found = ["other"]

    # 4. Facts from the read tools.
    facts = get_facts(order_id)
    trace.log("intake_facts", "intake", {"ticket_id": ticket_id, "order_id": order_id, **facts})

    # 5. Emotion and sentiment.
    feelings = sentiment.analyze(text)
    trace.log("intake_sentiment", "intake", {"ticket_id": ticket_id, **feelings})

    # 6. Priority.
    prio = priority.compute(found, facts, feelings["negative_score"])
    trace.log("intake_priority", "intake", {"ticket_id": ticket_id, "reasons": found, **prio})

    # 7. Style.
    writing = style.profile(text)

    ticket = {
        "ticket_id": ticket_id,
        "text": text,
        "order_id": order_id,
        "email": ids["email"],
        "phone": ids["phone"],
        # each reason = one sub-case; score/sentence are None when the reason came from the LLM fallback
        "reasons": matched["reasons"] if not matched["needs_llm"] else
                   [{"reason": r, "score": None, "sentence": None} for r in found],
        "main_reason": pick_main_reason(found),   # by precedence (config), not by score
        "emotion": feelings["emotion"],
        "sentiment": feelings["sentiment"],
        "facts": {"days_late": facts["days_late"], "delivered": facts["delivered"], "paid": facts["paid"]},
        **prio,
        "style": writing,
        "needs_llm": matched["needs_llm"],
        "seconds": round(time.perf_counter() - start, 3),
    }
    trace.log("intake_ticket", "intake", ticket)
    return ticket


def load_models() -> None:
    """Load all local models once (M3 + M4), so the first message is not slow."""
    reasons.example_vectors()
    reasons.get_model()
    sentiment.load_models()
