"""T19 tests: the CallVerse Console (apps/console) and its read-only data layer (callverse/console/reads.py),
the new computer-time columns + reply seconds, and the new ticket status "Escalated".

- each Console page loads for the supervisor and shows only "please log in" for the admin, a user and no login;
- the KPI math on a temporary callverse.db + shopnova.db with KNOWN tickets (solved / escalated / finance / late /
  tokens / system tokens / today's Groq), and the Agents page's counts;
- the Console's connections cannot write (an INSERT fails), and a missing file is never created;
- an old-style callverse.db (made before T19) gets the new columns and accepts "Escalated", rows kept.

No API call: the Console calls no model (llm.chat is made to fail here), the refunds are written by the
Coordinator's own review (stub Layer 3), the SLM is offline (conftest). Temporary accounts file and tickets DB.
"""

import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

import bcrypt
import pytest
import yaml
from streamlit.testing.v1 import AppTest

from callverse import llm
from callverse.auth import accounts
from callverse.channels import approvals, web_chat
from callverse.console import reads
from callverse.coordinator.coordinator import new_case, review
from callverse.data import db
from callverse.tickets import store

APP = Path(__file__).resolve().parent.parent / "apps" / "console"
sys.path.insert(0, str(APP))   # the pages import console_ui (Streamlit adds this folder itself when it runs)
PAGES = {"live": APP / "pages" / "1_Live_tickets.py", "detail": APP / "pages" / "2_Ticket_detail.py",
         "agents": APP / "pages" / "3_Agents.py", "dashboard": APP / "pages" / "4_Dashboard.py"}
TIMEOUT = 60
NOW = datetime.now()
TODAY = NOW.isoformat(timespec="seconds")
YESTERDAY = (NOW - timedelta(days=1)).isoformat(timespec="seconds")


@pytest.fixture(autouse=True)
def console_env(tmp_path, monkeypatch):
    hashed = bcrypt.hashpw(b"test-only", bcrypt.gensalt(rounds=4)).decode()
    users = {u: {"name": name, "roles": [role], "user_id": uid, "password": hashed}
             for u, name, _, role, uid in accounts.DEMO_ACCOUNTS}
    path = tmp_path / "accounts.yaml"
    path.write_text(yaml.safe_dump({"credentials": {"usernames": users},
                                    "cookie": {"name": "t", "key": "k" * 32, "expiry_days": 1}}), encoding="utf-8")
    accounts.use_accounts(path)
    store.use_db(tmp_path / "callverse_test.db")

    def no_model(*args, **kwargs):
        raise AssertionError("the Console must not call any model")
    monkeypatch.setattr(llm, "chat", no_model)
    yield
    accounts.use_accounts(accounts.DEFAULT_ACCOUNTS_PATH)
    store.use_db(store.DEFAULT_DB_PATH)


def run(path: Path, username: str | None = None, **state) -> AppTest:
    at = AppTest.from_file(str(path), default_timeout=TIMEOUT)
    if username:
        at.session_state["authentication_status"] = True
        at.session_state["username"] = username
    for key, value in state.items():
        at.session_state[key] = value
    return at.run()


def sql(statement: str, params: tuple = ()) -> None:
    """A test-only write in the temporary tickets DB (e.g. to make a step "yesterday")."""
    with closing(sqlite3.connect(store.db_path())) as con:
        con.execute(statement, params)
        con.commit()


def llm_step(ticket_id, message_id, role, provider, model, tokens, seconds=1.0):
    store.add_step(ticket_id, message_id, "llm", role, {"trace_step": "llm_call", "role": role, "provider": provider,
                                                         "model": model, "seconds": seconds,
                                                         "tokens": {"total": tokens}})


def refund_ticket(user_id, order_id, amount, tokens, reply_seconds, text):
    """A refund ticket the way the channel saves it: Intake, route, B's tools, proposal, the Coordinator's REAL
    review (stub Layer 3: it writes the refund in shopnova.db), the reply. Returns (ticket, decision)."""
    t = store.create_ticket("shopnova", user_id)
    mid = store.add_message(t["id"], "user", text)
    store.add_step(t["id"], mid, "intake", "intake", {"trace_step": "intake_ticket", "main_reason": "refund_request",
                                                      "emotion": "anger", "sentiment": "negative",
                                                      "priority_label": "high", "order_id": order_id, "seconds": 0.5})
    store.add_step(t["id"], mid, "route", "router", {"trace_step": "route", "agent": "B", "reason": "refund_request"})
    llm_step(t["id"], mid, "agent_b", "groq", "openai/gpt-oss-120b", tokens, seconds=2.0)
    store.add_step(t["id"], mid, "tool_call", "B", {"trace_step": "tool_call", "agent": "B", "tool": "get_order",
                                                    "args": {"order_id": order_id}, "result": {"id": order_id}})
    store.add_step(t["id"], mid, "search_policy", "B", {
        "trace_step": "tool_call", "agent": "B", "tool": "search_policy", "args": {"query": "late refund"},
        "result": {"results": [{"id": "R-REF-03"}]}})
    proposal = {"agent": "B", "action": "refund", "params": {"order_id": order_id, "amount": amount},
                "rule_id": "R-REF-03", "facts_used": {"days_late": 8}, "user_confirmed": True,
                "user_quote": "I want a refund"}
    store.add_step(t["id"], mid, "proposal", "proposal_tools", {"trace_step": "proposal", "order_id": order_id,
                                                                "amount": amount, "rule_id": "R-REF-03"})
    store.add_step(t["id"], mid, "coordinator", "coordinator", {"trace_step": "coordinator_check", "check": "rule_condition",
                                                                "rule_id": "R-REF-03", "result": "pass", "detail": "ok"})
    decision = review(proposal, new_case(t["id"]))
    assert decision["outcome"] == "approve", decision
    store.add_step(t["id"], mid, "coordinator", "coordinator", {"trace_step": "coordinator_decision", **decision})
    llm_step(t["id"], mid, "slm", "ollama", "qwen2.5:1.5b", 100)
    store.add_step(t["id"], mid, "slm", "pipeline", {"trace_step": "final_reply", "outcome": "approve",
                                                     "reply_source": "slm", "seconds": 1.5})
    store.add_message(t["id"], "assistant", "Your refund is approved.", seconds=reply_seconds)
    store.update_ticket(t["id"], status="Solved", main_reason="refund_request", priority="high", lead_agent="B")
    return t, decision


@pytest.fixture
def known_tickets():
    """4 known tickets (the KPI test checks every number by hand):
    T-0001 Sara 4512 59.90 TND: solved by the AI alone, 1,000 + 100 tokens, reply 12 s;
    T-0002 Youssef 4515 378 TND: sent to finance (approval approved), 3,000 + 100 tokens, reply 45 s (LATE);
    T-0003 Amira: escalated, 500 Groq tokens YESTERDAY, reply 5 s;
    T-0004 Karim: waiting for the user, 0 tokens, a reply without seconds (like an old row).
    + 50 system tokens (Groq, today) and 70 system tokens yesterday."""
    t1, _ = refund_ticket(1, 4512, 59.90, 1000, 12.0, "My order 4512 is late, I want a refund please.")
    t2, d2 = refund_ticket(2, 4515, 378.0, 3000, 45.0, "My order 4515 is very late, I want a refund please.")
    approval = store.create_approval(t2["id"], 4515, 378.0, d2["proposal_id"])
    store.close_approval(approval["id"], "approved", "admin", None)

    t3 = store.create_ticket("shopnova", 3)
    m3 = store.add_message(t3["id"], "user", "Where is my order 4511?")
    llm_step(t3["id"], m3, "agents", "groq", "openai/gpt-oss-120b", 500)   # before intake: Intake's fallback
    store.add_step(t3["id"], m3, "intake", "intake", {"trace_step": "intake_ticket", "main_reason": "delivery_status",
                                                      "priority_label": "low", "order_id": 4511, "seconds": 0.4})
    store.add_step(t3["id"], m3, "coordinator", "coordinator", {"trace_step": "coordinator_decision",
                                                                "outcome": "escalate", "reason": "test",
                                                                "proposal_id": None})
    store.add_message(t3["id"], "assistant", "Passed on for review.", seconds=5.0)
    store.update_ticket(t3["id"], status="Escalated", main_reason="delivery_status", priority="low", lead_agent="A")
    sql("UPDATE steps SET at_real = ? WHERE ticket_id = ? AND step = 'llm'", (YESTERDAY, t3["id"]))

    t4 = store.create_ticket("shopnova", 4)
    store.add_message(t4["id"], "user", "Hello?")
    store.add_message(t4["id"], "assistant", "Which order?")
    store.update_ticket(t4["id"], status="Waiting for user")

    store.add_system_tokens("quota_check", "groq", "openai/gpt-oss-120b", 50)
    old = store.add_system_tokens("quota_check", "groq", "openai/gpt-oss-120b", 70)
    sql("UPDATE system_tokens SET at_real = ? WHERE id = ?", (YESTERDAY, old))
    return [t1["id"], t2["id"], t3["id"], t4["id"]]


# ---------- pages and logins ----------

@pytest.mark.parametrize("page", list(PAGES))
def test_console_pages_load_for_the_supervisor(page, known_tickets):
    at = run(PAGES[page], "supervisor")
    assert not at.exception
    assert accounts.LOGIN_MESSAGE not in [i.value for i in at.info]
    assert reads.NO_TICKETS not in [i.value for i in at.info]


@pytest.mark.parametrize("username", [None, "admin", "sara"])
@pytest.mark.parametrize("page", list(PAGES))
def test_console_pages_show_only_please_log_in_to_others(page, username, known_tickets):
    at = run(PAGES[page], username)
    assert not at.exception
    assert [i.value for i in at.info] == [accounts.LOGIN_MESSAGE]
    assert len(at.dataframe) == 0 and len(at.metric) == 0 and len(at.main.selectbox) == 0


@pytest.mark.parametrize("page", list(PAGES))
def test_console_pages_say_no_tickets_yet_without_data(page):
    at = run(PAGES[page], "supervisor")
    assert not at.exception
    assert reads.NO_TICKETS in [i.value for i in at.info]
    assert not store.db_path().exists()                     # reading never creates the file


def test_live_tickets_page_shows_the_tickets_newest_first(known_tickets):
    at = run(PAGES["live"], "supervisor")
    table = at.dataframe[0].value
    assert list(table["id"]) == ["T-0004", "T-0003", "T-0002", "T-0001"]
    assert list(table["user"])[-1] == "Sara Ben Ali (1)"     # the name from the company's data
    at.selectbox(key="f_status").set_value("Escalated").run()
    assert list(at.dataframe[0].value["id"]) == ["T-0003"]


def test_ticket_detail_page_shows_the_timeline_of_the_finance_ticket(known_tickets):
    at = run(PAGES["detail"], "supervisor", console_ticket="T-0002")
    assert not at.exception and at.selectbox(key="detail_ticket").value == "T-0002"
    text = " ".join(m.value for m in at.markdown)
    assert "Finance approval" in text and "Youssef Trabelsi" in text
    for said in ("Intake read the message", "Routed to Agent B", "searched the rules", "R-REF-03",
                 "Proposal: refund", "Coordinator check: rule_condition", "Coordinator decision: **approve**",
                 "Reply written (first try)"):
        assert said in text, said
    assert any("Tokens: **3,100**" in c.value for c in at.caption)
    assert [e.label for e in at.expander] == ["details (raw step data)"]


# ---------- the KPI math (checked by hand in the fixture's docstring) ----------

def test_dashboard_numbers_on_known_tickets(known_tickets):
    d = reads.dashboard(now=NOW)
    assert d["tickets"] == 4
    assert (d["solved_ai"], d["solved_ai_pct"]) == (1, 25.0)                 # T-0001 only
    assert (d["escalated"], d["escalated_pct"]) == (1, 25.0)                 # T-0003
    assert (d["finance"], d["finance_pct"]) == (1, 25.0)                     # T-0002
    assert (d["replies_timed"], d["replies_untimed"]) == (3, 1)              # T-0004's reply has no seconds
    assert d["avg_reply_s"] == round((12 + 45 + 5) / 3, 2)
    assert (d["late"], d["late_pct"]) == (1, 33.3)                           # 45 s > 30 s
    assert (d["finance_approved"], d["finance_refused"], d["finance_pending"]) == (1, 0, 0)
    assert (d["refunds_paid"], d["refunds_tnd"], d["finance_tnd"]) == (2, 437.9, 378.0)
    assert (d["tokens_avg"], d["tokens_max"], d["tokens_total"]) == (1175, 3100, 4700)   # 1100, 3100, 500, 0
    assert d["system_tokens"] == 120                                         # shown apart, never in a ticket
    assert d["groq_today"] == {"tickets": 4000, "system": 50, "total": 4050, "limit": 200000}
    assert d["review_avg"] is not None and d["reviews"] > 0
    assert sum(r["tickets"] for r in d["per_day"]) == 4 and d["per_company"] == [{"company": "shopnova", "tickets": 4}]


def test_period_filter_uses_the_computer_time(known_tickets):
    sql("UPDATE tickets SET created_real = ? WHERE id = 'T-0001'", ((NOW - timedelta(days=10)).isoformat(),))
    sql("UPDATE tickets SET created_real = NULL WHERE id = 'T-0004'")         # an old row: only in "All"
    assert reads.dashboard(None, now=NOW)["tickets"] == 4
    assert reads.dashboard(30, now=NOW)["tickets"] == 3
    assert reads.dashboard(7, now=NOW)["tickets"] == 2
    assert reads.live_tickets(now=NOW)[0]["age"] == reads.NO_TIME             # T-0004 shown with "—"


def test_agents_cards_on_known_tickets(known_tickets):
    cards = {c["agent"]: c for c in reads.agents(now=NOW)}
    b = cards["B"]
    assert (b["tickets"], b["proposals"], b["approved"], b["tokens"]) == (2, 2, 2, 4000)
    assert b["avg_seconds"] == 2.0 and b["models"] == ["groq/openai/gpt-oss-120b"]
    assert cards["intake"]["tickets"] == 3 and cards["intake"]["tokens"] == 500    # T-0003's fallback call
    assert cards["coordinator"]["proposals"] == 2 and cards["coordinator"]["escalated"] == 1
    assert cards["coordinator"]["models"] == ["rules (no LLM)"]
    assert cards["writer"]["tokens"] == 200 and cards["writer"]["avg_seconds"] == 1.5
    assert cards["A"]["tickets"] == 0


def test_router_and_ask_agent_steps_belong_to_no_agent():
    step = lambda kind, saved_by, **data: {"step": kind, "agent": saved_by, "message_id": 1, "data": data}  # noqa: E731
    steps = [step("intake", "intake", trace_step="intake_ticket", emotion={"label": "sadness", "score": 0.711}),
             step("route", "B", trace_step="route", agent="B"),
             step("tool_call", "A", trace_step="ask_agent", agent="A", to="A"),
             step("tool_call", "B", trace_step="tool_call", agent="B", tool="ask_agent")]
    assert reads.actors(steps) == ["intake", None, None, "B"]
    assert "emotion sadness (0.71)" in reads.describe_step(steps[0])[2]


def test_every_step_kind_has_a_description(known_tickets):
    for ticket_id in known_tickets:
        for turn in reads.ticket_detail(ticket_id)["turns"]:
            for step in turn["steps"]:
                icon, title, _ = reads.describe_step(step)
                assert icon and title and icon != "•", step


# ---------- read only ----------

def test_console_connections_cannot_write(known_tickets):
    writes = [(store.db_path(), "INSERT INTO system_tokens (purpose, tokens, at) VALUES ('x', 1, 'now')"),
              (store.db_path(), "UPDATE tickets SET status = 'Closed'"),
              (db.db_path(), "INSERT INTO reviews (order_id, score) VALUES (4512, 5)")]
    for path, statement in writes:
        with closing(reads.connect_ro(path)) as con, pytest.raises(sqlite3.OperationalError, match="readonly"):
            con.execute(statement)
    assert [t["status"] for t in reads.live_tickets()] == ["Waiting for user", "Escalated", "Solved", "Solved"]


def test_missing_file_is_never_created(tmp_path):
    missing = tmp_path / "nothing.db"
    assert reads.connect_ro(missing) is None and reads.live_tickets() == [] and not missing.exists()


# ---------- new columns, old databases, the Escalated status ----------

OLD_SCHEMA = """
CREATE TABLE tickets (id TEXT PRIMARY KEY, company TEXT NOT NULL, user_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('New', 'Open', 'Waiting for user', 'Waiting for finance', 'Solved', 'Closed')),
    main_reason TEXT, priority TEXT, lead_agent TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, closed_at TEXT);
CREATE TABLE messages (id INTEGER PRIMARY KEY, ticket_id TEXT NOT NULL REFERENCES tickets(id),
    sender TEXT NOT NULL, text TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE steps (id INTEGER PRIMARY KEY, ticket_id TEXT NOT NULL REFERENCES tickets(id), message_id INTEGER,
    step TEXT NOT NULL, agent TEXT, data TEXT NOT NULL, at TEXT NOT NULL);
INSERT INTO tickets VALUES ('T-0001', 'shopnova', 1, 'Solved', 'refund_request', 'high', 'B',
    '2026-10-09T10:00:00', '2026-10-09T10:00:00', NULL);
INSERT INTO messages VALUES (1, 'T-0001', 'user', 'old message', '2026-10-09T10:00:00');
INSERT INTO messages VALUES (2, 'T-0001', 'assistant', 'old reply', '2026-10-09T10:00:00');
"""


def test_old_callverse_db_gets_the_new_columns_and_the_escalated_status():
    with closing(sqlite3.connect(store.db_path())) as con:
        con.executescript(OLD_SCHEMA)
    # The Console reads the old file as it is (read only): no crash, "—" for the missing times.
    assert reads.live_tickets()[0]["age"] == reads.NO_TIME
    assert reads.dashboard()["replies_untimed"] == 1
    # The store (channel side) adds the columns and rebuilds the status check once; the rows are kept.
    with closing(store.connect()) as con:
        assert {"user_unread", "created_real", "updated_real"} <= store._columns(con, "tickets")
        assert {"at_real", "seconds"} <= store._columns(con, "messages")
        assert "at_real" in store._columns(con, "steps")
    assert store.get_ticket("T-0001")["main_reason"] == "refund_request"
    assert [m["text"] for m in store.messages("T-0001")] == ["old message", "old reply"]
    assert store.messages("T-0001")[0]["at_real"] is None
    assert store.update_ticket("T-0001", status="Escalated")["status"] == "Escalated"
    assert store.get_ticket("T-0001")["updated_real"] is not None
    assert store.create_ticket("shopnova", 2)["id"] == "T-0002"
    with closing(store.connect()) as con:                     # connecting again changes nothing
        assert con.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 2


def test_new_rows_get_the_computer_time():
    t = store.create_ticket("shopnova", 1)
    assert t["created_real"] and t["created_real"] == t["updated_real"]
    assert datetime.fromisoformat(t["created_real"]).date() == datetime.now().date()
    mid = store.add_message(t["id"], "assistant", "hi", seconds=3.25)
    assert store.messages(t["id"])[0]["seconds"] == 3.25 and store.messages(t["id"])[0]["at_real"]
    store.add_step(t["id"], mid, "intake", "intake", {})
    assert store.steps(t["id"])[0]["at_real"]


def test_escalate_outcome_gives_escalated_and_the_next_message_continues_it(monkeypatch):
    monkeypatch.setattr(web_chat, "agent_b_ready", lambda: True)
    monkeypatch.setattr(web_chat.intake, "process", lambda text, chat_fn=None: {
        "order_id": None, "main_reason": "other", "priority_label": "low"})
    outcomes = iter(["escalate", "info"])
    monkeypatch.setattr(web_chat.pipeline, "handle_ticket", lambda t, **k: {
        "decision": {"outcome": next(outcomes)}, "handover": None, "route": {"agent": "A"},
        "final_reply": "A colleague will look.", "reply_source": "template"})
    first = web_chat.send(1, "shopnova", "Something strange happened.")
    assert first["status"] == "Escalated" == store.get_ticket(first["ticket_id"])["status"]
    reply = store.messages(first["ticket_id"])[-1]
    assert reply["sender"] == "assistant" and reply["seconds"] == first["seconds"] and reply["seconds"] is not None
    second = web_chat.send(1, "shopnova", "Any news?", ticket_id=first["ticket_id"])
    assert second["ticket_id"] == first["ticket_id"] and second["status"] == "Solved"


def test_admin_decision_reply_keeps_its_seconds(monkeypatch):
    monkeypatch.setenv("CALLVERSE_LAYER3_MODE", "queue")
    decision = review({"agent": "B", "action": "refund", "params": {"order_id": 4515, "amount": 378.0},
                       "rule_id": "R-REF-03", "facts_used": {"days_late": 8}, "user_confirmed": True},
                      new_case("T-0001"))
    assert decision["outcome"] == "layer3_pending"
    ticket = store.create_ticket("shopnova", 2)
    store.add_message(ticket["id"], "user", "My order 4515 is very late, I want a refund please.")
    approval = store.create_approval(ticket["id"], 4515, 378.0, decision["proposal_id"])
    out = approvals.decide(approval["id"], "admin", True)
    assert out["outcome"] == "approve"
    reply = store.messages(ticket["id"])[-1]
    assert reply["sender"] == "assistant" and isinstance(reply["seconds"], float)
