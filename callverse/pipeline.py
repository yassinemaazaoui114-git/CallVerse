"""The end-to-end flow: client message -> Intake -> Router -> Agent A or Agent B.

    handle(message) -> {ticket, route, answer, handover, handover_text, proposal, proposals, decision}

- Route A: Agent A answers. If Agent A signals [HANDOVER: B] (the client wants money back),
  Agent B takes the same message.
- Route B: Agent B answers directly.
- handover_text: the short sentence that announces the handover, per reason (config.yaml,
  queues.handover_texts), e.g. "Your request is passed on for a refund check." It is traced and
  returned for the channel to show/say; the client's answer itself is Agent B's answer.
- Coordinator (T07): when an agent submits a proposal, the Coordinator reviews it (rules, no LLM).
  On "send_back" the SAME agent gets the reason once more and may correct its proposal; the Coordinator
  allows 2 send-backs per case, the 3rd becomes "escalate". Only an approved proposal is written,
  by the Coordinator.
- proposal: the last proposal, proposals: every proposal of the case, decision: the Coordinator's
  final decision dict (None when there was no proposal).
"""

from callverse import trace
from callverse.agents.agent_a import AgentA
from callverse.agents.agent_b import AgentB
from callverse.config import load_config
from callverse.coordinator.coordinator import new_case, review
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


def run_agent_with_coordinator(agent_cls, message: str, ticket: dict, chat_fn=None) -> tuple[dict, list, dict | None]:
    """Run the agent; review each proposal it makes; on send_back let the same agent correct it.

    Returns (last agent result, all proposals, final decision or None).
    The loop ends: each send-back is counted by the Coordinator and the 3rd one becomes "escalate".
    """
    case = new_case(ticket["ticket_id"])
    result = agent_cls(chat_fn=chat_fn).run(message)
    proposals, decision = [], None
    while result.get("proposal"):
        proposals.append(result["proposal"])
        decision = review(result["proposal"], case)
        if decision["outcome"] != "send_back":
            break
        note = (f"[Coordinator: proposal {decision['proposal_id']} was sent back: {decision['reason']}. "
                f"Correct it and propose again.]")
        trace.log("send_back_to_agent", "pipeline", {"ticket_id": ticket["ticket_id"],
                                                     "agent": result["agent"], "note": note})
        result = agent_cls(chat_fn=chat_fn).run(f"{message}\n\n{note}")
    return result, proposals, decision


def handle_ticket(ticket: dict, chat_fn=None) -> dict:
    """Route an existing ticket and answer it (used by handle() and by the queue batch)."""
    decision = route(ticket)
    message = f"{ticket['text']}\n\n{ticket_note(ticket)}"
    answer, handover, text = None, None, None
    proposals, final = [], None

    if decision["agent"] == "A":
        result, proposals, final = run_agent_with_coordinator(AgentA, message, ticket, chat_fn)
        answer, handover = result["answer"], result.get("handover")

    if decision["agent"] == "B" or handover == "B":
        handover = "B"
        by = "router" if decision["agent"] == "B" else "agent_A"
        text = handover_text(ticket["main_reason"])
        trace.log("handover", "pipeline", {"ticket_id": ticket["ticket_id"], "to": "B", "by": by, "text": text})
        result, proposals, final = run_agent_with_coordinator(AgentB, message, ticket, chat_fn)
        answer = result["answer"]

    proposal = proposals[-1] if proposals else None
    out = {"ticket": ticket, "route": decision, "answer": answer, "handover": handover,
           "handover_text": text, "proposal": proposal, "proposals": proposals, "decision": final}
    trace.log("pipeline_done", "pipeline", {"ticket_id": ticket["ticket_id"], "route": decision,
                                            "answer": answer, "handover": handover, "proposal": proposal,
                                            "decision": final})
    return out


def handle(message: str, chat_fn=None, use_llm: bool = True) -> dict:
    """Whole flow for one message. chat_fn = fake LLM for tests (used by the agents and the Intake fallback)."""
    ticket = intake.process(message, use_llm=use_llm, chat_fn=chat_fn)
    return handle_ticket(ticket, chat_fn=chat_fn)
