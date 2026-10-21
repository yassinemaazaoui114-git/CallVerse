"""T09 tests: story S3 (Agent A proposes a notification -> Coordinator -> clock -> notifier) and the
4 fixes from T08 (SLM warm-up, sign-off / shouted words, damaged item -> ask_proof, layer3_refused words).

No API call and no Ollama: agents and SLM are fakes, or the SLM is offline (template, see conftest.py).
"""

import json
from types import SimpleNamespace

from callverse import pipeline, trace
from callverse.agents.agent_a import AgentA
from callverse.coordinator.coordinator import proof_decision
from callverse.data import clock, reports
from callverse.notifier.notifier import notify_decision, run_notifier
from callverse.slm.check import check_reply
from callverse.slm.writer import clean, fix_punctuation, warm_up, write_reply
from callverse.tools.registry import ALLOW_LISTS, run_tool


def tool_call_reply(name, arguments):
    tc = SimpleNamespace(id="c1", function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))
    return SimpleNamespace(content=None, tool_calls=[tc])


def text_reply(text):
    return SimpleNamespace(content=text, tool_calls=None)


def steps():
    return [json.loads(x)["step"] for x in trace.current_path().read_text(encoding="utf-8").splitlines()]


TICKET = {"ticket_id": "T-S3", "text": "Hi, can you let me know when my order 4510 arrives?", "order_id": 4510,
          "main_reason": "order_status", "priority_label": "low",
          "style": {"formality": "neutral", "length": "short", "shouting": False},
          "emotion": {"label": "neutral"}, "sentiment": {"label": "neutral"}}


def agent_a_subscribes():
    """Fake Agent A: proposes subscribe(delivered) once, then answers."""
    replies = iter([tool_call_reply("propose_subscription", {"order_id": 4510, "event": "delivered",
                                                             "user_quote": "let me know when my order 4510 arrives"})])
    return lambda role_key, messages, tools=None: next(replies, text_reply("I asked for the message."))


# ---------- propose_subscription ----------

def test_propose_subscription_is_only_for_agent_a_and_validates():
    assert "propose_subscription" in ALLOW_LISTS["A"] and "propose_subscription" not in ALLOW_LISTS["B"]
    ok = run_tool("A", "propose_subscription", {"order_id": 4510, "event": "delivered", "user_quote": "tell me"})
    assert ok == {"status": "submitted to Coordinator"}
    assert "event must be one of" in run_tool("A", "propose_subscription",
                                              {"order_id": 4510, "event": "stuck_at_depot", "user_quote": "x"})["error"]
    assert "user_quote" in run_tool("A", "propose_subscription", {"order_id": 4510, "event": "delivered",
                                                                  "user_quote": ""})["error"]
    assert reports.list_rows("subscriptions") == []          # a proposal writes nothing


def test_agent_a_returns_the_subscribe_proposal():
    result = AgentA(chat_fn=agent_a_subscribes()).run("tell me when 4510 arrives")
    assert result["proposal"]["action"] == "subscribe" and result["proposal"]["rule_id"] == "R-NOT-01"
    assert result["proposal"]["params"] == {"order_id": 4510, "event": "delivered"}


# ---------- S3 end to end (fake agent, SLM offline -> template) ----------

def test_s3_subscribe_then_clock_then_one_message():
    clock.reset()
    out = pipeline.handle_ticket(TICKET, chat_fn=agent_a_subscribes())
    assert out["decision"]["outcome"] == "approve" and out["decision"]["action"] == "subscribe"
    assert "You will get a message here when your order is delivered." in out["final_reply"]
    subs = reports.list_rows("subscriptions")
    assert len(subs) == 1 and subs[0]["status"] == "waiting" and subs[0]["event"] == "delivered"

    clock.advance(24)                                  # 4510 out_for_delivery: not subscribed
    assert run_notifier() == []
    clock.advance(6)                                   # 4510 delivered
    sent = run_notifier()
    assert len(sent) == 1 and "Your order 4510 has been delivered." in sent[0]["text"]
    assert run_notifier() == []                        # never sent twice
    assert reports.list_rows("subscriptions")[0]["status"] == "sent"
    assert "notification_sent" in steps()


def test_handover_tag_does_not_replace_an_approved_notification():
    replies = iter([tool_call_reply("propose_subscription", {"order_id": 4510, "event": "delivered",
                                                             "user_quote": "let me know when it arrives"})])

    def agent(role_key, messages, tools=None):
        assert messages[0]["content"].startswith("You are Agent A"), "Agent B must not run"
        return next(replies, text_reply("Done. [HANDOVER: B]"))

    out = pipeline.handle_ticket(TICKET, chat_fn=agent)
    assert out["decision"]["outcome"] == "approve" and out["handover"] is None
    assert "handover_ignored" in steps()


def test_status_question_creates_no_subscription():
    agent = lambda role_key, messages, tools=None: text_reply("Your order 4510 is shipped.")
    out = pipeline.handle_ticket({**TICKET, "text": "Where is order 4510?"}, chat_fn=agent)
    assert out["decision"]["outcome"] == "info" and reports.list_rows("subscriptions") == []


def test_notify_decision_words():
    d = notify_decision({"order_id": 4510, "event": "out_for_delivery", "event_at": "2026-10-10"})
    assert d["outcome"] == "notify" and d["must_say"] == ["Your order 4510 is out for delivery."]
    reply = write_reply(d)["reply"]                    # SLM offline -> template
    assert check_reply(reply, d)["passed"] and "Your order 4510 is out for delivery." in reply


# ---------- the 4 fixes from T08 ----------

def test_warm_up_never_crashes():
    assert warm_up()["ok"] is False                    # Ollama off (conftest): warning only
    assert warm_up(chat_fn=lambda role_key, messages: text_reply("OK"))["ok"] is True
    assert steps().count("slm_warmup") == 2


def test_sign_off_and_shouted_words_are_removed():
    assert clean("Dear customer, your order 4510 is on its way. Kind regards") == \
        "Dear customer, your order 4510 is on its way."
    assert clean("Your order is on its way. Thanks, ShopNova") == "Your order is on its way."
    assert fix_punctuation("ORDER 4512 Your refund of 59.90 TND is approved. WHY IS IT LATE") == \
        "Order 4512: your refund of 59.90 TND is approved. Why is it late"
    assert fix_punctuation("I'm sorry. Order 4515 Your refund is approved.") == \
        "I'm sorry. Order 4515: your refund is approved."


def test_damaged_item_without_proposal_asks_for_a_photo():
    agent = lambda role_key, messages, tools=None: text_reply("Please send a photo.")
    ticket = {**TICKET, "text": "The speaker from order 4507 arrived broken", "order_id": 4507,
              "main_reason": "damaged_item"}
    out = pipeline.handle_ticket(ticket, chat_fn=agent)
    assert out["decision"]["outcome"] == "ask_proof" and out["decision"]["rule_id"] == "R-DMG-01"
    assert "Please send us a photo of the damage." in out["final_reply"]
    assert proof_decision(4507)["must_say"] == ["Please send us a photo of the damage."]


def test_must_say_keeps_its_exact_wording():
    from callverse.slm.writer import must_say_once
    d = {"must_say": ["Please send us a photo of the damage."]}
    assert must_say_once("Order 4507, please send us a photo of the damage.", d) == \
        "Order 4507. Please send us a photo of the damage."


def test_layer3_refused_reply_has_refusal_words_and_no_promise():
    d = {"outcome": "layer3_refused", "action": "refund", "order_id": 4515, "rule_id": "R-REF-03",
         "facts": {"amount_tnd": 600.0, "threshold_tnd": 300.0, "layer3_decision": "refused"},
         "must_say": ["We cannot approve a refund of 600.00 TND for order 4515."],
         "next_step": "Our finance team reviewed it and did not approve it.",
         "style": {"formality": "neutral", "length": "short", "shouting": False, "sentiment": "neutral"}}
    reply = write_reply(d)["reply"]                    # template path
    assert "We cannot approve a refund of 600.00 TND for order 4515." in reply
    assert check_reply(reply, d)["passed"]             # includes "no refund promise" for non-approve outcomes
    assert "we cannot approve this refund" in reply.lower()
