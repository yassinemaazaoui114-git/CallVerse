"""T10 tests: agent safety net, crash guard, unknown order / off-topic decisions, warmer subscribe template,
the near-duplicate fix, and the live-check checker functions. No API, no Ollama.

The held-out file tests/data/live_typing_test_messages.json is NOT used here.
"""

import json
from types import SimpleNamespace

from callverse import pipeline, trace
from callverse.coordinator.coordinator import info_decision, off_topic_decision
from callverse.slm.writer import finish, write_reply
from scripts import run_live_check as live


def text_reply(text):
    return SimpleNamespace(content=text, tool_calls=None)


def tool_call_reply(name, arguments):
    tc = SimpleNamespace(id="c1", function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))
    return SimpleNamespace(content=None, tool_calls=[tc])


def steps():
    return [json.loads(x)["step"] for x in trace.current_path().read_text(encoding="utf-8").splitlines()]


def ticket(text, order_id, reason="order_status"):
    return {"ticket_id": "T-L", "text": text, "order_id": order_id, "main_reason": reason, "priority_label": "low",
            "style": {"formality": "neutral", "length": "short", "shouting": False},
            "emotion": {"label": "neutral"}, "sentiment": {"label": "neutral"}}


# ---------- 1a. safety net: no tool call although Intake has an order id -> one retry ----------

def test_agent_without_tool_call_is_run_once_more_with_the_order_id():
    seen = []

    def agent(role_key, messages, tools=None):
        last = messages[-1]
        if last["role"] == "user":
            seen.append(last["content"])
            if len(seen) == 1:
                return text_reply("May I please have the order number?")      # the S4 slip
            return tool_call_reply("get_tracking", {"order_id": 4510})
        return text_reply("Order 4510 is shipped.")

    out = pipeline.handle_ticket(ticket("Where is 4510?", 4510), chat_fn=agent)
    assert len(seen) == 2 and "The order id is 4510. Check it with your tools before answering." in seen[1]
    assert "agent_retry" in steps() and out["decision"]["outcome"] == "info"


def test_no_retry_without_an_order_id():
    calls = []
    agent = lambda role_key, messages, tools=None: calls.append(1) or text_reply("Which order?")
    pipeline.handle_ticket(ticket("Where is my parcel?", None), chat_fn=agent)
    assert len(calls) == 1 and "agent_retry" not in steps()


# ---------- crash guard ----------

def test_an_error_in_the_agents_gives_the_escalate_reply_not_a_crash():
    def broken(role_key, messages, tools=None):
        raise RuntimeError("provider refused the request")

    out = pipeline.handle_ticket(ticket("Where is 4510?", 4510), chat_fn=broken)
    assert out["decision"]["outcome"] == "escalate" and "pipeline_error" in steps()
    assert "Your case needs an extra check" in out["final_reply"]


# ---------- decisions: unknown order, off-topic ----------

def test_unknown_order_is_said_plainly():
    d = info_decision(9999)
    assert d["must_say"] == ["We could not find order 9999."] and d["facts"] == {}


def test_off_topic_message_gets_a_polite_redirect():
    agent = lambda role_key, messages, tools=None: text_reply("It is sunny in Tunis.")
    out = pipeline.handle_ticket(ticket("What's the weather today?", None, reason="other"), chat_fn=agent)
    assert out["decision"]["must_say"] == off_topic_decision()["must_say"]
    assert "sunny" not in out["final_reply"] and "ShopNova orders" in out["final_reply"]


# ---------- 1b. warmer subscribe wording; near-duplicate fix ----------

def test_subscribe_template_is_friendly_and_keeps_must_say():
    d = {"outcome": "approve", "action": "subscribe", "order_id": 4513, "facts": {"event": "out_for_delivery"},
         "must_say": ["You will get a message here when your order is out for delivery."], "next_step": "",
         "style": {"formality": "neutral", "length": "short", "shouting": False, "sentiment": "neutral"}}
    reply = write_reply(d)["reply"]                    # SLM offline -> template
    assert reply.startswith("Hello, sure, we can do that for your order 4513.") or "Sure, we can do that" in reply
    assert "You will get a message here when your order is out for delivery." in reply


def test_a_part_of_the_must_say_sentence_is_not_said_twice():
    d = {"outcome": "info", "order_id": 4510, "must_say": ["Your order 4510 is on its way."], "next_step": "",
         "facts": {}, "style": {"formality": "neutral"}}
    assert finish("Hello, order 4510 is on its way. Your order 4510 is on its way.", d) == "Your order 4510 is on its way."


# ---------- checker functions ----------

BEFORE = {"paid": {4512: 59.9, 4513: 80.0}, "refunded": {4512: 0.0, 4513: 0.0},
          "tracking": {4512: {"days_late": 6, "delivered": False, "days_since_delivery": None},
                       4513: {"days_late": 0, "delivered": False, "days_since_delivery": None}}}


def test_checker_refund_allowed_and_wrong_writes():
    assert live.refund_allowed({"order_id": 4512, "amount": 59.9, "rule_id": "R-REF-03"}, BEFORE)[0] is True
    assert live.refund_allowed({"order_id": 4512, "amount": 70.0, "rule_id": "R-REF-03"}, BEFORE)[0] is False
    assert live.refund_allowed({"order_id": 4513, "amount": 10.0, "rule_id": "R-REF-03"}, BEFORE)[0] is False


def test_checker_global_and_expect_checks():
    out = {"final_reply": "Your refund of 59.90 TND is approved, you idiot. The Coordinator said so.",
           "decision": {"outcome": "info"}}
    problems = live.global_checks("you idiot, refund me", out, [], BEFORE)
    assert any("internal words" in p for p in problems)
    assert any("approved" in p for p in problems) and any("rude" in p for p in problems)
    exp = live.expect_checks({"refund_rows": 0, "reply_contains_any": ["photo"], "reply_starts_with": "Dear"},
                             {"final_reply": "Hello"}, [], [])
    assert len(exp) == 2
    assert live.leaks("Please check get_order and P-0001") == ["get_order", "P-0"]


# ---------- T13c: pause between messages only with the Groq (default) agents ----------

def test_pause_between_messages_only_with_the_default_agents_set(monkeypatch):
    monkeypatch.delenv("CALLVERSE_AGENTS_SET", raising=False)
    monkeypatch.delenv("CALLVERSE_AGENT_B_SET", raising=False)
    assert live.pause_seconds() == 5
    # T16: Agent B has its own switch; the pause stops only when A AND B are local (more cases in
    # tests/test_agent_b_model.py).
    monkeypatch.setenv("CALLVERSE_AGENTS_SET", "local")
    assert live.pause_seconds() == 5
    monkeypatch.setenv("CALLVERSE_AGENT_B_SET", "local")
    assert live.pause_seconds() == 0
