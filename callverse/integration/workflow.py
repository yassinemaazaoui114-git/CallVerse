"""One customer turn through the whole CallVerse chain:

    Intake -> Router -> specialist agent -> Coordinator -> response writer

run() returns the reply AND a list of `steps`, one per stage, each with a status:
  real      the team's implemented component ran
  mock      the LLM agent was replaced by a labelled demo text (no API key)
  not built the component does not exist yet; the workflow did the safe thing instead (said in `detail`)
  skipped   the stage was not needed for this turn (e.g. no action to validate)
The channel (callverse/web) shows these steps to the customer, so nobody mistakes a stand-in for the real thing.

Identity: the channel checks the customer's identity BEFORE calling run(). After the agent answers, run()
withholds the answer if the agent's tools read orders or clients outside what the customer proved.
"""

from callverse import trace
from callverse.integration import components
from callverse.queues import router

TEXTS = {
    "en": {
        "handover": "Your request is passed to our refund team.",
        "mock": "Demo mode: Agent A was not called because no API key is set. CallVerse understood your "
                "message as {reason} with {priority} priority and routed it to Agent A (Status and Tracking).",
        "blocked": "For your security, I can only share information about orders linked to your verified "
                   "email address.",
        "unavailable": "CallVerse is temporarily unavailable. Please try again in a moment.",
        "withheld": "Your request needs a check by our team before anything is changed. A colleague will review it.",
    },
    "fr": {
        "handover": "Votre demande est transmise à notre équipe des remboursements.",
        "mock": "Mode démo : l'agent A n'a pas été appelé car aucune clé API n'est configurée. CallVerse a compris "
                "votre message comme {reason} avec une priorité {priority} et l'a orienté vers l'agent A "
                "(Suivi des commandes).",
        "blocked": "Pour votre sécurité, je ne peux donner des informations que sur les commandes liées à votre "
                   "adresse e-mail vérifiée.",
        "unavailable": "CallVerse est momentanément indisponible. Veuillez réessayer dans un instant.",
        "withheld": "Votre demande doit être vérifiée par notre équipe avant toute modification. "
                    "Un collègue va l'examiner.",
    },
}
REASON_WORDS = {"en": {"order_status": "an order status question", "late_delivery": "a late delivery",
                       "refund_request": "a refund request", "return_item": "a return request",
                       "damaged_item": "a damaged item", "other": "a general question"},
                "fr": {"order_status": "une question de suivi", "late_delivery": "une livraison en retard",
                       "refund_request": "une demande de remboursement", "return_item": "une demande de retour",
                       "damaged_item": "un article endommagé", "other": "une question générale"}}
PRIORITY_WORDS = {"en": {"high": "high", "medium": "medium", "low": "low"},
                  "fr": {"high": "haute", "medium": "moyenne", "low": "basse"}}


def _t(lang, key, **kw):
    return TEXTS.get(lang, TEXTS["en"])[key].format(**kw)


def _step(name, status, **detail):
    return {"name": name, "status": status, "detail": detail}


def out_of_scope(session, tool_calls: list[dict]) -> list[str]:
    """Agent tool calls that read an order or client the customer did not prove."""
    bad = []
    for call in tool_calls:
        args = call.get("args") or {}
        if call["tool"] in ("get_order", "get_tracking", "get_refunds"):
            try:
                if int(args.get("order_id")) not in session.verified_orders:
                    bad.append(f"{call['tool']}({args.get('order_id')})")
            except (TypeError, ValueError):
                pass  # the tool refused the bad argument itself; nothing was read
        elif call["tool"] == "get_user":
            result = call.get("result") or {}
            if "error" not in result and result.get("id") != session.verified_user_id:
                bad.append("get_user")
    return bad


def _ticket_summary(ticket: dict) -> dict:
    """What the customer may see of the ticket: labels only, never the order facts."""
    return {"reasons": [r["reason"] for r in ticket.get("reasons", [])], "main_reason": ticket.get("main_reason"),
            "emotion": ticket.get("emotion", {}).get("label"), "sentiment": ticket.get("sentiment", {}).get("label"),
            "priority": ticket.get("priority_label"), "needs_llm": ticket.get("needs_llm")}


def _run_agent(agent_cls, session, text, ticket, route, chat_fn):
    """Run a specialist agent with the conversation so far and a short ticket note (T04, step 6)."""
    note = f"\n\n(Intake note: order {ticket.get('order_id')}, main reason {route['reason']}.)"
    return agent_cls(chat_fn=chat_fn).run(text + note, history=session.history)


def run(session, text: str, lang: str, mode: str, chat_fn=None) -> dict:
    """Process one (identity-checked) customer message. mode: "real" or "mock" (mock = no LLM agent)."""
    from openai import APIError

    from callverse.agents.agent_a import AgentA
    from callverse.intake import intake
    from callverse.llm import AllModelsFailed

    steps = []
    reply = {"mode": mode, "agent": None, "handover": None, "tools_used": [], "language": lang}

    # 1. Intake (real: local models; the LLM fallback only in real mode, i.e. when a key exists).
    ticket = intake.process(text, use_llm=(mode == "real"), chat_fn=chat_fn)
    summary = _ticket_summary(ticket)
    steps.append(_step("intake", "real", **summary))
    reply["ticket"] = summary

    # 2. Router: Yassine's T04 rules (callverse/queues/router.py, config.yaml -> queues.routes).
    route = router.route(ticket)
    steps.append(_step("router", "real", agent=route["agent"], layer=route.get("layer"),
                       reason=route.get("reason"), priority=route.get("priority_label")))
    reply["route"] = {k: route.get(k) for k in ("agent", "layer", "reason", "priority_label")}

    # 3. Specialist agent.
    result, agent = None, route["agent"]
    if agent == "A":
        if mode == "mock":
            words = REASON_WORDS.get(lang, REASON_WORDS["en"])
            levels = PRIORITY_WORDS.get(lang, PRIORITY_WORDS["en"])
            reply.update(kind="mock", text=_t(lang, "mock", reason=words.get(route["reason"], route["reason"]),
                                              priority=levels.get(route.get("priority_label"), "normal")))
            steps.append(_step("agent", "mock", agent="A", note="no API key: Agent A's LLM was not called"))
        else:
            try:
                result = _run_agent(AgentA, session, text, ticket, route, chat_fn)
            except (AllModelsFailed, APIError) as e:
                # every model down, or e.g. a wrong key (401) that llm.py does not treat as "try the next model"
                trace.log("agent_unavailable", "workflow", {"error": type(e).__name__})
                steps.append(_step("agent", "real", agent="A", error="unavailable"))
                reply.update(kind="channel", text=_t(lang, "unavailable"), error="agent_unavailable", steps=steps)
                return reply
            reply["tools_used"] = [c["tool"] for c in result["tool_calls"]]
            bad = out_of_scope(session, result["tool_calls"])
            steps.append(_step("agent", "real", agent="A", tools=reply["tools_used"], stopped_by=result["stopped_by"]))
            if bad:
                trace.log("identity_block", "workflow", {"tool_calls": bad})
                reply.update(kind="channel", text=_t(lang, "blocked"), steps=steps)
                return reply
            reply.update(kind="agent", agent="A", text=result["answer"])
            if result.get("handover") == "B":
                agent = "B"                                  # Agent A hands money questions to B

    if agent == "B":
        agent_b = components.get("agent_b")
        if agent_b and mode == "real":
            result = _run_agent(agent_b, session, text, ticket, route, chat_fn)
            reply["tools_used"] += [c["tool"] for c in result["tool_calls"]]
            steps.append(_step("agent", "real", agent="B", tools=[c["tool"] for c in result["tool_calls"]]))
            reply.update(kind="agent", agent="B", text=result["answer"])
        else:
            # T04: until Agent B exists, the handover is recorded and the client is told, nothing else.
            steps.append(_step("agent_b", "not built", note="handover to the refund team recorded; nothing decided"))
            reply.update(kind="handover", handover="B", text=_t(lang, "handover"))
            trace.log("handover", "workflow", {"to": "B", "ticket_id": ticket.get("ticket_id"),
                                               "reason": route.get("reason")})

    # 4. Coordinator: the ONLY component allowed to execute an action. Agents today only read, so there is
    #    usually nothing to validate. If an agent ever returns a proposal and no Coordinator exists: fail closed.
    proposal = (result or {}).get("proposal")
    coordinator = components.get("coordinator")
    if proposal is None:
        steps.append(_step("coordinator", "skipped" if coordinator else "not built",
                           note="no action proposed: nothing to validate, nothing executed"))
    elif coordinator is None:
        trace.log("proposal_withheld", "workflow", {"proposal": proposal})
        steps.append(_step("coordinator", "not built", note="proposal NOT executed (no Coordinator)"))
        reply.update(kind="channel", text=_t(lang, "withheld"))
    else:
        decision = coordinator(proposal)
        steps.append(_step("coordinator", "real", outcome=decision.get("outcome")))
        reply["decision"] = decision

    # 5. Response writer (SLM, T05). It needs a Coordinator decision; until both exist the approved text is used as is.
    writer = components.get("slm")
    if writer and reply.get("decision"):
        written = writer(reply["decision"], history=session.history)
        reply["text"] = written["reply"]
        steps.append(_step("response", "real", writer="slm", used_template=written.get("used_template")))
    else:
        steps.append(_step("response", "skipped" if writer else "not built",
                           note="reply text used as approved (no SLM rewrite)"))

    reply["steps"] = steps
    trace.log("workflow", "workflow", {"mode": mode, "route": reply["route"], "kind": reply["kind"],
                                       "steps": [(s["name"], s["status"]) for s in steps]})
    return reply
