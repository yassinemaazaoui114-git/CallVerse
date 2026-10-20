"""The first end-to-end flow: client message -> Intake -> Router -> Agent A (or a recorded handover to B).

    handle(message) -> {ticket, route, answer, handover}

Agent B is not built yet (later task): when the route is B, or Agent A signals [HANDOVER: B],
the handover is recorded in the trace and the client gets a fixed holding answer.
"""

from callverse import trace
from callverse.agents.agent_a import AgentA
from callverse.intake import intake
from callverse.queues.router import route

HANDOVER_ANSWER = "Your request is passed to our refund team."


def ticket_note(ticket: dict) -> str:
    """Short note from Intake added to the client message, so Agent A knows the order and the reason."""
    return f"[Intake note: order id = {ticket['order_id']}, main reason = {ticket['main_reason']}]"


def handle_ticket(ticket: dict, chat_fn=None) -> dict:
    """Route an existing ticket and answer it (used by handle() and by the queue batch)."""
    decision = route(ticket)
    answer, handover = None, None

    if decision["agent"] == "A":
        result = AgentA(chat_fn=chat_fn).run(f"{ticket['text']}\n\n{ticket_note(ticket)}")
        answer, handover = result["answer"], result.get("handover")

    if decision["agent"] == "B" or handover == "B":
        handover = "B"
        answer = HANDOVER_ANSWER
        trace.log("handover", "pipeline", {"ticket_id": ticket["ticket_id"], "to": "B",
                                           "by": "router" if decision["agent"] == "B" else "agent_A"})

    out = {"ticket": ticket, "route": decision, "answer": answer, "handover": handover}
    trace.log("pipeline_done", "pipeline", {"ticket_id": ticket["ticket_id"], "route": decision,
                                            "answer": answer, "handover": handover})
    return out


def handle(message: str, chat_fn=None, use_llm: bool = True) -> dict:
    """Whole flow for one message. chat_fn = fake LLM for tests (used by Agent A and the Intake fallback)."""
    ticket = intake.process(message, use_llm=use_llm, chat_fn=chat_fn)
    return handle_ticket(ticket, chat_fn=chat_fn)
