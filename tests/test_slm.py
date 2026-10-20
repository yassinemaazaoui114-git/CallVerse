"""SLM reply writer (T05): rule check, templates, writer flow. No Ollama needed (fake LLM).

The decisions here are made up for the tests; the held-out set tests/data/slm_test_decisions.json is
not used by these tests.
"""

import json
from types import SimpleNamespace

import pytest

from callverse import trace
from callverse.slm import templates
from callverse.slm.check import check_reply
from callverse.slm.writer import build_messages, clean, write_reply

REFUND = {"outcome": "approve", "action": "refund", "order_id": 7001, "rule_id": "R-REF-03",
          "facts": {"amount_tnd": 12.50, "days_late": 8, "order_status": "stuck_at_depot"},
          "next_step": "The money goes back to your card.",
          "style": {"formality": "casual", "length": "short", "shouting": True, "emotion": "anger",
                    "sentiment": "negative"}}
LAYER3 = {"outcome": "layer3", "action": "refund", "order_id": 7002, "rule_id": "R-ESC-01",
          "facts": {"amount_tnd": 350.00, "threshold_tnd": 300.0, "days_late": 7},
          "next_step": "Our finance team reviews the request and we reply with their decision.",
          "style": {"formality": "formal", "length": "medium", "shouting": False, "emotion": "neutral",
                    "sentiment": "neutral"}}
GOOD = "Hi, I'm sorry about the wait on order 7001. Your refund of 12.50 TND is approved. The money goes back to your card."


def _steps() -> list[str]:
    return [json.loads(x)["step"] for x in trace.current_path().read_text(encoding="utf-8").splitlines()]


# --- rule check -------------------------------------------------------------

def test_good_reply_passes():
    assert check_reply(GOOD, REFUND) == {"passed": True, "problems": []}


@pytest.mark.parametrize("bad, problem", [
    ("", "empty"),
    ("Hi, order 7001: your refund of 15.00 TND is approved.", "numbers not in the decision: 15"),
    ("Hi, your refund of 12.50 TND is approved.", "order number 7001 is not mentioned"),
    ("Hi, order 7001: refund of 12.50 TND approved. We will keep you updated.", "forbidden promise"),
    ("Hi, order 7001: refund approved, we are monitoring the parcel.", "forbidden promise"),
    ("Hi, order 7001: we guarantee the refund.", "forbidden promise"),
    ("Hi, order 7001: you will get the money within two days.", "forbidden promise"),
    ("Hi, order 7001: refund of 12.50 TND approved under R-REF-03.", "rule id"),
    ("Dear [Name], order 7001: refund of 12.50 TND approved.", "placeholder"),
    ("Hi, order 7001: refund of $12.50 approved.", "currency"),
    ("Hi, order 7001 is with FedEx. The money goes back to your card.", "name not in the decision"),
    ("Hi, order 7001 is approved. The money goes back to your card. The money goes back to your card.", "repeated"),
    ("Hi order 7001 " + "word " * 120, "too long"),
])
def test_bad_replies_fail(bad, problem):
    result = check_reply(bad, REFUND)
    assert result["passed"] is False
    assert any(problem in p for p in result["problems"]), result["problems"]


def test_dates_and_amount_formats_from_facts_are_allowed():
    d = {**REFUND, "facts": {"promised_date": "2026-10-03", "amount_tnd": 59.90}, "order_id": 4512}
    assert check_reply("Hello, order 4512 was promised for October 3, 2026 (59,90 TND).", d)["passed"]
    assert check_reply("Hello, order 4512 was promised for 2026-10-03, amount 59.9 TND.", d)["passed"]


def test_layer3_reply_must_not_promise_the_refund():
    for promise in ("Your refund of 350.00 TND is approved.", "You will receive a full refund.",
                    "We will refund you.", "The money will be returned to your card."):
        result = check_reply(f"Dear customer, about order 7002: {promise}", LAYER3)
        assert not result["passed"] and any("refund" in p for p in result["problems"]), promise
    ok = ("Dear customer, your refund request for order 7002 (350.00 TND) needs approval from our finance team. "
          "Our finance team reviews the request and we reply with their decision.")
    assert check_reply(ok, LAYER3)["passed"]


def test_promise_allowed_when_the_decision_contains_it():
    d = {**REFUND, "action": "subscribe", "facts": {"event": "out_for_delivery"},
         "next_step": "You will get a notification when the parcel is out for delivery."}
    assert check_reply("Hi, order 7001 is set: we will notify you when it is out for delivery.", d)["passed"]


# --- templates ---------------------------------------------------------------

@pytest.mark.parametrize("outcome", ["approve", "send_back", "ask_user", "ask_proof", "layer3", "escalate", "info"])
def test_template_per_outcome_passes_the_check(outcome):
    for base in (REFUND, LAYER3):
        d = {**base, "outcome": outcome, "facts": {**base["facts"], "needed": "a photo of the box",
                                                    "promised_date": "2026-10-01", "carrier": "Aramex"}}
        reply = templates.render(d)
        assert check_reply(reply, d)["passed"], (outcome, reply, check_reply(reply, d))
        assert str(d["order_id"]) in reply


def test_template_for_subscription_and_unknown_outcome():
    sub = {"outcome": "approve", "action": "subscribe", "order_id": 4510, "facts": {"event": "out_for_delivery"},
           "next_step": "", "style": {}}
    assert "out for delivery" in templates.render(sub) and check_reply(templates.render(sub), sub)["passed"]
    odd = {**REFUND, "outcome": "something_new"}
    assert check_reply(templates.render(odd), odd)["passed"]


# --- writer flow (fake LLM) ----------------------------------------------------

class FakeLLM:
    """Returns the given replies in order and records what it was sent."""
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, role, messages, tools=None):
        self.calls.append({"role": role, "messages": messages, "tools": tools})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(content=reply, tool_calls=None)


def test_first_try_passes():
    fake = FakeLLM(GOOD)
    out = write_reply(REFUND, chat_fn=fake)
    assert out["reply"] == GOOD and out["attempts"] == 1 and out["used_template"] is False
    assert fake.calls[0]["role"] == "slm" and fake.calls[0]["tools"] is None   # the SLM gets no tools
    assert _steps()[-2:] == ["slm_call", "slm_check"]


def test_fail_then_retry_passes_and_retry_lists_the_problems():
    fake = FakeLLM("Hi, your refund of 99 TND is approved.", GOOD)
    out = write_reply(REFUND, chat_fn=fake)
    assert out["attempts"] == 2 and out["used_template"] is False and out["check"]["passed"]
    retry_prompt = fake.calls[1]["messages"][-1]["content"]
    assert "rejected" in retry_prompt and "99" in retry_prompt and "7001" in retry_prompt


def test_fail_twice_uses_the_template():
    fake = FakeLLM("We will keep you updated.", "Refund of 99 TND, we guarantee it.")
    out = write_reply(REFUND, chat_fn=fake)
    assert out["used_template"] is True and out["check"]["passed"] and out["reply"] == templates.render(REFUND)
    assert _steps()[-1] == "slm_template"


def test_model_down_uses_the_template_without_crashing():
    fake = FakeLLM(ConnectionError("Ollama is not running"), ConnectionError("still down"))
    out = write_reply(LAYER3, chat_fn=fake)
    assert out["used_template"] is True and out["check"]["passed"]
    assert "finance" in out["reply"] and "7002" in out["reply"]


# --- prompt and clean-up ----------------------------------------------------

def test_prompt_contains_only_the_decision_and_tone():
    msgs = build_messages(REFUND, history=[{"role": "user", "content": "WHERE IS MY MONEY"},
                                           {"role": "assistant", "content": "internal note 999"}])
    user = msgs[-1]["content"]
    assert "12.5" in user and "7001" in user and "The money goes back to your card." in user
    assert "R-REF-03" not in user                      # the rule id is not given to the SLM
    assert "Hi," in user and "upset" in user           # casual + calm opener for an angry client
    assert "WHERE IS MY MONEY" in user and "999" not in user   # only the client's messages, for tone


def test_clean_removes_signature_but_keeps_the_body():
    assert clean("Reply: \"Hi, order 1 ok.\"") == "Hi, order 1 ok."
    assert clean("Hi,\nOrder 1 ok.\nThank you.\nBest regards,\nShopNova Team") == "Hi, Order 1 ok. Thank you."
