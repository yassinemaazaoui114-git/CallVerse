"""The end-to-end flow: client message -> Intake -> Router -> Agent A or B -> Coordinator -> SLM -> reply.

    handle(message) -> {ticket, route, agent_text, handover, handover_text, proposal, proposals,
                        decision, final_reply, reply_source}

- Route A: Agent A runs. If Agent A signals [HANDOVER: B] (the client wants money back),
  Agent B takes the same message. Route B: Agent B runs directly.
- handover_text: the short sentence that announces the handover, per reason (config.yaml,
  queues.handover_texts). Traced and returned for the channel.
- Coordinator (T07): when an agent submits a proposal, the Coordinator reviews it (rules, no LLM).
  On "send_back" the SAME agent gets the reason once more and may correct its proposal; the Coordinator
  allows 2 send-backs per case, the 3rd becomes "escalate". Only an approved proposal is written,
  by the Coordinator.
- No proposal (e.g. a status question): an "info" decision, with facts the Coordinator reads itself;
  a damaged item without a proposal: an "ask_proof" decision (R-DMG-01, a photo is needed first, T09).
- Final reply (T08): the SLM writes it from the decision ONLY (callverse/slm/writer.py), in the client's
  style from Intake. The agent's own text never reaches the user: it is kept as agent_text (trace only),
  because it was written before the decision ("sent for checking").
- reply_source: "slm" (first try passed the rule check), "slm_retry" (second try), "template"
  (both failed, or Ollama is not running: the pipeline still answers, it never crashes).
"""

from callverse import trace
from callverse.agents.agent_a import AgentA
from callverse.agents.agent_b import AgentB
from callverse.config import load_config
from callverse.coordinator.coordinator import (escalate_decision, for_user, info_decision, new_case,
                                               off_topic_decision, proof_decision, review)
from callverse.intake import intake
from callverse.queues.router import route
from callverse.slm.writer import write_reply


def ticket_note(ticket: dict) -> str:
    """Short note from Intake added to the client message, so the agent knows the order and the reason."""
    return f"[Intake note: order id = {ticket['order_id']}, main reason = {ticket['main_reason']}]"


def handover_text(reason: str) -> str:
    """The handover sentence for this reason. Reasons routed to A (order_status, late_delivery, other)
    have no text of their own: Agent A only hands over money requests, so they get the refund text."""
    texts = load_config()["queues"]["handover_texts"]
    return texts.get(reason, texts["refund_request"])


def searched_rules(result: dict) -> set[str]:
    """Rule ids that search_policy returned to the agent during this turn."""
    return {r["id"] for c in result["tool_calls"] if c["tool"] == "search_policy" and isinstance(c["result"], dict)
            for r in c["result"].get("results", [])}


def reply_style(ticket: dict) -> dict:
    """The style the SLM writes in, from the Intake ticket (hand-made test tickets may lack some fields)."""
    style = ticket.get("style") or {}
    return {"formality": style.get("formality", "neutral"), "length": style.get("length", "short"),
            "shouting": bool(style.get("shouting")),
            "emotion": (ticket.get("emotion") or {}).get("label", "neutral"),
            "sentiment": (ticket.get("sentiment") or {}).get("label", "neutral")}


def final_reply(ticket: dict, decision: dict | None, slm_chat_fn=None) -> tuple[dict, str, str]:
    """(decision said to the user, final reply, reply_source). The SLM sees only the decision + style."""
    if decision:
        said = for_user(decision)
    elif ticket.get("main_reason") == "damaged_item":
        said = proof_decision(ticket.get("order_id"))   # T09: no photo yet -> ask for it (R-DMG-01)
    elif ticket.get("main_reason") == "other" and ticket.get("order_id") is None:
        said = off_topic_decision()                     # T10: not about an order -> polite redirect
    else:
        said = info_decision(ticket.get("order_id"))
    said = {**said, "style": reply_style(ticket)}
    # T10: the client's own message is NOT given to the SLM (in T10's dev set it copied an insult back word
    # for word). The tone comes from Intake's style profile; the content only from the decision.
    written = write_reply(said, None, chat_fn=slm_chat_fn)
    source = "template" if written["used_template"] else ("slm" if written["attempts"] == 1 else "slm_retry")
    trace.log("final_reply", "pipeline", {"ticket_id": ticket["ticket_id"], "outcome": said["outcome"],
                                          "reply": written["reply"], "reply_source": source,
                                          "seconds": written["seconds"]})
    return said, written["reply"], source


def run_agent_with_coordinator(agent_cls, message: str, ticket: dict, chat_fn=None) -> tuple[dict, list, dict | None]:
    """Run the agent; review each proposal it makes; on send_back let the same agent correct it.

    Returns (last agent result, all proposals, final decision or None).
    The loop ends: each send-back is counted by the Coordinator and the 3rd one becomes "escalate".
    """
    case = new_case(ticket["ticket_id"])
    result = agent_cls(chat_fn=chat_fn).run(message)
    if ticket.get("order_id") is not None and not result["tool_calls"] and not result.get("proposal"):
        # T10 safety net (the S4 slip): Intake found an order id, but the agent used no tool at all
        # (e.g. it asked the client for the order number). One more run, with the id given plainly.
        note = f"[Note: The order id is {ticket['order_id']}. Check it with your tools before answering.]"
        trace.log("agent_retry", "pipeline", {"ticket_id": ticket["ticket_id"], "agent": result["agent"],
                                              "first_answer": result["answer"], "note": note})
        result = agent_cls(chat_fn=chat_fn).run(f"{message}\n\n{note}")
    proposals, decision = [], None
    while result.get("proposal"):
        proposals.append(result["proposal"])
        case["searched_rules"] = searched_rules(result)   # for the Coordinator's rule_not_searched warning
        decision = review(result["proposal"], case)
        if decision["outcome"] != "send_back":
            break
        note = (f"[Coordinator: proposal {decision['proposal_id']} was sent back: {decision['reason']}. "
                f"Correct it and propose again.]")
        trace.log("send_back_to_agent", "pipeline", {"ticket_id": ticket["ticket_id"],
                                                     "agent": result["agent"], "note": note})
        result = agent_cls(chat_fn=chat_fn).run(f"{message}\n\n{note}")
    return result, proposals, decision


def handle_ticket(ticket: dict, chat_fn=None, slm_chat_fn=None) -> dict:
    """Route an existing ticket and answer it (used by handle() and by the queue batch).
    chat_fn = fake LLM for the agents (tests); slm_chat_fn = fake LLM for the SLM (tests)."""
    decision = route(ticket)
    message = f"{ticket['text']}\n\n{ticket_note(ticket)}"
    answer, handover, text = None, None, None
    proposals, final = [], None
    try:
        answer, handover, text, proposals, final = _run_agents(ticket, decision, message, chat_fn)
    except AssertionError:
        raise   # an assert in a test's fake LLM: a failing test must stay visible
    except Exception as e:
        # T10: never crash in front of the user. Any error in the agents' part (LLM provider refusing
        # a request, ...) is traced and the user gets the "extra check" (escalate) reply.
        trace.log("pipeline_error", "pipeline", {"ticket_id": ticket["ticket_id"], "error": f"{type(e).__name__}: {e}"})
        final = escalate_decision(ticket.get("order_id"), f"error in the agents: {type(e).__name__}")

    said, reply, source = final_reply(ticket, final, slm_chat_fn)
    proposal = proposals[-1] if proposals else None
    out = {"ticket": ticket, "route": decision, "agent_text": answer, "handover": handover,
           "handover_text": text, "proposal": proposal, "proposals": proposals, "decision": said,
           "final_reply": reply, "reply_source": source}
    trace.log("pipeline_done", "pipeline", {"ticket_id": ticket["ticket_id"], "route": decision,
                                            "agent_text": answer, "handover": handover, "proposal": proposal,
                                            "decision": said, "final_reply": reply, "reply_source": source})
    return out


def _run_agents(ticket: dict, decision: dict, message: str, chat_fn) -> tuple:
    """The agents' part of handle_ticket: (agent text, handover, handover text, proposals, final decision)."""
    answer, handover, text = None, None, None
    proposals, final = [], None
    if decision["agent"] == "A":
        result, proposals, final = run_agent_with_coordinator(AgentA, message, ticket, chat_fn)
        answer, handover = result["answer"], result.get("handover")
        if handover == "B" and final is not None:
            # T09: Agent A already has a Coordinator decision (e.g. an approved notification). A handover
            # tag in the same answer would replace it with Agent B's result, so it is ignored (traced).
            trace.log("handover_ignored", "pipeline", {"ticket_id": ticket["ticket_id"],
                                                       "reason": f"agent A already has a decision: {final['outcome']}"})
            handover = None

    if decision["agent"] == "B" or handover == "B":
        handover = "B"
        by = "router" if decision["agent"] == "B" else "agent_A"
        text = handover_text(ticket["main_reason"])
        trace.log("handover", "pipeline", {"ticket_id": ticket["ticket_id"], "to": "B", "by": by, "text": text})
        result, proposals, final = run_agent_with_coordinator(AgentB, message, ticket, chat_fn)
        answer = result["answer"]
    return answer, handover, text, proposals, final


def handle(message: str, chat_fn=None, use_llm: bool = True, slm_chat_fn=None) -> dict:
    """Whole flow for one message. chat_fn = fake LLM for tests (used by the agents and the Intake fallback)."""
    ticket = intake.process(message, use_llm=use_llm, chat_fn=chat_fn)
    return handle_ticket(ticket, chat_fn=chat_fn, slm_chat_fn=slm_chat_fn)
