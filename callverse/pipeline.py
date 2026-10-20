"""The end-to-end flow: client message -> Intake -> Router -> Agent A or Agent B.

    handle(message) -> {ticket, route, answer, handover, handover_text, proposal}

- Route A: Agent A answers. If Agent A signals [HANDOVER: B] (the client wants money back),
  Agent B takes the same message.
- Route B: Agent B answers directly.
- handover_text: the short sentence that announces the handover, per reason (config.yaml,
  queues.handover_texts), e.g. "Your request is passed on for a refund check." It is traced and
  returned for the channel to show/say; the client's answer itself is Agent B's answer.
- proposal: the refund proposal Agent B submitted for the Coordinator (T07), or None.
  Nothing is paid or written in the database here.
"""

from callverse import trace
from callverse.agents.agent_a import AgentA
from callverse.agents.agent_b import AgentB
from callverse.config import load_config
from callverse.intake import intake
from callverse.queues.router import route


def ticket_note(ticket: dict) -> str:
    """Short note from Intake added to the client message, so the agent knows the order and the reason."""
    return f"[Intake note: order id = {ticket['order_id']}, main reason = {ticket['main_reason']}]"


def handover_text(reason: str) -> str:
    """The handover sentence for this reason. Reasons routed to A (order_status, late_delivery, other)
    have no text of their own: Agent A only hands over money requests, so they get the refund text."""
    texts = load_config()["queues"]["handover_texts"]
    return texts.get(reason, texts["refund_request"])


def handle_ticket(ticket: dict, chat_fn=None) -> dict:
    """Route an existing ticket and answer it (used by handle() and by the queue batch)."""
    decision = route(ticket)
    message = f"{ticket['text']}\n\n{ticket_note(ticket)}"
    answer, handover, text, proposal = None, None, None, None

    if decision["agent"] == "A":
        result = AgentA(chat_fn=chat_fn).run(message)
        answer, handover = result["answer"], result.get("handover")

    if decision["agent"] == "B" or handover == "B":
        handover = "B"
        by = "router" if decision["agent"] == "B" else "agent_A"
        text = handover_text(ticket["main_reason"])
        trace.log("handover", "pipeline", {"ticket_id": ticket["ticket_id"], "to": "B", "by": by, "text": text})
        result = AgentB(chat_fn=chat_fn).run(message)
        answer, proposal = result["answer"], result["proposal"]

    out = {"ticket": ticket, "route": decision, "answer": answer, "handover": handover,
           "handover_text": text, "proposal": proposal}
    trace.log("pipeline_done", "pipeline", {"ticket_id": ticket["ticket_id"], "route": decision,
                                            "answer": answer, "handover": handover, "proposal": proposal})
    return out


def handle(message: str, chat_fn=None, use_llm: bool = True) -> dict:
    """Whole flow for one message. chat_fn = fake LLM for tests (used by the agents and the Intake fallback)."""
    ticket = intake.process(message, use_llm=use_llm, chat_fn=chat_fn)
    return handle_ticket(ticket, chat_fn=chat_fn)
