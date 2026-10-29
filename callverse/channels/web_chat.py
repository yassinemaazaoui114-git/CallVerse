"""The web chat channel (T17): the ONE door from a company's app (ShopNova) into CallVerse.

    send(user_id, company, text, ticket_id=None, on_step=None) -> {ticket_id, status, reply, ...}

The app never calls Intake, the agents or the Coordinator itself: it calls send(), and send() calls the
same pipeline as before (callverse/pipeline.py, not changed). What send() adds around it:
1. the ticket: which ticket this message goes on (tickets/store.py, the ticket rule), the user message saved.
   about_order (T17 follow-up F1): the order the user clicked "Ask about this order" for. If the message names
   no order number, " (order N)" is added to it (so Intake finds it); a message with an order number is not
   changed. The added number goes through the same identity check as a typed one;
2. quota check (item 9): Agent B runs on Groq (T16). If B has no model left, the user gets "Our assistant is
   busy, please try again later." and the pipeline is NOT called (no half answer from a weaker model).
   The ping's tokens are saved as SYSTEM tokens (store.system_tokens), not in the ticket (Q5);
3. identity check (item 12): Intake reads the message; if it names an order that is not this user's
   order, the user gets "This order is not on your account." and NO agent runs, no order data is shown;
4. the pipeline (handle_ticket on that Intake ticket), with every trace line of this message saved as a
   `step` and turned into a short live text for the page ("Checking your order…"), each text once per message;
5. the reply saved and the ticket updated (status, main reason, priority, lead agent).
It never crashes: any error gives the pipeline's own "extra check" (escalate) reply and an error step.

One message at a time (a lock): the pipeline has one trace and one set of local models; a demo has few users.
"""

import threading
import time

from callverse import pipeline, trace
from callverse import quota
from callverse.coordinator.coordinator import escalate_decision, user_words
from callverse.intake import extract, intake
from callverse.tickets import store
from callverse.tools.shopnova_tools import get_order

BUSY_REPLY = "Our assistant is busy, please try again later."
NOT_YOUR_ORDER_REPLY = "This order is not on your account."
QUOTA_CACHE_SECONDS = 300   # B's quota is checked at most once per 5 minutes (one tiny Groq call)

# Decision outcome -> ticket status (item 11). Final decisions solve the ticket; a question waits for the user.
# escalate: a human colleague must look, so the ticket stays Open.
STATUS_BY_OUTCOME = {"approve": "Solved", "info": "Solved", "layer3_refused": "Solved",
                     "ask_user": "Waiting for user", "ask_proof": "Waiting for user", "escalate": "Open"}

# Trace step -> kind of step saved in the tickets store (docs/ui_design.md section 3; "llm" added for the
# tokens per ticket of the Console, "quota" / "identity" for the two checks of this channel).
STEP_KINDS = {
    "intake_ticket": "intake",
    "route": "route", "handover": "route", "handover_ignored": "route", "agent_retry": "route",
    "proposal_claim_retry": "route",
    "tool_call": "tool_call", "tool_refused": "tool_call", "ask_agent": "tool_call",
    "proposal": "proposal", "proposal_refused": "proposal",
    "coordinator_check": "coordinator", "coordinator_decision": "coordinator", "rule_not_searched": "coordinator",
    "internal_outcome_to_escalate": "coordinator", "send_back_to_agent": "coordinator",
    "layer3_decision": "layer3",
    "db_write": "write", "db_write_refused": "write",
    "slm_call": "slm", "slm_check": "slm", "slm_template": "slm", "final_reply": "slm",
    "llm_call": "llm", "llm_fallback": "llm", "llm_daily_limit": "llm", "llm_skip": "llm", "llm_wait": "llm",
    "pipeline_error": "error",
}
ORDER_TOOLS = ("get_order", "get_tracking", "get_refunds", "get_user")

_lock = threading.Lock()
_quota_cache: dict = {}   # {"at": monotonic seconds, "ok": bool}


def agent_b_ready() -> bool:
    """True if at least one of Agent B's models answers (callverse/quota.py, role agent_b).
    Cached for QUOTA_CACHE_SECONDS, so a chat does not pay one Groq call per message.
    The tokens of the ping are saved as system tokens (not in any ticket)."""
    if _quota_cache and time.monotonic() - _quota_cache["at"] < QUOTA_CACHE_SECONDS:
        return _quota_cache["ok"]
    results = quota.check_models("agent_b", stop_at_first_ok=True)
    for r in results:
        if r.get("tokens"):
            store.add_system_tokens("quota_check", r.get("provider"), r.get("model"), r["tokens"])
    ok = any(r["status"] == "ok" for r in results)
    _quota_cache.update(at=time.monotonic(), ok=ok)
    return ok


def live_text(record: dict) -> str | None:
    """The short text shown to the user while waiting for this trace line, or None (item 10)."""
    step, data = record["step"], record.get("data") or {}
    if step == "intake_start":
        return "Reading your message…"
    if step == "tool_call" and data.get("tool") in ORDER_TOOLS:
        return "Checking your order…"
    if (step == "tool_call" and data.get("tool") == "search_policy") or step in ("coordinator_check",
                                                                                 "layer3_decision"):
        return "Checking the rules…"
    if step == "handover":
        return "Checking with our refund team…"
    if step == "coordinator_decision" and data.get("outcome") != "send_back":
        return "Writing the reply…"   # every path logs a decision just before the SLM writes the reply
    return None


def step_row(record: dict) -> tuple[str, str | None, dict] | None:
    """(kind, agent, data) to save for this trace line, or None if the line is not kept as a step."""
    kind = STEP_KINDS.get(record["step"])
    if kind is None:
        return None
    data = record.get("data") or {}
    if kind == "tool_call" and data.get("tool") == "search_policy":
        kind = "search_policy"
    if record["step"] == "coordinator_check" and data.get("check") == "layer3":
        kind = "layer3"
    agent = data.get("agent") or (data.get("role") if kind == "llm" else None) or record.get("actor")
    return kind, agent, {"trace_step": record["step"], **data}


def _escalate_reply(ticket: dict, reason: str, slm_chat_fn=None) -> str:
    """The pipeline's own "extra check" reply (the SLM or its template); a fixed sentence if even that fails."""
    try:
        _, reply, _ = pipeline.final_reply(ticket, escalate_decision(ticket.get("order_id"), reason), slm_chat_fn)
        return reply
    except Exception:
        return user_words("escalate", None, None, {}, None)[0][0]


def _not_users_order(order_id, user_id: int) -> bool:
    """True when the message names an order that is not on this user's account (or does not exist)."""
    if order_id is None:
        return False
    order = get_order(order_id)
    return "error" in order or order.get("user_id") != int(user_id)


def with_order(text: str, about_order: int | None) -> str:
    """F1: add " (order N)" when the user asks about order N but typed no order number; else the text as it is."""
    if about_order is None or extract.extract(text)["order_id"] is not None:
        return text
    return f"{text} (order {int(about_order)})"


def send(user_id: int, company: str, text: str, ticket_id: str | None = None, on_step=None,
         chat_fn=None, slm_chat_fn=None, about_order: int | None = None) -> dict:
    """Handle one user message. Returns {ticket_id, status, reply, outcome, reply_source, steps, seconds}.

    on_step(text): called with each live text while the pipeline runs (the page shows it), each text once.
    about_order: the order of "Ask about this order" (F1), added to the text if it names no order number.
    chat_fn / slm_chat_fn: fake LLMs for the tests (as in pipeline.handle_ticket); None = the real models.
    """
    with _lock:
        return _send(user_id, company, with_order(text, about_order), ticket_id, on_step, chat_fn, slm_chat_fn)


def _send(user_id, company, text, ticket_id, on_step, chat_fn, slm_chat_fn) -> dict:
    start = time.perf_counter()
    ticket = store.ticket_for_message(company, user_id, ticket_id)
    tid = ticket["id"]
    message_id = store.add_message(tid, "user", text)
    records, shown = [], []

    def listen(record):
        records.append(record)
        said = live_text(record)
        if said and on_step and said not in shown:   # F5: each text once per message
            shown.append(said)
            on_step(said)

    def flush():
        """Stop listening and save the trace lines heard so far as steps (in order). Safe to call twice."""
        trace.remove_listener(listen)
        while records:
            row = step_row(records.pop(0))
            if row:
                store.add_step(tid, message_id, *row)

    def channel_step(kind, data):
        flush()   # the pipeline's steps first, so the steps stay in time order
        store.add_step(tid, message_id, kind, "channel", data)

    def finish(reply, status, outcome, source, **fields):
        flush()
        store.add_message(tid, "assistant", reply)
        updated = store.update_ticket(tid, status=status, **fields)
        return {"ticket_id": tid, "status": updated["status"], "reply": reply, "outcome": outcome,
                "reply_source": source, "steps": len(store.steps(tid)),
                "seconds": round(time.perf_counter() - start, 2)}

    # 2. Quota check: no pipeline call at all when Agent B has no model left.
    try:
        ready = agent_b_ready()
    except Exception as e:   # the check itself failed (e.g. no network): treat as busy, never crash
        ready, error = False, f"{type(e).__name__}: {e}"
    else:
        error = None
    if not ready:
        channel_step("quota", {"agent_b_ready": False, "error": error})
        return finish(BUSY_REPLY, "Open", "busy", "channel")

    trace.add_listener(listen)
    try:
        intake_ticket = None
        try:
            # 3. Identity check: Intake first (it reads the message, no agent yet).
            intake_ticket = {**intake.process(text, chat_fn=chat_fn), "ticket_id": tid}
            if _not_users_order(intake_ticket["order_id"], user_id):
                channel_step("identity", {"order_id": intake_ticket["order_id"], "result": "not this user's order"})
                return finish(NOT_YOUR_ORDER_REPLY, "Waiting for user", "not_your_order", "channel",
                              main_reason=intake_ticket["main_reason"],
                              priority=intake_ticket.get("priority_label"))
            # 4. The pipeline, as it is.
            out = pipeline.handle_ticket(intake_ticket, chat_fn=chat_fn, slm_chat_fn=slm_chat_fn)
        except AssertionError:
            raise   # an assert in a test's fake LLM: a failing test must stay visible
        except Exception as e:
            reason = f"error in the channel: {type(e).__name__}: {e}"
            channel_step("error", {"error": reason})
            reply = _escalate_reply(intake_ticket or {"ticket_id": tid, "order_id": None}, reason, slm_chat_fn)
            return finish(reply, "Open", "escalate", "channel")

        outcome = out["decision"]["outcome"]
        lead = "B" if out["handover"] == "B" else out["route"]["agent"]
        return finish(out["final_reply"], STATUS_BY_OUTCOME.get(outcome, "Open"), outcome, out["reply_source"],
                      main_reason=intake_ticket["main_reason"], priority=intake_ticket.get("priority_label"),
                      lead_agent=lead)
    finally:
        flush()   # also when a test's assert stops the run
