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
  T14a, ShopNova: a return, refund or cancel request without a proposal first goes through no_proposal_decision: when
  the rules say no, the client gets a "decline" with the rule's reason (written by code), not only the order status.
- Final reply (T08): the SLM writes it from the decision ONLY (callverse/slm/writer.py), in the client's
  style from Intake. The agent's own text never reaches the user: it is kept as agent_text (trace only),
  because it was written before the decision ("sent for checking").
- reply_source: "slm" (first try passed the rule check), "slm_retry" (second try), "template"
  (both failed, or Ollama is not running: the pipeline still answers, it never crashes).
- Safety net (T13c): if the agent's text CLAIMS a proposal ("I propose ...", "sent for checking") but it called
  no proposal tool, the same agent runs once more with a short note. Nothing is written by the net itself.
  Used only when config.yaml pipeline.proposal_claim_retry is true (OFF by default).
- T21: one pipeline for every company. The company is on the ticket (from the channel); the same steps then use that
  company's agents' prompts and tools, its gate (config.yaml companies.<company>.coordinator) and its words. A route can
  be "escalate": no agent runs, a human colleague takes the ticket.
"""

import re

from callverse import companies, trace
from callverse.agents.agent_a import AgentA
from callverse.agents.agent_b import AgentB
from callverse.config import load_config
from callverse.coordinator.coordinator import (for_user, info_decision, new_case, no_proposal_decision,
                                               off_topic_decision, proof_decision, review)
from callverse.intake import intake
from callverse.queues.router import route
from callverse.slm.writer import write_reply

# T13c safety net (L3): an answer that CLAIMS a proposal although no proposal tool was called (seen with the
# local test model: "I can propose a full refund ... sent for checking", but no propose_refund call). Short list.
PROPOSAL_CLAIM_RE = re.compile(r"\bpropos(?:e|ed|es|ing|al)\b|sent for checking|\bsubmitted\b[^.]{0,60}\bfor review",
                               re.IGNORECASE)
PROPOSAL_TOOLS = ("propose_refund", "propose_subscription", "propose_cancellation", "propose_compensation",
                  "propose_hotel_cancellation")
PROPOSAL_CLAIM_NOTE = ("[Note: A first answer to this message said that something is proposed, but no proposal tool "
                       "was called. If a rule allows it, call the proposal tool now. Otherwise answer without saying "
                       "that anything is proposed.]")


def claims_proposal(answer: str) -> bool:
    """True when the agent's text says it proposes / proposed something (the phrases above)."""
    return bool(PROPOSAL_CLAIM_RE.search(answer or ""))


def ticket_note(ticket: dict) -> str:
    """Short note from Intake added to the client message, so the agent knows the order and the reason."""
    if companies.of(ticket) == "atlas":
        return (f"[Intake note: booking id = {ticket['order_id']}, booking type = {ticket.get('booking_type')}, "
                f"main reason = {ticket['main_reason']}]")
    return f"[Intake note: order id = {ticket['order_id']}, main reason = {ticket['main_reason']}]"


def gate(ticket: dict):
    """The Coordinator of the ticket's company."""
    return companies.module(companies.of(ticket), "coordinator")


def handover_text(reason: str, company: str = companies.DEFAULT) -> str:
    """The handover sentence for this reason. Reasons routed to A (order_status, late_delivery, other)
    have no text of their own: Agent A only hands over money requests, so they get the refund text."""
    texts = companies.get(company)["handover_texts"]
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
    if companies.of(ticket) != companies.DEFAULT:
        said = gate(ticket).said_to_user(ticket, decision)
    elif decision:
        said = for_user(decision)
    elif ticket.get("main_reason") == "damaged_item":
        said = proof_decision(ticket.get("order_id"))   # T09: no photo yet -> ask for it (R-DMG-01)
    elif ticket.get("main_reason") == "other" and ticket.get("order_id") is None:
        said = off_topic_decision()                     # T10: not about an order -> polite redirect
    else:
        # T14a: the rules may say "no" (decline, with the reason); otherwise the status, as before.
        said = no_proposal_decision(ticket.get("main_reason"), ticket.get("order_id")) or info_decision(ticket.get("order_id"))
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
    company = companies.of(ticket)
    # ShopNova's `review` is looked up here at call time: the demo screen wraps pipeline.review for its story S2.
    check = review if company == companies.DEFAULT else gate(ticket).review

    def new_agent():
        return agent_cls(chat_fn=chat_fn, company=company)

    case = new_case(ticket["ticket_id"])
    # The gate checks that a proposal is about the ticket's own booking / order, and confirms from the client's words.
    case.update(order_id=ticket.get("order_id"), main_reason=ticket.get("main_reason"), user_message=ticket.get("text"))
    if company != companies.DEFAULT:
        case.update(booking_type=ticket.get("booking_type"))
    result = new_agent().run(message)
    if ticket.get("order_id") is not None and not result["tool_calls"] and not result.get("proposal"):
        # T10 safety net (the S4 slip): Intake found an order id, but the agent used no tool at all
        # (e.g. it asked the client for the order number). One more run, with the id given plainly.
        word = "order" if company == companies.DEFAULT else "booking"
        note = f"[Note: The {word} id is {ticket['order_id']}. Check it with your tools before answering.]"
        trace.log("agent_retry", "pipeline", {"ticket_id": ticket["ticket_id"], "agent": result["agent"],
                                              "first_answer": result["answer"], "note": note})
        result = new_agent().run(f"{message}\n\n{note}")
    called = {c["tool"] for c in result["tool_calls"]}
    net_on = load_config().get("pipeline", {}).get("proposal_claim_retry", False)   # config switch, OFF by default
    if net_on and claims_proposal(result["answer"]) and not called & set(PROPOSAL_TOOLS) and not result.get("proposal"):
        # T13c safety net: the answer claims a proposal, but no proposal tool was called, so nothing would
        # happen. One more run (at most one), with a short note. The net writes nothing: only a real proposal
        # tool call reaches the Coordinator, which checks it as before.
        trace.log("proposal_claim_retry", "pipeline", {"ticket_id": ticket["ticket_id"], "agent": result["agent"],
                                                       "first_answer": result["answer"], "note": PROPOSAL_CLAIM_NOTE})
        result = new_agent().run(f"{message}\n\n{PROPOSAL_CLAIM_NOTE}")
    proposals, decision = [], None
    while result.get("proposal"):
        proposals.append(result["proposal"])
        case["searched_rules"] = searched_rules(result)   # for the Coordinator's rule_not_searched warning
        decision = check(result["proposal"], case)
        if decision["outcome"] != "send_back":
            break
        note = (f"[Coordinator: proposal {decision['proposal_id']} was sent back: {decision['reason']}. "
                f"Correct it and propose again.]")
        trace.log("send_back_to_agent", "pipeline", {"ticket_id": ticket["ticket_id"],
                                                     "agent": result["agent"], "note": note})
        result = new_agent().run(f"{message}\n\n{note}")
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
        final = gate(ticket).escalate_decision(ticket.get("order_id"), f"error in the agents: {type(e).__name__}")

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
    if decision["agent"] == "escalate":   # T21: no agent for this reason yet: a human colleague takes the ticket
        reason = f"route: {decision['reason']} goes to a colleague"
        return answer, handover, text, proposals, gate(ticket).escalate_decision(ticket.get("order_id"), reason)
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
        text = handover_text(ticket["main_reason"], companies.of(ticket))
        trace.log("handover", "pipeline", {"ticket_id": ticket["ticket_id"], "to": "B", "by": by, "text": text})
        result, proposals, final = run_agent_with_coordinator(AgentB, message, ticket, chat_fn)
        answer = result["answer"]
    return answer, handover, text, proposals, final


def handle(message: str, chat_fn=None, use_llm: bool = True, slm_chat_fn=None,
           company: str = companies.DEFAULT) -> dict:
    """Whole flow for one message. chat_fn = fake LLM for tests (used by the agents and the Intake fallback)."""
    ticket = intake.process(message, use_llm=use_llm, chat_fn=chat_fn, **companies.extra_args(company))
    return handle_ticket(ticket, chat_fn=chat_fn, slm_chat_fn=slm_chat_fn)
