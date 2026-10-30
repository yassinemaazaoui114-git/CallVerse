"""The CallVerse Console's reads (T19): ALL the Console's SQL is here, on READ-ONLY connections.

The Console (apps/console, port 8502) is the center's own screen: every ticket of every company, how the agents
worked on each one, and the KPIs. It never writes: both databases are opened with SQLite's read-only mode
(`file:...?mode=ro`), so even a bug in a page cannot change a ticket or a company's data (a test checks that an
INSERT fails). A missing file is never created: the page just shows "No tickets yet".

- callverse.db (the center's tickets, callverse/tickets/store.py): tickets, messages, steps, approvals,
  system_tokens. Read whole (a demo has tens of tickets) and counted in Python: easy to read and to check by hand.
- the company's data (shopnova.db, atlas.db): the user's name, the money paid (refunds, Atlas's compensations too),
  and ShopNova's review scores.

Times: the Console uses the COMPUTER time columns (created_real, at_real: T19), never the simulation clock (it
does not move, so every ticket would have the same age). Rows made before T19 have no computer time: they are
shown with "—" and only counted in the period "All".

Who did a step (the Agents page and the tokens per agent): steps are read in order, per user message.
Intake reads first (its LLM fallback uses the "agents" models, before the intake step); then an "agents" model
call is Agent A's, an "agent_b" call is Agent B's (also its "ask Agent A" question), an "slm" call is the reply
writer's; a proposal belongs to the agent that worked just before it; checks, decisions, Layer 3 and the writes
the Coordinator approved belong to the Coordinator.

One function per page block: companies, live_tickets, ticket_detail (+ describe_step), agents, dashboard,
groq_today.
"""

import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from callverse.config import load_config
from callverse.data import db as shopnova_db
from callverse.data.atlas import db as atlas_db
from callverse.tickets import store

NO_TICKETS = "No tickets yet — chat in the ShopNova app to see them here."
NO_TIME = "—"   # shown for a value an old row does not have (made before T19)

# The period filter of the Agents and Dashboard pages: label -> days back (None = all tickets).
PERIODS = {"All": None, "Last 7 days": 7, "Last 30 days": 30}

# The Agents page cards, in the order of the pipeline.
AGENTS = {"intake": "Intake", "A": "Agent A", "B": "Agent B", "coordinator": "Coordinator", "writer": "Reply writer"}

# The company's own data file, per company (the user's name, refunds, reviews).
COMPANY_DBS = {"shopnova": shopnova_db.db_path, "atlas": atlas_db.db_path}

# Where each company keeps the money it paid: {kind: (table, the column with the case's number)}.
MONEY_TABLES = {"shopnova": {"refunds": ("refunds", "order_id")},
                "atlas": {"refunds": ("refunds", "booking_id"), "compensations": ("compensations", "booking_id")}}

# Steps counted as errors on the Agents page: a refused tool or proposal, a model that failed (the next one of
# its list was used), a write the platform refused, an error in the pipeline.
ERROR_STEPS = ("tool_refused", "proposal_refused", "llm_fallback", "llm_daily_limit", "db_write_refused",
               "pipeline_error")
SOLVED = ("Solved", "Closed")


# ---------- read-only connections ----------

def connect_ro(path: str | Path) -> sqlite3.Connection | None:
    """Open a database file READ-ONLY (any write fails), or None if the file does not exist (never created)."""
    path = Path(path)
    if not path.exists():
        return None
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _read(path: str | Path, sql: str, params: tuple = ()) -> list[dict]:
    """The rows of one SELECT as dicts; [] if the file or the table does not exist yet."""
    con = connect_ro(path)
    if con is None:
        return []
    with closing(con):
        try:
            return [dict(r) for r in con.execute(sql, params)]
        except sqlite3.OperationalError:   # e.g. "no such table" in a very old or empty file
            return []


def _tickets() -> list[dict]:
    rows = _read(store.db_path(), "SELECT * FROM tickets")
    return sorted(rows, key=lambda t: _number(t["id"]), reverse=True)   # newest first (ids follow each other)


def _messages() -> list[dict]:
    return _read(store.db_path(), "SELECT * FROM messages ORDER BY id")


def _steps() -> list[dict]:
    rows = _read(store.db_path(), "SELECT * FROM steps ORDER BY id")
    for r in rows:
        r["data"] = json.loads(r["data"])
    return rows


def _approvals() -> list[dict]:
    return _read(store.db_path(), "SELECT * FROM approvals ORDER BY id")


def _number(ticket_id: str) -> int:
    """T-0012 -> 12 (to sort tickets; text sorting would put T-10000 before T-9999)."""
    try:
        return int(str(ticket_id).split("-")[-1])
    except ValueError:
        return 0


def _console_cfg() -> dict:
    return load_config().get("console", {})


# ---------- small helpers ----------

def _now(now: datetime | None) -> datetime:
    return now or datetime.now()


def since(days: int | None, now: datetime | None = None) -> str | None:
    """The computer time `days` days ago as ISO text (None = no limit)."""
    if days is None:
        return None
    return (_now(now) - timedelta(days=days)).isoformat(timespec="seconds")


def in_period(ticket: dict, days: int | None, now: datetime | None = None) -> bool:
    """True if the ticket was created in the last `days` days (computer time). Old rows: only in "All"."""
    if days is None:
        return True
    return bool(ticket.get("created_real")) and ticket["created_real"] >= since(days, now)


def age(real_time: str | None, now: datetime | None = None) -> str:
    """How long ago, in short words: "40 s", "12 min", "3 h", "2 d"; "—" if the row has no computer time."""
    if not real_time:
        return NO_TIME
    seconds = max(0, int((_now(now) - datetime.fromisoformat(real_time)).total_seconds()))
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min"
    if seconds < 86400:
        return f"{seconds // 3600} h"
    return f"{seconds // 86400} d"


def kind_of(step: dict) -> str:
    """The exact trace step (llm_call, coordinator_check, ...); the channel's own steps keep their kind."""
    return step["data"].get("trace_step") or step["step"]


def tokens_of(step: dict) -> int:
    """The tokens of one model call (0 for any other step)."""
    if kind_of(step) != "llm_call":
        return 0
    return int((step["data"].get("tokens") or {}).get("total") or 0)


def model_of(step: dict) -> str:
    data = step["data"]
    return f"{data.get('provider') or '?'}/{data.get('model') or '?'}"


def tokens_by_model(steps: list[dict]) -> dict[str, int]:
    """{"groq/openai/gpt-oss-120b": 5012, ...} for the model calls among these steps."""
    out: dict[str, int] = defaultdict(int)
    for s in steps:
        if kind_of(s) == "llm_call":
            out[model_of(s)] += tokens_of(s)
    return dict(out)


def user_names(company: str, user_ids) -> dict[int, str]:
    """{user id: name} from the company's own data (read-only). Unknown company or file: no names."""
    path_fn = COMPANY_DBS.get(company)
    ids = sorted({int(u) for u in user_ids})
    if path_fn is None or not ids:
        return {}
    marks = ", ".join("?" for _ in ids)
    rows = _read(path_fn(), f"SELECT id, name FROM users WHERE id IN ({marks})", tuple(ids))
    return {r["id"]: r["name"] for r in rows}


def _user_label(ticket: dict, names: dict) -> str:
    name = names.get((ticket["company"], ticket["user_id"]))
    return f"{name} ({ticket['user_id']})" if name else f"user {ticket['user_id']}"


def _all_names(tickets: list[dict]) -> dict[tuple, str]:
    """{(company, user id): name} for these tickets."""
    by_company = defaultdict(set)
    for t in tickets:
        by_company[t["company"]].add(t["user_id"])
    return {(c, uid): name for c, ids in by_company.items() for uid, name in user_names(c, ids).items()}


# ---------- who did a step ----------

def _actor(step: dict, intake_done: bool) -> str | None:
    """intake / A / B / coordinator / writer for one step, or None (route, channel checks, ...)."""
    kind, data, who = step["step"], step["data"], step.get("agent")
    if kind == "intake":
        return "intake"
    if kind == "route" or kind_of(step) == "ask_agent":
        return None   # the router is a rule, not an agent; "ask_agent" names the agent ASKED (B's tool call says who asked)
    if kind == "llm":
        role = data.get("role")
        if role == "agents":
            return "A" if intake_done else "intake"   # before the intake step: Intake's LLM fallback
        return {"agent_b": "B", "slm": "writer"}.get(role)
    if kind in ("coordinator", "layer3", "write"):
        return "coordinator"
    if kind == "slm":
        return "writer"
    if who in ("A", "B"):
        return who
    if who == "INTAKE":
        return "intake"   # Intake's own reads (order facts)
    return None


def actors(steps: list[dict]) -> list[str | None]:
    """Who did each step (same order as `steps`, ONE ticket's steps in id order). See the top of this file."""
    out, intake_done, current, message = [], False, None, object()
    for s in steps:
        if s["message_id"] != message:   # a new user message: Intake reads first again
            intake_done, current, message = False, None, s["message_id"]
        who = _actor(s, intake_done)
        if who is None and kind_of(s) in ("proposal", "proposal_refused"):
            who = current   # the proposal tool's trace line names no agent: it is the agent working now
        if s["step"] == "intake":
            intake_done = True
        if who in ("A", "B"):
            current = who
        out.append(who)
    return out


def _by_ticket(steps: list[dict]) -> dict[str, list[dict]]:
    out = defaultdict(list)
    for s in steps:
        out[s["ticket_id"]].append(s)
    return out


# ---------- page: Live tickets ----------

def companies() -> list[str]:
    """The company filter: the companies in config (console.companies) + those found in callverse.db."""
    found = {r["company"] for r in _read(store.db_path(), "SELECT DISTINCT company FROM tickets")}
    return sorted(set(_console_cfg().get("companies", [])) | found)


def live_tickets(company: str | None = None, status: str | None = None, priority: str | None = None,
                 agent: str | None = None, now: datetime | None = None) -> list[dict]:
    """The Live tickets table, newest first. A filter set to None shows everything."""
    tickets = [t for t in _tickets()
               if (company is None or t["company"] == company) and (status is None or t["status"] == status)
               and (priority is None or t["priority"] == priority) and (agent is None or t["lead_agent"] == agent)]
    names = _all_names(tickets)
    return [{"id": t["id"], "company": t["company"], "user": _user_label(t, names),
             "reason": t["main_reason"] or NO_TIME, "priority": t["priority"] or NO_TIME, "status": t["status"],
             "lead agent": t["lead_agent"] or NO_TIME, "age": age(t.get("created_real"), now)} for t in tickets]


def filter_values() -> dict[str, list[str]]:
    """The values offered by the Live tickets filters (from the tickets that exist, plus the companies)."""
    tickets = _tickets()
    pick = lambda key: sorted({t[key] for t in tickets if t[key]})   # noqa: E731
    return {"company": companies(), "status": [s for s in store.STATUSES if s in pick("status")],
            "priority": pick("priority"), "agent": pick("lead_agent")}


# ---------- page: Ticket detail ----------

def ticket_ids() -> list[str]:
    return [t["id"] for t in _tickets()]


def ticket_detail(ticket_id: str) -> dict | None:
    """One ticket: {ticket, user, turns, approvals}. A turn = one user message + the replies to it + the steps
    CallVerse took on it, its tokens by model and the reply seconds."""
    ticket = next((t for t in _tickets() if t["id"] == ticket_id), None)
    if ticket is None:
        return None
    messages = _read(store.db_path(), "SELECT * FROM messages WHERE ticket_id = ? ORDER BY id", (ticket_id,))
    steps = _read(store.db_path(), "SELECT * FROM steps WHERE ticket_id = ? ORDER BY id", (ticket_id,))
    for s in steps:
        s["data"] = json.loads(s["data"])
    for s, who in zip(steps, actors(steps)):
        s["actor"] = who
    turns = []
    for m in messages:
        if m["sender"] == "user":
            turns.append({"message": m, "replies": [], "steps": [s for s in steps if s["message_id"] == m["id"]]})
        elif turns:
            turns[-1]["replies"].append(m)
        else:   # (never seen: a reply before any user message) shown without a user message
            turns.append({"message": None, "replies": [m], "steps": []})
    for turn in turns:
        turn["tokens"] = tokens_by_model(turn["steps"])
        turn["tokens_total"] = sum(turn["tokens"].values())
        turn["seconds"] = [r.get("seconds") for r in turn["replies"] if r["sender"] == "assistant"]
    approvals = [a for a in _approvals() if a["ticket_id"] == ticket_id]
    return {"ticket": ticket, "user": _user_label(ticket, _all_names([ticket])), "turns": turns,
            "approvals": approvals}


def _short(value, size: int = 140) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= size else text[:size - 1] + "…"


def _args(args) -> str:
    return ", ".join(f"{k}={v}" for k, v in (args or {}).items())


AGENT_LABEL = {"A": "Agent A", "B": "Agent B", "INTAKE": "Intake"}


def _label(value) -> str:
    """Intake's emotion / sentiment: {"label": "sadness", "score": 0.71} -> "sadness (0.71)"; text stays text."""
    if isinstance(value, dict):
        score = value.get("score")
        return f"{value.get('label')}" + (f" ({score:.2f})" if isinstance(score, (int, float)) else "")
    return str(value)


def describe_step(step: dict) -> tuple[str, str, str]:
    """(icon, title, detail) of one step, in plain words, for the Ticket detail timeline."""
    kind, d = kind_of(step), step["data"]
    who = AGENT_LABEL.get(d.get("agent"), d.get("agent") or "")
    if kind == "intake_ticket":
        return ("📥", "Intake read the message",
                f"reason **{d.get('main_reason')}** · emotion {_label(d.get('emotion'))} · "
                f"sentiment {_label(d.get('sentiment'))} · "
                f"priority **{d.get('priority_label')}** · order {d.get('order_id')}"
                + (" · LLM fallback used" if d.get("needs_llm") else "")
                + (f" · {d['seconds']} s" if d.get("seconds") is not None else ""))
    if kind == "route":
        return "🔀", f"Routed to Agent {d.get('agent')}", f"reason {d.get('reason')} · layer {d.get('layer')} (rules, no LLM)"
    if kind == "handover":
        return "🤝", f"Hand-over to Agent {d.get('to')}", f"asked by {d.get('by')}: {_short(d.get('text') or '')}"
    if kind == "handover_ignored":
        return "↪️", "Hand-over ignored", _short(d)
    if kind in ("agent_retry", "proposal_claim_retry"):
        return "🔁", f"{who} asked again (safety net)", _short(d.get("note") or "")
    if kind == "tool_call" and d.get("tool") == "search_policy":
        rules = [r.get("id") for r in (d.get("result") or {}).get("results", [])]
        return "📚", f"{who} searched the rules", f"“{(d.get('args') or {}).get('query')}” → {', '.join(rules) or 'none'}"
    if kind == "tool_call":
        result = d.get("result")
        said = f"error: {result['error']}" if isinstance(result, dict) and "error" in result else _short(result, 120)
        return "🔧", f"{who} called {d.get('tool')}({_args(d.get('args'))})", said
    if kind == "tool_refused":
        return "⛔", f"{who} was refused {d.get('tool')}", f"not in its allow-list ({', '.join(d.get('allowed') or [])})"
    if kind == "ask_agent":
        return "💬", f"Asked Agent {d.get('to')}", f"{_short(d.get('question') or '')} → {_short(d.get('answer') or '', 100)}"
    if kind == "proposal":
        action = d.get("action", "refund")
        what = (f"{d.get('amount')} TND on order {d.get('order_id')}" if action == "refund"
                else f"{d.get('event')} on order {d.get('order_id')}")
        if d.get("booking_id") is not None:   # T21: an Atlas proposal has no amount: the Coordinator computes it
            what = f"{d.get('booking_type')} booking {d.get('booking_id')}"
        return ("📝", f"Proposal: {action}",
                f"{what} · rule {d.get('rule_id')} · client confirmed: {d.get('user_confirmed')} · "
                f"facts {_short(d.get('facts_used'), 100)}")
    if kind == "proposal_refused":
        return "⛔", "Proposal refused by the tool", "; ".join(d.get("problems") or [])
    if kind == "coordinator_check":
        icon = {"pass": "✅", "fail": "❌", "pending": "⏳"}.get(d.get("result"), "•")
        rule = f" ({d['rule_id']})" if d.get("rule_id") else ""
        return icon, f"Coordinator check: {d.get('check')}{rule}", _short(d.get("detail") or "", 160)
    if kind == "rule_not_searched":
        return "⚠️", f"Rule {d.get('rule_id')} was cited but not searched", f"searched: {d.get('searched')}"
    if kind == "coordinator_decision":
        return ("⚖️", f"Coordinator decision: **{d.get('outcome')}**",
                f"why: {d.get('reason')}" + (f" · proposal {d['proposal_id']}" if d.get("proposal_id") else ""))
    if kind == "internal_outcome_to_escalate":
        return "⚖️", "Coordinator: passed to a human", f"from {d.get('from')}"
    if kind == "send_back_to_agent":
        return "↩️", f"Sent back to Agent {d.get('agent')}", _short(d.get("note") or "", 160)
    if kind == "layer3_decision":
        if d.get("by") in ("ShopNova admin", "Atlas admin"):
            return "🏦", f"Layer 3: the {d['by']} decided **{d.get('outcome')}**", f"by {d.get('admin')}"
        result = d.get("result") or {}
        return "🏦", f"Layer 3 (fixed rule): {result.get('decision')}", _short(d.get("args") or {}, 100)
    if kind == "approval":
        return "🏦", "Layer 3: waiting for finance", f"approval {d.get('approval_id')} · {d.get('amount')} TND on order {d.get('order_id')}"
    if kind == "approval_pending":
        return "🏦", "Already waiting for finance", f"order {d.get('order_id')} (approval {d.get('approval_id')}): no agent ran"
    if kind == "quota":
        return "⏳", "Quota check: Agent B has no model left", f"the user got the 'busy' reply · {d.get('error') or ''}"
    if kind == "identity":
        return "🪪", "Identity check: refused", f"order {d.get('order_id')}: {d.get('result')} (no agent ran, no data shown)"
    if kind == "error":
        return "💥", "Error in the channel", _short(d.get("error") or "", 160)
    if kind == "pipeline_error":
        return "💥", "Error in the pipeline", _short(d, 160)
    if kind == "db_write":
        return "💾", f"Written: {d.get('function')}", f"{_args(d.get('args'))} → {_short(d.get('result'), 100)}"
    if kind == "db_write_refused":
        return "⛔", f"Write refused: {d.get('function')}", d.get("reason") or ""
    if kind == "slm_call":
        error = f" · error: {d['error']}" if d.get("error") else ""
        return "✍️", f"Reply writer, try {d.get('attempt')}", f"{d.get('seconds')} s{error}"
    if kind == "slm_check":
        if d.get("passed"):
            return "✅", f"Reply check, try {d.get('attempt')}: passed", ""
        return "❌", f"Reply check, try {d.get('attempt')}: failed", "; ".join(d.get("problems") or [])
    if kind == "slm_template":
        return "📄", "Reply writer: the fixed template was used", "; ".join(d.get("problems") or [])
    if kind == "final_reply":
        source = {"slm": "first try", "slm_retry": "retry", "template": "template"}.get(d.get("reply_source"),
                                                                                      d.get("reply_source"))
        return "✍️", f"Reply written ({source})", f"outcome {d.get('outcome')} · {d.get('seconds')} s"
    if kind == "llm_call":
        return ("🧠", f"Model call ({d.get('role')}): {model_of(step)}",
                f"{tokens_of(step):,} tokens · {d.get('seconds')} s")
    if kind == "llm_fallback":
        return "⚠️", f"Model failed ({d.get('role')}): {model_of(step)}", f"the next model of the list was used · {_short(d.get('error') or '', 100)}"
    if kind == "llm_daily_limit":
        return "🛑", f"Daily limit reached: {model_of(step)}", ""
    if kind in ("llm_wait", "llm_skip"):
        return "⏱️", f"{kind.replace('_', ' ')} ({d.get('role')}): {model_of(step)}", _short(d, 100)
    return "•", kind, _short(d)


# ---------- page: Agents ----------

def _tickets_in(days: int | None, now: datetime | None) -> list[dict]:
    return [t for t in _tickets() if in_period(t, days, now)]


def agents(days: int | None = None, now: datetime | None = None) -> list[dict]:
    """One card per agent (AGENTS) for the tickets created in the period: tickets and messages handled,
    proposals, Coordinator outcomes (approved / sent back / escalated / to finance), errors, average seconds,
    tokens and the models used."""
    keep = {t["id"] for t in _tickets_in(days, now)}
    cards = {key: {"agent": key, "name": name, "tickets": set(), "messages": set(), "proposals": 0,
                   "approved": 0, "sent_back": 0, "escalated": 0, "to_finance": 0, "errors": 0,
                   "seconds": [], "tokens": 0, "models": set()} for key, name in AGENTS.items()}
    llm_seconds = defaultdict(float)   # (agent, ticket, message) -> model seconds (Agents A and B)
    for ticket_id, steps in _by_ticket(_steps()).items():
        if ticket_id not in keep:
            continue
        current = None
        for s, who in zip(steps, actors(steps)):
            kind, d = kind_of(s), s["data"]
            if who in ("A", "B"):
                current = who
            if kind == "coordinator_decision":   # counted for the Coordinator AND the agent that proposed
                outcome = {"approve": "approved", "send_back": "sent_back", "escalate": "escalated",
                           "layer3_pending": "to_finance"}.get(d.get("outcome"))
                targets = ["coordinator"] + ([current] if d.get("proposal_id") and current else [])
                for target in targets if outcome else []:
                    cards[target][outcome] += 1
                if d.get("proposal_id"):
                    cards["coordinator"]["proposals"] += 1   # proposals reviewed
            if who is None:
                continue
            card = cards[who]
            card["tickets"].add(ticket_id)
            card["messages"].add((ticket_id, s["message_id"]))
            if kind == "proposal" and who in ("A", "B"):
                card["proposals"] += 1
            if kind in ERROR_STEPS or (kind == "slm_call" and d.get("error")):
                card["errors"] += 1
            if kind == "llm_call":
                card["tokens"] += tokens_of(s)
                card["models"].add(model_of(s))
                if who in ("A", "B"):
                    llm_seconds[(who, ticket_id, s["message_id"])] += float(d.get("seconds") or 0)
            if (who == "intake" and kind == "intake_ticket") or (who == "writer" and kind == "final_reply"):
                if d.get("seconds") is not None:
                    card["seconds"].append(float(d["seconds"]))
    for (who, _, _), seconds in llm_seconds.items():
        cards[who]["seconds"].append(seconds)
    intake_cfg = load_config().get("intake", {})
    local = [intake_cfg.get(k, "").split("/")[-1] for k in ("embedding_model", "emotion_model", "sentiment_model")]
    out = []
    for key, c in cards.items():
        models = sorted(c["models"])
        if key == "intake":
            models = [f"local: {m}" for m in local if m] + models
        if key == "coordinator":
            models = ["rules (no LLM)"]
        seconds = c.pop("seconds")
        out.append({**c, "tickets": len(c["tickets"]), "messages": len(c["messages"]), "models": models,
                    "avg_seconds": round(sum(seconds) / len(seconds), 2) if seconds else None})
    return out


# ---------- page: Dashboard ----------

def _pct(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def dashboard(days: int | None = None, now: datetime | None = None) -> dict:
    """All the Dashboard's numbers for the tickets created in the period (computer time). See the page for
    what each one means; the tests check the math on known tickets."""
    tickets = _tickets_in(days, now)
    ids = {t["id"] for t in tickets}
    steps = [s for s in _steps() if s["ticket_id"] in ids]
    approvals = [a for a in _approvals() if a["ticket_id"] in ids]
    replies = [m for m in _messages() if m["ticket_id"] in ids and m["sender"] == "assistant"]
    late_s = float(_console_cfg().get("late_reply_s", 30))

    escalated = {t["id"] for t in tickets if t["status"] == "Escalated"} | {
        s["ticket_id"] for s in steps if kind_of(s) == "coordinator_decision" and s["data"].get("outcome") == "escalate"}
    finance = {a["ticket_id"] for a in approvals}
    solved_ai = {t["id"] for t in tickets if t["status"] in SOLVED} - escalated - finance

    per_day = Counter(((t.get("created_real") or "")[:10] or NO_TIME, t["company"]) for t in tickets)
    timed = [float(m["seconds"]) for m in replies if m.get("seconds") is not None]
    late = [s for s in timed if s > late_s]

    tokens = defaultdict(int)
    for s in steps:
        tokens[s["ticket_id"]] += tokens_of(s)
    per_ticket = [tokens[t["id"]] for t in tickets]
    cutoff = since(days, now)
    system = [r for r in _read(store.db_path(), "SELECT * FROM system_tokens")
              if cutoff is None or (r.get("at_real") or "") >= cutoff]

    return {
        "tickets": len(tickets),
        "per_day": [{"day": day, "company": company, "tickets": n} for (day, company), n in sorted(per_day.items())],
        "per_company": [{"company": c, "tickets": n} for c, n in sorted(Counter(t["company"] for t in tickets).items())],
        "by_status": [{"status": s, "tickets": n} for s, n in Counter(t["status"] for t in tickets).items()],
        "solved_ai": len(solved_ai), "solved_ai_pct": _pct(len(solved_ai), len(tickets)),
        "escalated": len(escalated), "escalated_pct": _pct(len(escalated), len(tickets)),
        "finance": len(finance), "finance_pct": _pct(len(finance), len(tickets)),
        "replies_timed": len(timed), "replies_untimed": len(replies) - len(timed),
        "avg_reply_s": round(sum(timed) / len(timed), 2) if timed else None,
        "late_s": late_s, "late": len(late), "late_pct": _pct(len(late), len(timed)),
        **_refunds(tickets, steps, approvals),
        **satisfaction(),
        "tokens_avg": round(sum(per_ticket) / len(per_ticket)) if per_ticket else 0,
        "tokens_max": max(per_ticket, default=0), "tokens_total": sum(per_ticket),
        "tokens_per_ticket": [{"ticket": t["id"], "tokens": tokens[t["id"]]} for t in tickets],
        "system_tokens": sum(int(r["tokens"]) for r in system),
        "groq_today": groq_today(now),
    }


def _paid(company: str, table: str, column: str, pairs: set) -> list[dict]:
    """The rows of one money table of this company whose (proposal id, case number) is one of `pairs` (read-only)."""
    if not pairs:
        return []
    ids = sorted({p for p, _ in pairs})
    marks = ", ".join("?" for _ in ids)
    rows = _read(COMPANY_DBS[company](), f"SELECT * FROM {table} WHERE proposal_id IN ({marks})", tuple(ids))
    return [{**r, "case": r[column]} for r in rows if (r["proposal_id"], r[column]) in pairs]


def _refunds(tickets: list[dict], steps: list[dict], approvals: list[dict]) -> dict:
    """Finance's decisions (approvals) and the money CallVerse paid on these tickets, from each company's own data: a
    row counts only if its (proposal id, case number) is one of that company's tickets' proposals (read-only).
    money_per_company = the totals of each company; the top-level totals add them up."""
    company_of = {t["id"]: t["company"] for t in tickets}
    pairs, finance_pairs = defaultdict(set), defaultdict(set)
    for s in steps:
        if kind_of(s) == "coordinator_decision" and s["data"].get("proposal_id"):
            pairs[company_of[s["ticket_id"]]].add((s["data"]["proposal_id"], s["data"].get("order_id")))
    for a in approvals:
        if a["proposal_id"]:
            pairs[company_of[a["ticket_id"]]].add((a["proposal_id"], a["order_id"]))
        if a["status"] == "approved":
            finance_pairs[company_of[a["ticket_id"]]].add((a["proposal_id"], a["order_id"]))

    per_company = []
    for company in sorted(set(company_of.values()) & set(MONEY_TABLES)):
        tables = MONEY_TABLES[company]
        refunds = _paid(company, *tables["refunds"], pairs[company])
        compensations = _paid(company, *tables["compensations"], pairs[company]) if "compensations" in tables else []
        after_finance = [r for r in refunds + compensations if (r["proposal_id"], r["case"]) in finance_pairs[company]]
        per_company.append({"company": company,
                            "refunds_paid": len(refunds), "refunds_tnd": round(sum(r["amount"] for r in refunds), 2),
                            "compensations_paid": len(compensations),
                            "compensations_tnd": round(sum(r["amount"] for r in compensations), 2),
                            "finance_tnd": round(sum(r["amount"] for r in after_finance), 2)})
    total = lambda key: round(sum(c[key] for c in per_company), 2)   # noqa: E731
    status = Counter(a["status"] for a in approvals)
    return {"finance_approved": status["approved"], "finance_refused": status["refused"],
            "finance_pending": status["pending"],
            "refunds_paid": total("refunds_paid"), "refunds_tnd": total("refunds_tnd"),
            "compensations_paid": total("compensations_paid"), "compensations_tnd": total("compensations_tnd"),
            "finance_tnd": total("finance_tnd"), "money_per_company": per_company}


def satisfaction() -> dict:
    """ShopNova's average review score (its real Olist reviews, 1-5). Agent F (satisfaction) comes later."""
    rows = _read(shopnova_db.db_path(), "SELECT COUNT(*) AS n, AVG(score) AS avg FROM reviews")
    n = rows[0]["n"] if rows else 0
    return {"reviews": n, "review_avg": round(rows[0]["avg"], 2) if n else None}


def groq_today(now: datetime | None = None) -> dict:
    """Groq tokens used TODAY (computer date): the model calls of all tickets + the system tokens (quota pings),
    out of the free daily quota (console.groq_daily_tokens). Rows without a computer time are not counted."""
    today = _now(now).date().isoformat()
    in_steps = sum(tokens_of(s) for s in _steps()
                   if kind_of(s) == "llm_call" and s["data"].get("provider") == "groq"
                   and (s.get("at_real") or "")[:10] == today)
    system = sum(int(r["tokens"]) for r in _read(store.db_path(), "SELECT * FROM system_tokens")
                 if r.get("provider") == "groq" and (r.get("at_real") or "")[:10] == today)
    return {"tickets": in_steps, "system": system, "total": in_steps + system,
            "limit": int(_console_cfg().get("groq_daily_tokens", 200000))}
