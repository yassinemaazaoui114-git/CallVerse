"""The Console data for the API: wrappers around callverse.console.reads (read-only), shaped for JSON.

Nothing is computed here that reads.py does not already compute. The only additions are:
- a plain-words description of each step (reads.describe_step) next to its raw data, so the browser shows the
  timeline without knowing the step formats;
- a `kind` per step (reads.kind_of), the Coordinator's decision pulled out per turn (so the page can highlight
  it), and the tool calls / policy searches listed per turn;
- JSON-safe values (datetime -> text).
New step kinds or outcomes are passed through as they are: the browser shows them as plain text.
"""

from datetime import datetime
from typing import Any

from callverse.console import reads
from callverse.tickets import store

# The raw step fields the Streamlit page shows in its "details" expander.
RAW_STEP_KEYS = ("id", "step", "agent", "at", "at_real", "data")


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return value


def filter_values() -> dict:
    """The values of the four Live tickets filters (company, status, priority, agent)."""
    return reads.filter_values()


def live_tickets(company: str | None, status: str | None, priority: str | None, agent: str | None) -> dict:
    """The Live tickets table + whether any ticket exists at all (to tell "no tickets yet" from "no match")."""
    has_tickets = bool(reads.ticket_ids())
    rows = reads.live_tickets(company, status, priority, agent) if has_tickets else []
    return {"tickets": _json_safe(rows), "count": len(rows), "has_tickets": has_tickets,
            "no_tickets_message": reads.NO_TICKETS, "statuses": list(store.STATUSES),
            "server_time": datetime.now().isoformat(timespec="seconds")}


def _step_view(step: dict) -> dict:
    """One step as the browser needs it: who, kind, plain words, and the raw data (unchanged)."""
    icon, title, detail = reads.describe_step(step)
    actor = step.get("actor")
    return {
        "id": step.get("id"),
        "kind": reads.kind_of(step),
        "step": step.get("step"),
        "agent": step.get("agent"),
        "actor": actor,
        "actor_label": reads.AGENTS.get(actor) if actor else None,
        "at": step.get("at"),
        "at_real": step.get("at_real"),
        "title": title,
        "detail": detail,
        "icon_text": icon,   # the Streamlit emoji, kept for reference; the browser draws its own SVG icon from `kind`
        "confirmation": step.get("confirmation"),
        "raw": {k: step[k] for k in RAW_STEP_KEYS if k in step},
    }


def _turn_view(turn: dict) -> dict:
    steps = [_step_view(s) for s in turn["steps"]]
    decisions = [s for s in steps if s["kind"] == "coordinator_decision"]
    return {
        "message": turn["message"],
        "replies": turn["replies"],
        "steps": steps,
        "decision": decisions[-1]["raw"]["data"] if decisions else None,   # the last decision of the turn
        "tool_calls": [s for s in steps if s["kind"] in ("tool_call", "tool_refused")],
        "policy_searches": [s for s in steps if s["kind"] == "tool_call" and s["raw"]["data"].get("tool") == "search_policy"],
        "tokens": turn["tokens"],
        "tokens_total": turn["tokens_total"],
        "seconds": turn["seconds"],
    }


def ticket_detail(ticket_id: str) -> dict | None:
    """One ticket for the detail page, or None if it does not exist."""
    detail = reads.ticket_detail(ticket_id)
    if detail is None:
        return None
    ticket = detail["ticket"]
    return _json_safe({
        "ticket": ticket,
        "user": detail["user"],
        "age": reads.age(ticket.get("created_real")),
        "turns": [_turn_view(t) for t in detail["turns"]],
        "approvals": detail["approvals"],
        "server_time": datetime.now().isoformat(timespec="seconds"),
    })
