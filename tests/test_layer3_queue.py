"""T18 tests: the REAL Layer 3 queue (layer3 mode "queue").

Coordinator: a refund above 300 TND gives "layer3_pending", the proposal stays undecided, nothing is written;
stub mode is unchanged. Channel: the approval row + "Waiting for finance"; the duplicate guard calls no agent.
decide(): approve writes the refund + message + Solved + unread; refuse pays nothing and never shows the admin's
reason; a failed re-check writes nothing; a second decision is refused.

No API call: fake LLM for the agents, the SLM is offline (conftest: the template writes the reply).
"""

import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest

from callverse.channels import approvals, web_chat
from callverse.coordinator.coordinator import new_case, review
from callverse.data import admin_reads, db, writes
from callverse.data.layer3 import layer3_mode
from callverse.kb import search
from callverse.tickets import store
from callverse.tools.shopnova_tools import get_order, get_refunds

PENDING_SENTENCE = "Your refund of 378.00 TND for order 4515 needs approval from our finance team."
SECRET_REASON = "Client is on the internal watch list XQ-77"


@pytest.fixture(autouse=True)
def queue_mode(tmp_path, monkeypatch):
    """Queue mode on, a fresh tickets DB, Agent B's quota "there"."""
    monkeypatch.setenv("CALLVERSE_LAYER3_MODE", "queue")
    store.use_db(tmp_path / "callverse_test.db")
    monkeypatch.setattr(web_chat, "agent_b_ready", lambda: True)
    yield
    store.use_db(store.DEFAULT_DB_PATH)


def refund_4515(amount=378.00):
    return {"agent": "B", "action": "refund", "params": {"order_id": 4515, "amount": amount}, "rule_id": "R-REF-03",
            "facts_used": {"days_late": 8, "delivered": False, "paid": 378.0, "refunded_total": 0.0},
            "user_confirmed": True, "user_quote": "I want a refund please."}


def proposal_row(pid: str) -> dict:
    return admin_reads.proposal(pid)


def admin_log() -> list[tuple]:
    with closing(sqlite3.connect(db.db_path())) as con:
        return con.execute("SELECT admin, action, target_table FROM admin_actions ORDER BY id").fetchall()


def tool_call_reply(name, arguments):
    call = SimpleNamespace(id="call_1", function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))
    return SimpleNamespace(content=None, tool_calls=[call])


def refund_llm():
    """Fake LLM: Agent B reads order 4515, searches the rules and proposes 378.00 TND under R-REF-03."""
    p = refund_4515()
    steps = iter([tool_call_reply("get_order", {"order_id": 4515}),
                  tool_call_reply("get_refunds", {"order_id": 4515}),
                  tool_call_reply("search_policy", {"query": "refund for a late order"}),
                  tool_call_reply("propose_refund", {"order_id": 4515, "amount": 378.00, "rule_id": "R-REF-03",
                                                     "facts_used": p["facts_used"], "user_confirmed": True,
                                                     "user_quote": p["user_quote"]})])

    def fake(role_key, messages, tools=None):
        return next(steps, None) or SimpleNamespace(content="Your refund request is sent for checking.",
                                                    tool_calls=None)
    return fake


def no_llm(role_key, messages, tools=None):
    raise AssertionError("no LLM call expected")


def pending_approval() -> dict:
    """A pending approval as the channel makes it: Coordinator in queue mode + a ticket + the approvals row."""
    decision = review(refund_4515(), new_case("T-0001"))
    ticket = store.create_ticket("shopnova", 2)
    store.add_message(ticket["id"], "user", "My order 4515 is very late, I want a refund please.")
    store.add_step(ticket["id"], None, "intake", "intake",
                   {"style": {"formality": "formal", "length": "short"}, "emotion": {"label": "anger"},
                    "sentiment": {"label": "negative"}, "main_reason": "refund_request"})
    store.update_ticket(ticket["id"], status="Waiting for finance")
    return store.create_approval(ticket["id"], 4515, decision["facts"]["amount_tnd"], decision["proposal_id"])


# ---------- the switch and the Coordinator ----------

def test_mode_comes_from_the_env_var_else_config(monkeypatch):
    assert layer3_mode() == "queue"
    monkeypatch.delenv("CALLVERSE_LAYER3_MODE")
    assert layer3_mode() == "stub"                    # config.yaml default
    monkeypatch.setenv("CALLVERSE_LAYER3_MODE", "bank")
    with pytest.raises(ValueError):
        layer3_mode()


def test_queue_mode_gives_layer3_pending_and_writes_nothing(monkeypatch):
    monkeypatch.setattr("callverse.coordinator.coordinator.layer3_decide",
                        lambda *a, **k: pytest.fail("the stub must not be called in queue mode"))
    d = review(refund_4515(), new_case("T-1"))
    assert d["outcome"] == "layer3_pending" and d["facts"]["layer3_decision"] == "pending"
    assert d["must_say"] == [PENDING_SENTENCE]
    assert d["next_step"] == "We will reply here as soon as it has been reviewed."
    p = proposal_row(d["proposal_id"])
    assert p["decision"] is None and p["decided_at"] is None                    # undecided: the admin decides
    assert get_refunds(4515)["refunds"] == [] and get_order(4515)["status"] == "stuck_at_depot"


def test_queue_mode_leaves_small_refunds_alone():
    d = review({**refund_4515(), "params": {"order_id": 4512, "amount": 59.90}}, new_case("T-2"))
    assert d["outcome"] == "approve" and get_refunds(4512)["refunded_total"] == 59.90


def test_stub_mode_is_unchanged(monkeypatch):
    monkeypatch.setenv("CALLVERSE_LAYER3_MODE", "stub")
    d = review(refund_4515(), new_case("T-3"))
    assert d["outcome"] == "approve" and d["facts"]["layer3_decision"] == "approved"
    assert d["must_say"] == ["Your refund of 378.00 TND is approved after a check by our finance team."]
    assert proposal_row(d["proposal_id"])["decision"] == "approve"


# ---------- the channel ----------

def test_channel_creates_the_approval_and_waits_for_finance(monkeypatch):
    monkeypatch.setattr(search, "search_policy",
                        lambda query, k=3: [{"id": "R-REF-03", "title": "", "text": "", "score": 1.0}])
    out = web_chat.send(2, "shopnova", "My order 4515 is very late, I want a refund please.", chat_fn=refund_llm())
    assert out["outcome"] == "layer3_pending" and out["status"] == "Waiting for finance"
    assert PENDING_SENTENCE in out["reply"] and "as soon as it has been reviewed" in out["reply"]
    [a] = store.approvals("pending")
    assert (a["ticket_id"], a["order_id"], a["amount"]) == (out["ticket_id"], 4515, 378.0)
    assert proposal_row(a["proposal_id"])["decision"] is None
    assert "approval" in [s["step"] for s in store.steps(out["ticket_id"])]
    assert get_refunds(4515)["refunds"] == []

    # Duplicate guard: same order again (a new chat) -> the fixed reply, NO agent call.
    again = web_chat.send(2, "shopnova", "Any news about my refund for order 4515?", chat_fn=no_llm)
    assert again["reply"] == web_chat.ALREADY_PENDING_REPLY.format(order_id=4515)
    assert again["outcome"] == "approval_pending" and again["ticket_id"] != out["ticket_id"]
    kinds = [s["step"] for s in store.steps(again["ticket_id"])]
    assert "approval_pending" in kinds and "route" not in kinds and "proposal" not in kinds
    assert len(store.approvals("pending")) == 1


def test_duplicate_guard_only_for_the_order_with_a_pending_approval(monkeypatch):
    pending_approval()
    monkeypatch.setattr(web_chat.pipeline, "handle_ticket", lambda t, **k: {
        "decision": {"outcome": "info"}, "handover": None, "route": {"agent": "A"},
        "final_reply": "Your order 4510 is on its way.", "reply_source": "template"})
    out = web_chat.send(2, "shopnova", "Where is my order 4510?", chat_fn=no_llm)    # another order: as normal
    assert out["reply"] == "Your order 4510 is on its way." and out["status"] == "Solved"


# ---------- the admin's decision ----------

def test_approve_writes_the_refund_the_message_and_solves_the_ticket():
    a = pending_approval()
    out = approvals.decide(a["id"], "admin", True, "")
    assert out["outcome"] == "approve"
    refund = out["refund"]
    assert (refund["order_id"], refund["amount"], refund["rule_id"], refund["proposal_id"]) == \
        (4515, 378.0, "R-REF-03", a["proposal_id"])
    assert get_order(4515)["status"] == "refunded"                                  # R-REF-03, as the Coordinator
    assert proposal_row(a["proposal_id"])["decision"] == "approve"
    approval = store.get_approval(a["id"])
    assert (approval["status"], approval["decided_by"]) == ("approved", "admin") and approval["decided_at"]
    assert admin_log() == [("admin", "approve_refund", "refunds")]
    reply = store.messages(a["ticket_id"])[-1]
    assert reply["sender"] == "assistant"
    assert "Your refund of 378.00 TND is approved after a check by our finance team." in reply["text"]
    assert "Your order 4515 is now refunded." in reply["text"]
    assert reply["text"].startswith("Dear customer, please accept our apologies")  # the saved style: formal + upset
    ticket = store.get_ticket(a["ticket_id"])
    assert ticket["status"] == "Solved" and ticket["user_unread"] == 1
    assert "layer3" in [s["step"] for s in store.steps(a["ticket_id"])]


def test_refuse_needs_a_reason_pays_nothing_and_hides_the_reason():
    a = pending_approval()
    assert "reason is required" in approvals.decide(a["id"], "admin", False, "  ")["error"]
    assert store.get_approval(a["id"])["status"] == "pending"

    out = approvals.decide(a["id"], "admin", False, SECRET_REASON)
    assert out["outcome"] == "layer3_refused" and out["refund"] is None
    assert get_refunds(4515)["refunds"] == [] and get_order(4515)["status"] == "stuck_at_depot"
    assert proposal_row(a["proposal_id"])["decision"] == "layer3"
    approval = store.get_approval(a["id"])
    assert (approval["status"], approval["reason"]) == ("refused", SECRET_REASON)    # stored only
    text = store.messages(a["ticket_id"])[-1]["text"]
    assert "We cannot approve a refund of 378.00 TND for order 4515." in text
    assert "XQ-77" not in text and "watch list" not in text                       # never shown to the user
    assert store.get_ticket(a["ticket_id"])["status"] == "Solved"
    assert admin_log() == [("admin", "refuse_refund", "proposals")]


def test_refuse_reason_never_reaches_the_slm():
    a = pending_approval()
    seen = []

    def fake_slm(role_key, messages, **kwargs):
        seen.append(json.dumps(messages))
        return SimpleNamespace(content="Dear customer, we cannot approve a refund of 378.00 TND for order 4515. "
                                       "Our finance team reviewed it and did not approve it.", tool_calls=None)
    approvals.decide(a["id"], "admin", False, SECRET_REASON, slm_chat_fn=fake_slm)
    assert seen and not any("XQ-77" in s for s in seen)


def test_failed_recheck_writes_nothing():
    a = pending_approval()
    for status in ("out_for_delivery", "delivered"):          # meanwhile the parcel arrived: R-REF-03 no longer holds
        writes.set_order_status(4515, status)
    messages, steps = len(store.messages(a["ticket_id"])), len(store.steps(a["ticket_id"]))
    out = approvals.decide(a["id"], "admin", True)
    assert out["recheck_failed"] and "R-REF-03 does not apply any more" in out["error"]
    assert get_refunds(4515)["refunds"] == [] and proposal_row(a["proposal_id"])["decision"] is None
    assert store.get_approval(a["id"])["status"] == "pending" and admin_log() == []
    assert len(store.messages(a["ticket_id"])) == messages and len(store.steps(a["ticket_id"])) == steps
    # The admin can still refuse it.
    assert approvals.decide(a["id"], "admin", False, "Delivered meanwhile.")["outcome"] == "layer3_refused"


def test_recheck_also_checks_r_ref_05():
    a = pending_approval()
    with closing(db.connect()) as con:     # temp test DB only: a partial refund was paid meanwhile
        con.execute("INSERT INTO refunds (order_id, amount, status, created_at) VALUES (4515, 100, 'approved', "
                    "'2026-10-09')")
        con.commit()
    out = approvals.decide(a["id"], "admin", True)
    assert "R-REF-05" in out["error"] and store.get_approval(a["id"])["status"] == "pending"


def test_a_second_decision_is_refused():
    a = pending_approval()
    assert approvals.decide(a["id"], "admin", True)["outcome"] == "approve"
    assert "already approved" in approvals.decide(a["id"], "admin", True)["error"]
    assert "already approved" in approvals.decide(a["id"], "admin", False, "oops")["error"]
    assert len(get_refunds(4515)["refunds"]) == 1 and len(admin_log()) == 1
    assert not store.close_approval(a["id"], "refused", "admin", "late click")      # closes only a PENDING row


def test_platform_refusal_gives_the_extra_check_message(monkeypatch):
    a = pending_approval()
    monkeypatch.setattr(writes, "create_refund", lambda *args: {"error": "safety net: test refusal"})
    out = approvals.decide(a["id"], "admin", True)
    assert out["outcome"] == "escalate" and out["ticket"]["status"] == "Open"
    approval = store.get_approval(a["id"])
    assert approval["status"] == "refused" and "test refusal" in approval["reason"]
    assert "passed on for review" in store.messages(a["ticket_id"])[-1]["text"]


def test_unread_notice_is_cleared_without_moving_the_reopen_window():
    a = pending_approval()
    approvals.decide(a["id"], "admin", True)
    before = store.get_ticket(a["ticket_id"])
    assert [t["id"] for t in store.unread_tickets("shopnova", 2)] == [a["ticket_id"]]
    store.set_unread(a["ticket_id"], False)
    after = store.get_ticket(a["ticket_id"])
    assert after["user_unread"] == 0 and after["updated_at"] == before["updated_at"]
    assert store.unread_tickets("shopnova", 2) == []


def test_old_tickets_db_gets_the_user_unread_column(tmp_path):
    old = tmp_path / "old_callverse.db"
    with closing(sqlite3.connect(old)) as con:    # a T17 tickets table, without user_unread
        con.execute("CREATE TABLE tickets (id TEXT PRIMARY KEY, company TEXT NOT NULL, user_id INTEGER NOT NULL,"
                    " status TEXT NOT NULL, main_reason TEXT, priority TEXT, lead_agent TEXT, created_at TEXT NOT"
                    " NULL, updated_at TEXT NOT NULL, closed_at TEXT)")
        con.execute("INSERT INTO tickets VALUES ('T-0001', 'shopnova', 1, 'Solved', NULL, NULL, NULL, 'x', 'x', NULL)")
        con.commit()
    store.use_db(old)
    assert store.get_ticket("T-0001")["user_unread"] == 0
