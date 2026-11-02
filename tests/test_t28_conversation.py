"""T28 tests (step 09): conversation memory inside one ticket, the pending question with a bare "yes" / "no", and one
decision per message. Design: docs/step09_design.md.

No API call: the agents get a fake LLM, the SLM is offline (conftest), the quota check is replaced. The messages are
written for these tests (Claude-written practice messages, not from any held-out or locked test set).
"""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from callverse.channels import conversation, web_chat
from callverse.coordinator import atlas_coordinator, coordinator
from callverse.coordinator.negation import negated_request, question_flags, yes_confirmation
from callverse.kb import search
from callverse.tickets import store
from callverse.tools.registry import run_tool


@pytest.fixture(autouse=True)
def tickets_db(tmp_path, monkeypatch):
    """A fresh tickets database per test; Agent B's quota is "there"; the rule search returns R-REF-03."""
    store.use_db(tmp_path / "callverse_t28.db")
    monkeypatch.setattr(web_chat, "agent_b_ready", lambda: True)
    monkeypatch.setattr(search, "search_policy",
                        lambda query, k=3: [{"id": "R-REF-03", "title": "", "text": "", "score": 1.0}])
    yield
    store.use_db(store.DEFAULT_DB_PATH)


def tool_call_reply(name, arguments, call_id="call_1"):
    tool_call = SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))
    return SimpleNamespace(content=None, tool_calls=[tool_call])


def text_reply(text):
    return SimpleNamespace(content=text, tool_calls=None)


PROPOSAL = {"order_id": 4512, "amount": 59.90, "rule_id": "R-REF-03",
            "facts_used": {"days_late": 6, "delivered": False, "paid": 59.90, "refunded_total": 0.0}}


def b_llm(user_confirmed, quote=""):
    """Fake LLM: Agent B reads order 4512, searches the rules and proposes 59.90 TND under R-REF-03."""
    steps = iter([tool_call_reply("get_order", {"order_id": 4512}),
                  tool_call_reply("search_policy", {"query": "refund for a late order"}),
                  tool_call_reply("propose_refund", {**PROPOSAL, "user_confirmed": user_confirmed,
                                                     "user_quote": quote})])

    def fake(role_key, messages, tools=None):
        if messages[0]["content"].startswith("You are Agent A"):
            return text_reply("I pass this to my colleague. [HANDOVER: B]")
        return next(steps, None) or text_reply("Sent for checking.")
    return fake


def any_text_llm(role_key, messages, tools=None):
    """Every model call answers with a short text (no tool call, no proposal)."""
    return text_reply("How can I help you with your order?")


def no_llm(role_key, messages, tools=None):
    raise AssertionError("no LLM call expected")


def refunded(order_id):
    return run_tool("B", "get_refunds", {"order_id": order_id})["refunded_total"]


def ask_first(text="My order 4512 is late, I want my money back.", user_confirmed=False):
    """Message 1: B proposes, the Coordinator asks "Please confirm ..." (the model said user_confirmed false)."""
    out = web_chat.send(1, "shopnova", text, chat_fn=b_llm(user_confirmed, text))
    assert out["outcome"] == "ask_user" and "Please confirm" in out["reply"], out
    return out


# ---------- the word lists and the flags ----------

def test_bare_answer_only_for_a_whole_yes_or_no():
    assert [conversation.bare_answer(t) for t in ("Yes!", "yes please", "OK", "Go ahead.", "confirm")] == ["yes"] * 5
    assert [conversation.bare_answer(t) for t in ("No thanks.", "never mind", "Cancel")] == ["no"] * 3
    assert [conversation.bare_answer(t) for t in ("yes, refund order 4512", "no, where is it?", "")] == [None] * 3


def test_no_refund_please_is_negative_but_complaints_stay_requests():
    for t in ("no refund please", "No refund needed, just tell me where it is", "no refund, thanks"):
        assert negated_request(t), t
    for t in ("still no refund please help", "I got no refund", "no refund yet", "I want a refund"):
        assert not negated_request(t), t


def test_yes_confirms_a_refund_only_with_money_back_words_in_the_first_message():
    assert yes_confirmation("refund", question_flags("Order 4512 is late, I want my money back."))[0]
    assert not yes_confirmation("refund", question_flags("order 4512 is a week late, help"))[0]   # TWCS style
    assert not yes_confirmation("refund", question_flags("No refund please, just send it."))[0]
    assert not yes_confirmation("cancel", question_flags("please cancel this payment"))[0]
    assert yes_confirmation("cancel", question_flags("Please cancel my order 4511."))[0]
    assert not yes_confirmation("promotion", {"money_back": True})[0]


def test_atlas_yes_still_needs_the_right_reason_for_the_action():
    flags = question_flags("Please refund my booking 7008.")
    case = {"main_reason": "compensation", "yes_answer": flags, "user_message": "yes"}
    assert not atlas_coordinator.confirmation({"action": "refund", "user_quote": "yes"}, case)[0]
    case["main_reason"] = "refund_request"
    assert atlas_coordinator.confirmation({"action": "refund", "user_quote": "yes"}, case)[0]


def test_shopnova_review_with_a_yes_and_no_money_words_asks_again():
    case = coordinator.new_case("T-x")
    case.update(order_id=4512, main_reason="late_delivery", user_message="yes",
                yes_answer=question_flags("order 4512 is a week late, help"))
    decision = coordinator.review({"agent": "B", "action": "refund", "params": {"order_id": 4512, "amount": 59.90},
                                   "rule_id": "R-REF-03", "facts_used": {}, "user_confirmed": True,
                                   "user_quote": "yes"}, case)
    assert decision["outcome"] == "ask_user" and refunded(4512) == 0


# ---------- several requests in one message ----------

def test_split_refund_4512_and_where_is_4511():
    parts = conversation.split_requests("Please refund order 4512, it arrived broken, and where is order 4511?",
                                        "shopnova")
    assert [(p["order_id"], p["money"]) for p in parts] == [(4512, True), (4511, False)]
    assert conversation.main_part(parts)["order_id"] == 4512
    assert "broken" in parts[0]["text"]


def test_split_puts_the_money_part_first_and_ignores_amounts_and_one_id():
    parts = conversation.split_requests("Where is order 4509? Also I want a refund for 4512.", "shopnova")
    assert conversation.main_part(parts)["order_id"] == 4512
    assert conversation.split_requests("Where is order 4512? I paid 1500 TND", "shopnova") == []
    assert conversation.split_requests("Order 4512, order #4512 again", "shopnova") == []


def test_two_requests_one_decision_and_the_status_of_the_other():
    text = "Please refund order 4512, it is very late, and where is order 4509?"
    out = web_chat.send(1, "shopnova", text, chat_fn=b_llm(True, "Please refund order 4512"))
    assert out["outcome"] == "approve" and refunded(4512) == 59.90
    assert out["reply"].endswith("Order 4509 is delivered.")
    assert refunded(4509) == 0
    assert store.messages(out["ticket_id"])[0]["text"] == text            # the whole message is kept


def test_two_money_requests_one_write_and_the_fixed_sentence_last():
    out = web_chat.send(1, "shopnova", "I want a refund for 4512 and a refund for order 4509 too.",
                        chat_fn=b_llm(True, "I want a refund for 4512"))
    assert out["outcome"] == "approve" and refunded(4512) == 59.90 and refunded(4509) == 0
    assert out["reply"].endswith(conversation.ONE_DECISION_SENTENCE.format(word="order", order_id=4509))


def test_other_users_order_in_a_two_request_message_is_not_shown():
    out = web_chat.send(1, "shopnova", "Refund order 4512 please and where is order 4511?",
                        chat_fn=b_llm(True, "Refund order 4512 please"))
    assert out["reply"].endswith("Order 4511 is not on your account.")
    assert "being prepared" not in out["reply"]                         # 4511's status is not told


# ---------- the earlier id (memory a) ----------

def test_earlier_order_id_from_the_users_own_messages_only():
    t = store.create_ticket("shopnova", 1)
    store.add_message(t["id"], "user", "Where is my order 4512?")
    store.add_message(t["id"], "assistant", "Order 4509 is delivered.")   # an assistant text is never read
    mid = store.add_message(t["id"], "user", "And what about it?")
    assert conversation.earlier_order_id(t["id"], "shopnova", mid) == 4512
    assert conversation.refers_back("and what about it?") and not conversation.refers_back("hello")


def test_follow_up_without_id_uses_the_earlier_order(monkeypatch):
    first = web_chat.send(1, "shopnova", "Where is my order 4512?", chat_fn=any_text_llm)
    seen = []
    real = web_chat.intake.process
    monkeypatch.setattr(web_chat.intake, "process", lambda text, **k: seen.append(text) or real(text, **k))
    web_chat.send(1, "shopnova", "and what about it?", ticket_id=first["ticket_id"], chat_fn=any_text_llm)
    assert seen == ["and what about it? (order 4512)"]
    assert "memory_order" in [s["data"].get("trace_step", s["step"]) for s in store.steps(first["ticket_id"])] or \
        any(s["step"] == "memory_order" for s in store.steps(first["ticket_id"]))


def test_earlier_id_of_another_user_is_never_used(monkeypatch):
    first = web_chat.send(1, "shopnova", "Where is order 4511?", chat_fn=no_llm)
    assert first["outcome"] == "not_your_order"
    seen = []
    real = web_chat.intake.process
    monkeypatch.setattr(web_chat.intake, "process", lambda text, **k: seen.append(text) or real(text, **k))
    web_chat.send(1, "shopnova", "and what about it?", ticket_id=first["ticket_id"], chat_fn=any_text_llm)
    assert seen == ["and what about it?"]                                # no "(order 4511)" added


# ---------- the pending question and a bare yes / no ----------

def test_ask_user_saves_one_open_question_with_its_flags():
    out = ask_first()
    question = store.open_pending_question(out["ticket_id"])
    assert question["asked_by"] == "B" and question["action"] == "refund" and question["order_id"] == 4512
    assert question["flags"]["money_back"] is True and question["proposal_id"].startswith("P-")
    assert out["status"] == "Waiting for user" and refunded(4512) == 0


def test_bare_yes_continues_the_proposal_through_the_coordinator_once():
    out = ask_first()
    yes = web_chat.send(1, "shopnova", "yes", ticket_id=out["ticket_id"], chat_fn=no_llm)   # no agent, no model
    assert yes["outcome"] == "approve" and yes["status"] == "Solved" and refunded(4512) == 59.90
    assert "Your refund of 59.90 TND is approved." in yes["reply"]
    assert store.open_pending_question(out["ticket_id"]) is None
    kinds = [s["step"] for s in store.steps(out["ticket_id"])]
    assert "memory" in kinds and "coordinator" in kinds and "write" in kinds


def test_double_yes_gives_one_write_only():
    out = ask_first()
    web_chat.send(1, "shopnova", "yes", ticket_id=out["ticket_id"], chat_fn=no_llm)
    again = web_chat.send(1, "shopnova", "yes", ticket_id=out["ticket_id"], chat_fn=any_text_llm)
    assert again["outcome"] != "approve" and refunded(4512) == 59.90


def test_bare_no_closes_the_question_and_writes_nothing():
    out = ask_first()
    no = web_chat.send(1, "shopnova", "no thanks", ticket_id=out["ticket_id"], chat_fn=no_llm)
    assert no["reply"] == conversation.CLOSED_REPLY and no["outcome"] == "closed_by_user"
    assert refunded(4512) == 0 and store.open_pending_question(out["ticket_id"]) is None


def test_expired_question_is_not_answered_by_yes():
    out = ask_first()
    question = store.open_pending_question(out["ticket_id"])
    later = datetime.fromisoformat(question["created_real"]) + timedelta(minutes=31)
    assert conversation.open_question(out["ticket_id"], 1, "shopnova", now=later) is None
    assert store.get_pending_question(question["id"])["status"] == "expired"
    web_chat.send(1, "shopnova", "yes", ticket_id=out["ticket_id"], chat_fn=any_text_llm)
    assert refunded(4512) == 0


def test_unrelated_message_clears_the_question():
    out = ask_first()
    question = store.open_pending_question(out["ticket_id"])
    web_chat.send(1, "shopnova", "Do you sell phones?", ticket_id=out["ticket_id"], chat_fn=any_text_llm)
    assert store.get_pending_question(question["id"])["status"] == "cleared"
    web_chat.send(1, "shopnova", "yes", ticket_id=out["ticket_id"], chat_fn=any_text_llm)
    assert refunded(4512) == 0


def test_wrong_user_cannot_use_the_question():
    out = ask_first()
    assert conversation.open_question(out["ticket_id"], 2, "shopnova") is None
    assert conversation.open_question(out["ticket_id"], 1, "atlas") is None
    other = web_chat.send(2, "shopnova", "yes", ticket_id=out["ticket_id"], chat_fn=any_text_llm)
    assert other["ticket_id"] != out["ticket_id"] and refunded(4512) == 0
    assert store.open_pending_question(out["ticket_id"]) is not None          # still Sara's, still open


def test_yes_without_money_words_in_the_first_message_asks_again():
    out = ask_first("My order 4512 is a week late, help.", user_confirmed=True)   # the model said yes; words missing
    assert store.open_pending_question(out["ticket_id"])["flags"]["money_back"] is False
    yes = web_chat.send(1, "shopnova", "yes", ticket_id=out["ticket_id"], chat_fn=no_llm)
    assert yes["outcome"] == "ask_user" and refunded(4512) == 0


def test_bare_yes_with_nothing_open_goes_the_normal_way():
    out = web_chat.send(1, "shopnova", "yes", chat_fn=any_text_llm)
    assert out["outcome"] != "approve" and refunded(4512) == 0
    assert not any(s["step"] == "memory" for s in store.steps(out["ticket_id"]))


# ---------- T14f follow-up: TWCS-style tweets (Claude-written drafts in the style of real support tweets) ----------
# Draft messages, written for this test only (not real tweets, not from a test set): a complaint without the client's
# own money-back words must never let a bare "yes" confirm a refund.
DRAFT_TWCS_NO_MONEY_WORDS = ["@ShopNova order 4512 still not here after a week. this is ridiculous",
                             "hey my package 4512 is stuck at the depot since monday?? help",
                             "@ShopNova worst delivery ever, order 4512, nobody answers",
                             "no refund please, I just want my order 4512 to arrive"]
DRAFT_TWCS_MONEY_WORDS = ["@ShopNova order 4512 never came. I want my money back",
                          "can i get a refund for 4512 pls, it's a week late",
                          "still no refund for order 4512 please help"]


@pytest.mark.parametrize("text", DRAFT_TWCS_NO_MONEY_WORDS)
def test_draft_twcs_tweets_without_money_words_never_confirm_a_refund_by_yes(text):
    assert not yes_confirmation("refund", question_flags(text))[0]


@pytest.mark.parametrize("text", DRAFT_TWCS_MONEY_WORDS)
def test_draft_twcs_tweets_with_money_words_let_a_yes_confirm(text):
    assert yes_confirmation("refund", question_flags(text))[0]


def test_a_year_or_an_unknown_number_is_not_a_second_request():
    # T28 regression find (practice a05, real TWCS tweet): "May 2018" was read as a second booking.
    assert conversation.split_requests("cxld confirmed May 2018 flights to Kos. Booking 7008.", "atlas") == []
    assert conversation.split_requests("Refund order 4512, my code is 98765.", "shopnova") == []
    parts = conversation.split_requests("Refund 4512 and where is 4509?", "shopnova")   # no order words, both exist
    assert [p["order_id"] for p in parts] == [4512, 4509]
