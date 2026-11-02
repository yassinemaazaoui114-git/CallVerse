"""T29 step 1: more money-back words ("money returned to me", "reimbursed", "repay me", ...), for both companies.

Why? In the T28 live check the message "... If it can't arrive in time, I'd rather have the money returned to me."
asked for money back in plain words, but none of the T14e / T14f words were in it, so a later "yes" could not confirm
the refund. The new words are in request_words.asks_for_money_back; the negation check (negation.py) knows
"reimbursed" and "paid back" too, so "I do not want to be reimbursed" still writes nothing.
The example sentences are Claude-written drafts (not real messages, not held-out data).
"""

import json
from types import SimpleNamespace

import pytest

from callverse.channels import web_chat
from callverse.coordinator import atlas_coordinator
from callverse.coordinator.negation import money_back_asked, negated_request, question_flags, yes_confirmation
from callverse.intake.request_words import asks_for_expenses, asks_for_money_back
from callverse.kb import search
from callverse.tickets import store
from callverse.tools.registry import run_tool

T28_LIVE = ("Order 4512 is late and I need it tomorrow for a birthday. "
            "If it can't arrive in time, I'd rather have the money returned to me.")

# 12+ positives (drafts): each one asks for money back in the user's own words.
DRAFT_POSITIVES = [
    T28_LIVE,
    "I want my money returned.",
    "Please have the payment returned to me.",
    "I would like to be reimbursed for order 4512.",
    "I am asking for a reimbursement of what I paid.",
    "Can I be paid back for order 4511?",
    "I just want to get my money.",
    "I want the money refunded to my card.",
    "Please repay me the 59.90.",
    "The amount should be returned to me today.",
    "Returned to me, all the money I paid, that is what I want.",
    "Reimburse me please, booking 7008.",
]

# 8+ negatives and near misses (drafts): no money asked for, or asked for in the negative.
DRAFT_NEGATIVES = [
    "Please return the item.",
    "The courier returned my order.",
    "The parcel was returned to me yesterday.",
    "I do not want to be reimbursed, just send it.",
    "I don't need a reimbursement.",
    "This is a non-reimbursable fare, right?",
    "Can I return the shoes to the store?",
    "The box was returned to me damaged, where is my new one?",
    "I don't want to be paid back, I want the order.",
]


@pytest.mark.parametrize("text", DRAFT_POSITIVES)
def test_draft_money_back_words_count(text):
    assert asks_for_money_back(text), text
    assert money_back_asked(text), text


@pytest.mark.parametrize("text", DRAFT_NEGATIVES)
def test_draft_near_misses_and_negatives_do_not_count(text):
    assert not money_back_asked(text), text


def test_negation_knows_the_new_words():
    assert negated_request("i do not want to be reimbursed, just send it")
    assert negated_request("i don't want to be paid back")
    assert not negated_request("i would like to be reimbursed for order 4512")


def test_not_refunded_yet_stays_what_t14f_decided():
    # T14f/T28: a complaint that the refund did not come is a money-back request, not a negation.
    assert money_back_asked("I have not been refunded yet.") and not negated_request("I have not been refunded yet")


def test_a_bare_reimburse_at_atlas_is_still_a_cost_around_the_trip():
    # T14d (held-out h03) is kept: the Atlas Coordinator checks costs around the trip before the money-back words.
    assert asks_for_expenses("I want reimbursement for my hotel stay after the cancelled flight.")
    case = {"main_reason": "refund_request", "user_message": "I want reimbursement for my hotel stay."}
    assert not atlas_coordinator.confirmation(
        {"action": "refund", "user_quote": "I want reimbursement for my hotel stay"}, case)[0]


# ---------- Atlas path: the Coordinator's confirmation ----------

@pytest.mark.parametrize("message, quote", [
    ("Booking 7008 was cancelled. I'd rather have the money returned to me.", "the money returned to me"),
    ("Flight cancelled, booking 7008. I want to be reimbursed for booking 7008.", "reimbursed for booking 7008"),
    ("Booking 7008: can I be paid back?", "can i be paid back"),
])
def test_atlas_refund_is_confirmed_with_the_new_words(message, quote):
    case = {"main_reason": "refund_request", "user_message": message}
    assert atlas_coordinator.confirmation({"action": "refund", "user_quote": quote}, case)[0]


def test_atlas_negative_reimbursed_is_refused():
    message = "Booking 7008 was cancelled. I do not want to be reimbursed for booking 7008, rebook me."
    case = {"main_reason": "refund_request", "user_message": message}
    ok, reason = atlas_coordinator.confirmation(
        {"action": "refund", "user_quote": "i do not want to be reimbursed for booking 7008"}, case)
    assert not ok and reason == "negative sentence"


def test_atlas_yes_after_money_returned_confirms():
    flags = question_flags("Booking 7008 was cancelled. I'd rather have the money returned to me.")
    assert flags["money_back"] and yes_confirmation("refund", flags)[0]


# ---------- ShopNova path: the T28 live message, then a bare "yes" ----------

@pytest.fixture
def tickets_db(tmp_path, monkeypatch):
    store.use_db(tmp_path / "callverse_t29.db")
    monkeypatch.setattr(web_chat, "agent_b_ready", lambda: True)
    monkeypatch.setattr(search, "search_policy",
                        lambda query, k=3: [{"id": "R-REF-03", "title": "", "text": "", "score": 1.0}])
    yield
    store.use_db(store.DEFAULT_DB_PATH)


def _tool(name, arguments):
    call = SimpleNamespace(id="call_1", function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))
    return SimpleNamespace(content=None, tool_calls=[call])


def _text(text):
    return SimpleNamespace(content=text, tool_calls=None)


def _b_llm(quote):
    """Fake LLM: Agent B reads 4512, searches the rules, proposes 59.90 TND (the model is unsure: user_confirmed false)."""
    steps = iter([_tool("get_order", {"order_id": 4512}), _tool("search_policy", {"query": "late order refund"}),
                  _tool("propose_refund", {"order_id": 4512, "amount": 59.90, "rule_id": "R-REF-03",
                                           "facts_used": {"days_late": 6, "delivered": False, "paid": 59.90,
                                                          "refunded_total": 0.0},
                                           "user_confirmed": False, "user_quote": quote})])

    def fake(role_key, messages, tools=None):
        if messages[0]["content"].startswith("You are Agent A"):
            return _text("I pass this to my colleague. [HANDOVER: B]")
        return next(steps, None) or _text("Sent for checking.")
    return fake


def _no_llm(role_key, messages, tools=None):
    raise AssertionError("no LLM call expected")


def _any_text(role_key, messages, tools=None):
    return _text("How can I help you with your order?")


def _refunded():
    return run_tool("B", "get_refunds", {"order_id": 4512})["refunded_total"]


def test_t28_live_message_then_yes_writes_one_refund(tickets_db):
    first = web_chat.send(1, "shopnova", T28_LIVE, chat_fn=_b_llm("I'd rather have the money returned to me"))
    assert first["outcome"] == "ask_user", first
    assert store.open_pending_question(first["ticket_id"])["flags"]["money_back"] is True
    yes = web_chat.send(1, "shopnova", "yes", ticket_id=first["ticket_id"], chat_fn=_no_llm)
    assert yes["outcome"] == "approve" and _refunded() == 59.90
    again = web_chat.send(1, "shopnova", "yes", ticket_id=first["ticket_id"], chat_fn=_any_text)
    assert again["outcome"] != "approve" and _refunded() == 59.90          # double "yes" = one write
