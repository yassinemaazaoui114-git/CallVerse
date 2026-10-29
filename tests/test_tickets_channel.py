"""T17 tests: the tickets store (callverse.db), the ticket rule, the trace listener and the web chat channel.

No API call: the agents get a fake LLM, the SLM is offline (conftest), the quota check is replaced.
Intake runs its local models on messages written for these tests (not from any held-out test set).
"""

import json
from types import SimpleNamespace

import pytest

from callverse import trace
from callverse.channels import web_chat
from callverse.data import clock
from callverse.kb import search
from callverse.tickets import store
from callverse.tools.registry import run_tool


@pytest.fixture(autouse=True)
def tickets_db(tmp_path, monkeypatch):
    """A fresh tickets database per test; Agent B's quota is "there" unless a test says otherwise."""
    store.use_db(tmp_path / "callverse_test.db")
    monkeypatch.setattr(web_chat, "agent_b_ready", lambda: True)
    yield
    store.use_db(store.DEFAULT_DB_PATH)


def tool_call_reply(name, arguments, call_id="call_1"):
    tool_call = SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))
    return SimpleNamespace(content=None, tool_calls=[tool_call])


def text_reply(text):
    return SimpleNamespace(content=text, tool_calls=None)


GOOD = {"order_id": 4512, "amount": 59.90, "rule_id": "R-REF-03",
        "facts_used": {"days_late": 6, "delivered": False, "paid": 59.90, "refunded_total": 0.0},
        "user_confirmed": True, "user_quote": "I want my money back."}


def refund_llm():
    """Fake LLM: Agent B reads order 4512, searches the rules and proposes 59.90 TND under R-REF-03."""
    steps = iter([tool_call_reply("get_order", {"order_id": 4512}),
                  tool_call_reply("get_refunds", {"order_id": 4512}),
                  tool_call_reply("search_policy", {"query": "refund for a late order"}),
                  tool_call_reply("propose_refund", GOOD)])

    def fake(role_key, messages, tools=None):
        assert not messages[0]["content"].startswith("You are Agent A"), "Agent A is not needed here"
        return next(steps, None) or text_reply("Your refund request is sent for checking.")
    return fake


def no_llm(role_key, messages, tools=None):
    raise AssertionError("no LLM call expected")


# ---------- store and ticket rule ----------

def test_ticket_ids_follow_each_other_and_start_new():
    first = store.create_ticket("shopnova", 1)
    second = store.create_ticket("shopnova", 2)
    assert (first["id"], second["id"]) == ("T-0001", "T-0002")
    assert first["status"] == "New" and first["created_at"] == clock.now().isoformat(timespec="seconds")


def test_messages_and_steps_are_saved_in_order():
    t = store.create_ticket("shopnova", 1)
    mid = store.add_message(t["id"], "user", "hello")
    store.add_message(t["id"], "assistant", "hi")
    store.add_step(t["id"], mid, "intake", "intake", {"main_reason": "other"})
    assert [m["sender"] for m in store.messages(t["id"])] == ["user", "assistant"]
    assert store.steps(t["id"])[0]["data"] == {"main_reason": "other"}
    with pytest.raises(ValueError):
        store.add_message(t["id"], "agent", "not a sender")


def test_statuses_are_checked_and_closed_at_is_set():
    t = store.create_ticket("shopnova", 1)
    for status in store.STATUSES:
        assert store.update_ticket(t["id"], status=status)["status"] == status
    assert store.get_ticket(t["id"])["closed_at"] is not None
    with pytest.raises(ValueError):
        store.update_ticket(t["id"], status="Lost")
    with pytest.raises(ValueError):
        store.update_ticket(t["id"], user_id=2)


def test_solved_ticket_reopens_within_3_days_then_a_new_one():
    t = store.create_ticket("shopnova", 1)
    store.update_ticket(t["id"], status="Solved")
    clock.advance(24 * 3)                                   # exactly 3 days later: still the same ticket
    again = store.ticket_for_message("shopnova", 1, t["id"])
    assert again["id"] == t["id"] and again["status"] == "Open"
    store.update_ticket(t["id"], status="Solved")
    clock.advance(24 * 3 + 1)                               # more than 3 days: a new ticket
    assert store.ticket_for_message("shopnova", 1, t["id"])["id"] == "T-0002"


def test_new_chat_other_user_and_closed_ticket_give_a_new_ticket():
    t = store.create_ticket("shopnova", 1)
    assert store.ticket_for_message("shopnova", 1, None)["id"] == "T-0002"          # "New chat"
    assert store.ticket_for_message("shopnova", 2, t["id"])["id"] == "T-0003"       # not this user's ticket
    store.update_ticket(t["id"], status="Waiting for user")
    assert store.ticket_for_message("shopnova", 1, t["id"])["id"] == t["id"]        # waiting: same ticket
    store.update_ticket(t["id"], status="Closed")
    assert store.ticket_for_message("shopnova", 1, t["id"])["id"] == "T-0004"
    assert store.current_ticket("shopnova", 1)["id"] == "T-0004"                    # her latest open ticket
    assert store.current_ticket("shopnova", 3) is None


# ---------- trace listener ----------

def test_trace_listener_gets_each_record_until_removed():
    heard = []
    trace.add_listener(heard.append)
    trace.log("x", "test", {"a": 1})
    trace.remove_listener(heard.append)
    trace.log("y", "test", {})
    trace.remove_listener(heard.append)                     # no error the second time
    assert [r["step"] for r in heard] == ["x"] and heard[0]["data"] == {"a": 1}


def test_a_broken_listener_never_breaks_the_trace():
    def broken(record):
        raise RuntimeError("page closed")
    trace.add_listener(broken)
    try:
        trace.log("x", "test", {})
    finally:
        trace.remove_listener(broken)
    assert "\"step\": \"x\"" in trace.current_path().read_text(encoding="utf-8")


# ---------- channel ----------

def test_refund_message_saves_ticket_messages_and_steps(monkeypatch):
    monkeypatch.setattr(search, "search_policy",
                        lambda query, k=3: [{"id": "R-REF-03", "title": "", "text": "", "score": 1.0}])
    live = []
    out = web_chat.send(1, "shopnova", "My order 4512 is late, I want a refund please.", on_step=live.append,
                        chat_fn=refund_llm())

    assert out["ticket_id"] == "T-0001" and out["outcome"] == "approve" and out["status"] == "Solved"
    assert "Your refund of 59.90 TND is approved." in out["reply"]
    ticket = store.get_ticket("T-0001")
    assert ticket["main_reason"] == "refund_request" and ticket["lead_agent"] == "B" and ticket["priority"]
    assert [m["sender"] for m in store.messages("T-0001")] == ["user", "assistant"]
    kinds = [s["step"] for s in store.steps("T-0001")]
    for kind in ("intake", "route", "tool_call", "search_policy", "proposal", "coordinator", "write", "slm"):
        assert kind in kinds, kind
    assert out["steps"] == len(kinds)
    assert live[0] == "Reading your message…" and "Checking with our refund team…" in live
    assert "Checking the rules…" in live and live[-1] == "Writing the reply…"
    assert len(live) == len(set(live))                                   # F5: each text once per message
    assert run_tool("B", "get_refunds", {"order_id": 4512})["refunded_total"] == 59.90   # written by the Coordinator


def test_quota_used_up_makes_no_pipeline_call(monkeypatch):
    monkeypatch.setattr(web_chat, "agent_b_ready", lambda: False)
    monkeypatch.setattr(web_chat.intake, "process", lambda *a, **k: pytest.fail("Intake must not run"))
    out = web_chat.send(1, "shopnova", "My order 4512 is late, I want a refund please.", chat_fn=no_llm)
    assert out["reply"] == web_chat.BUSY_REPLY and out["status"] == "Open"
    assert [s["step"] for s in store.steps(out["ticket_id"])] == ["quota"]
    assert run_tool("B", "get_refunds", {"order_id": 4512})["refunded_total"] == 0


def test_quota_check_is_cached_and_its_tokens_are_system_tokens(monkeypatch):
    calls = []
    monkeypatch.undo()                                       # the real agent_b_ready, with a fake quota check
    monkeypatch.setattr(web_chat.quota, "check_models", lambda role_key, stop_at_first_ok=False: calls.append(
        role_key) or [{"provider": "groq", "model": "openai/gpt-oss-120b", "status": "ok", "tokens": 97}])
    web_chat._quota_cache.clear()
    try:
        assert web_chat.agent_b_ready() and web_chat.agent_b_ready()
    finally:
        web_chat._quota_cache.clear()
    assert calls == ["agent_b"]
    rows = store.system_tokens()                             # Q5: saved apart, in no ticket
    assert [(r["purpose"], r["model"], r["tokens"]) for r in rows] == [("quota_check", "openai/gpt-oss-120b", 97)]


def test_quota_check_counts_the_tokens_of_its_ping(monkeypatch):
    from callverse import llm, quota

    def fake_chat(role_key, messages, **kwargs):
        trace.log("llm_call", "llm", {"role": role_key, "tokens": {"total": 42}})

    monkeypatch.setattr(llm, "chat", fake_chat)
    results = quota.check_models("agent_b", stop_at_first_ok=True)
    assert [(r["model"], r["status"], r["tokens"]) for r in results] == [("openai/gpt-oss-120b", "ok", 42)]


def test_live_texts_are_shown_once_per_message():
    shown = []
    records = [{"step": "intake_start"}, {"step": "tool_call", "data": {"tool": "get_order"}},
               {"step": "handover"}, {"step": "tool_call", "data": {"tool": "get_order"}},
               {"step": "coordinator_check"}, {"step": "coordinator_check"},
               {"step": "coordinator_decision", "data": {"outcome": "approve"}}]
    for r in records:
        said = web_chat.live_text(r)
        if said and said not in shown:
            shown.append(said)
    assert shown == ["Reading your message…", "Checking your order…", "Checking with our refund team…",
                     "Checking the rules…", "Writing the reply…"]


def test_asked_order_is_added_only_when_the_message_has_none():
    assert web_chat.with_order("Is it late?", 4512) == "Is it late? (order 4512)"
    assert web_chat.with_order("Is order 4509 late?", 4512) == "Is order 4509 late?"   # the user's number wins
    assert web_chat.with_order("Is it late?", None) == "Is it late?"


def test_asked_order_of_another_user_is_still_refused():
    # F1: the number added by the channel goes through the same identity check (4510 = Youssef's order)
    out = web_chat.send(1, "shopnova", "Where is it? It is late.", about_order=4510, chat_fn=no_llm)
    assert out["reply"] == web_chat.NOT_YOUR_ORDER_REPLY
    assert store.messages(out["ticket_id"])[0]["text"] == "Where is it? It is late. (order 4510)"


def test_order_of_another_user_gets_no_agent_call():
    # 4510 belongs to user 2 (Youssef), Sara is user 1
    out = web_chat.send(1, "shopnova", "Where is my order 4510? It is late.", chat_fn=no_llm)
    assert out["reply"] == web_chat.NOT_YOUR_ORDER_REPLY and out["outcome"] == "not_your_order"
    kinds = [s["step"] for s in store.steps(out["ticket_id"])]
    assert "identity" in kinds and "route" not in kinds and "tool_call" in kinds   # only Intake's own reads
    assert "4510" not in out["reply"] and "Aramex" not in out["reply"]


def test_unknown_order_is_treated_like_another_users_order():
    out = web_chat.send(1, "shopnova", "Where is my order 99999? It is late.", chat_fn=no_llm)
    assert out["reply"] == web_chat.NOT_YOUR_ORDER_REPLY


def test_any_error_gives_the_escalate_reply_and_an_error_step(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("database locked")
    monkeypatch.setattr(web_chat.pipeline, "handle_ticket", boom)
    out = web_chat.send(1, "shopnova", "Where is my order 4512?", chat_fn=no_llm)
    assert out["outcome"] == "escalate" and out["status"] == "Open"
    assert "passed on for review" in out["reply"]
    assert store.steps(out["ticket_id"])[-1]["step"] == "error"


def test_second_message_goes_on_the_same_ticket(monkeypatch):
    monkeypatch.setattr(web_chat.pipeline, "handle_ticket", lambda t, **k: {
        "decision": {"outcome": "ask_user"}, "handover": None, "route": {"agent": "A"},
        "final_reply": "Please confirm.", "reply_source": "template"})
    first = web_chat.send(1, "shopnova", "Where is my order 4512?", chat_fn=no_llm)
    assert first["status"] == "Waiting for user"
    second = web_chat.send(1, "shopnova", "Yes, I confirm for order 4512.", ticket_id=first["ticket_id"],
                           chat_fn=no_llm)
    assert second["ticket_id"] == first["ticket_id"] and len(store.messages(first["ticket_id"])) == 4
