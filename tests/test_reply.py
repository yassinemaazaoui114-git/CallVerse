"""T08 tests: decision -> words for the user (Coordinator), info decisions, final reply by the SLM,
the writer's code fixes (punctuation, must_say once, formal greeting), rule_not_searched warning.

No API call and no Ollama: the SLM is a fake (or offline -> template, see conftest.py).
"""

import json
import re
from types import SimpleNamespace

import pytest

from callverse import pipeline, trace
from callverse.coordinator import coordinator
from callverse.coordinator.coordinator import for_user, info_decision, new_case, review, user_words
from callverse.kb import search
from callverse.slm.writer import finish, fix_punctuation, must_say_once, write_reply

LEAK_RE = re.compile(r"coordinator|agent|proposal|P-0|\bR-[A-Z]{0,3}-?\d|sent for checking", re.IGNORECASE)


def steps():
    return [json.loads(x)["step"] for x in trace.current_path().read_text(encoding="utf-8").splitlines()]


def text_reply(text):
    return SimpleNamespace(content=text, tool_calls=None)


def tool_call_reply(name, arguments):
    tc = SimpleNamespace(id="c1", function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))
    return SimpleNamespace(content=None, tool_calls=[tc])


# ---------- 1. decision -> user words (the T08 table) ----------

@pytest.mark.parametrize("outcome, action, rule, facts, must, next_step", [
    ("approve", "refund", "R-REF-03", {"amount_tnd": 59.9, "order_status": "refunded"},
     "Your refund of 59.90 TND is approved.", "Your order 4512 is now refunded."),
    # T17 F3: the status is said from the facts; if the order did not move, nothing is said about it
    ("approve", "refund", "R-REF-03", {"amount_tnd": 59.9, "order_status": "stuck_at_depot"},
     "Your refund of 59.90 TND is approved.", ""),
    ("approve", "refund", "R-RET-01", {"amount_tnd": 20.0}, "Your refund of 20.00 TND is approved.",
     "The refund is paid once we receive the returned item."),
    ("approve", "refund", "R-DMG-01", {"amount_tnd": 20.0}, "Your refund of 20.00 TND is approved.", ""),
    ("approve", "refund", "R-REF-03", {"amount_tnd": 378.0, "layer3_decision": "approved", "order_status": "refunded"},
     "Your refund of 378.00 TND is approved after a check by our finance team.", "Your order 4512 is now refunded."),
    ("layer3_refused", "refund", "R-REF-03", {"amount_tnd": 600.0},
     "We cannot approve a refund of 600.00 TND for order 4512.", "Our finance team reviewed it and did not approve it."),
    ("approve", "subscribe", "R-NOT-01", {"event": "out_for_delivery"},
     "You will get a message here when your order is out for delivery.", ""),
    ("ask_user", "refund", "R-REF-03", {"amount_tnd": 59.9},
     "Please confirm that you want a refund of 59.90 TND for order 4512.", ""),
    ("ask_proof", "refund", "R-DMG-01", {"amount_tnd": 20.0}, "Please send us a photo of the damage.", ""),
    ("escalate", "refund", "R-REF-03", {}, "Your case needs an extra check, so it has been passed on for review.", ""),
])
def test_user_words(outcome, action, rule, facts, must, next_step):
    assert user_words(outcome, action, rule, facts, 4512) == ([must], next_step)


def test_internal_outcomes_have_no_words_and_end_as_escalate():
    assert user_words("send_back", "refund", "R-REF-03", {"amount_tnd": 70.0}, 4512) == ([], "")
    d = review({"agent": "B", "action": "refund", "params": {"order_id": 4512, "amount": 70.0},
                "rule_id": "R-REF-03", "facts_used": {}, "user_confirmed": True}, new_case("T"))
    assert d["outcome"] == "send_back" and d["must_say"] == []
    said = for_user(d)
    assert said["outcome"] == "escalate" and said["must_say"][0].startswith("Your case needs an extra check")


# ---------- 2. info decisions ----------

def test_info_decision_from_tracking():
    d = info_decision(4510)
    assert d["outcome"] == "info" and d["proposal_id"] is None
    assert d["must_say"] == ["Your order 4510 is on its way."]
    assert d["facts"]["order_status"] == "shipped" and d["facts"]["days_late"] == 0 and d["next_step"] == ""


def test_info_decision_r_del_02_offers_the_message(monkeypatch):
    monkeypatch.setattr(coordinator, "get_tracking", lambda order_id: {
        "status": "shipped", "days_late": 3, "delivered": False, "promised_date": "2026-10-06", "carrier": "Aramex"})
    d = info_decision(4513)
    assert d["next_step"] == "If you like, we can send you a message when it is out for delivery."
    assert d["facts"]["carrier"] == "Aramex"


def test_info_decision_without_order():
    d = info_decision(None)
    assert d["order_id"] is None and "order number" in d["next_step"]


# ---------- 3. final reply in the pipeline ----------

TICKET = {"ticket_id": "T-R", "text": "Hi, where is my order 4510?", "order_id": 4510,
          "main_reason": "order_status", "priority_label": "low",
          "style": {"formality": "neutral", "length": "short", "shouting": False},
          "emotion": {"label": "neutral"}, "sentiment": {"label": "neutral"}}


def test_status_question_reply_comes_from_the_decision_not_the_agent():
    agent = lambda role_key, messages, tools=None: text_reply("The Coordinator says your proposal P-0001 is fine.")
    seen = []

    def slm(role_key, messages, tools=None):
        seen.append(messages[-1]["content"])
        return text_reply("Hello, your order 4510 is on its way.")

    out = pipeline.handle_ticket(TICKET, chat_fn=agent, slm_chat_fn=slm)
    assert out["reply_source"] == "slm" and "your order 4510 is on its way." in out["final_reply"].lower()
    assert not LEAK_RE.search(out["final_reply"])
    assert "Coordinator says" not in seen[0]          # the SLM never sees the agent's text
    assert "final_reply" in steps()


def test_ollama_down_gives_the_template_and_no_crash():
    agent = lambda role_key, messages, tools=None: text_reply("Your order is on its way.")
    out = pipeline.handle_ticket(TICKET, chat_fn=agent)        # SLM offline (conftest)
    assert out["reply_source"] == "template" and "4510" in out["final_reply"]


def test_s2_like_flow_gives_one_reply_after_the_approval(monkeypatch):
    monkeypatch.setattr(search, "search_policy", lambda q, k=3: [{"id": "R-REF-03", "title": "", "text": "", "score": 1}])
    args = {"order_id": 4512, "rule_id": "R-REF-03", "facts_used": {"days_late": 6}, "user_confirmed": True,
            "user_quote": "I want my money back."}

    def agent(role_key, messages, tools=None):
        last = messages[-1]
        if last["role"] == "user":
            amount = 59.90 if "sent back" in last["content"] else 70.00
            return tool_call_reply("propose_refund", {**args, "amount": amount})
        return text_reply("Sent for checking.")

    ticket = {**TICKET, "text": "Order 4512 is a week late. I want my money back.", "order_id": 4512,
              "main_reason": "refund_request"}
    out = pipeline.handle_ticket(ticket, chat_fn=agent)
    assert out["decision"]["outcome"] == "approve"
    assert out["final_reply"].count("Your refund of 59.90 TND is approved.") == 1
    assert "70" not in out["final_reply"] and not LEAK_RE.search(out["final_reply"])
    assert steps().count("final_reply") == 1


def test_rule_not_searched_is_a_warning_only():
    proposal = {"agent": "B", "action": "refund", "params": {"order_id": 4512, "amount": 59.9},
                "rule_id": "R-REF-03", "facts_used": {}, "user_confirmed": True}
    case = {**new_case("T-W"), "searched_rules": {"R-DEL-02"}}
    assert review(proposal, case)["outcome"] == "approve"        # not refused
    assert "rule_not_searched" in steps()


# ---------- 4. writer code fixes ----------

DECISION = {"outcome": "approve", "action": "refund", "order_id": 4512, "facts": {"amount_tnd": 59.9},
            "must_say": ["Your refund of 59.90 TND is approved."], "next_step": "Your order 4512 is now refunded.",
            "style": {"formality": "neutral", "length": "short", "shouting": False, "sentiment": "neutral"}}


def test_comma_capital_becomes_two_sentences_and_sentences_start_with_a_capital():
    assert fix_punctuation("About order 4512, Your refund is approved. the order is cancelled.") == \
        "About order 4512. Your refund is approved. The order is cancelled."
    assert fix_punctuation("Hi, Your refund is approved.") == "Hi, your refund is approved."
    assert fix_punctuation("Order 4512 is late, I am sorry.") == "Order 4512 is late, I am sorry."


def test_must_say_appears_once():
    text = "Your refund of 59.90 TND is approved. Order 4512: your refund of 59.90 TND is approved."
    assert must_say_once(text, DECISION).lower().count("your refund of 59.90 tnd is approved.") == 1


def test_formal_greeting_by_code_before_the_calm_opener():
    formal_upset = {**DECISION, "style": {"formality": "formal", "length": "short", "shouting": True,
                                          "sentiment": "negative"}}
    reply = finish("Hello, order 4512: Your refund of 59.90 TND is approved.", formal_upset)
    assert reply.startswith("Dear customer, please accept our apologies for the trouble.")
    template = write_reply(formal_upset)["reply"]                # SLM offline -> template, same fixes
    assert template.startswith("Dear customer,")
    casual = {**DECISION, "style": {"formality": "casual", "length": "short", "shouting": False}}
    assert not finish("Order 4512: your refund of 59.90 TND is approved.", casual).startswith("Dear customer")
