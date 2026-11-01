"""T14e tests: an Atlas refund needs the client's own money-back words. No API call (no LLM is used in these tests).

1. request_words.asks_for_money_back: refund / money back / my money / pay me back / reimburse my ticket / chargeback.
2. atlas_coordinator: a refund is confirmed only when a non-negative sentence of the message has those words;
   otherwise the client is asked first and nothing is written (T14d held-out t02).
3. t05 ("still no refund"): the words count as money back and the sentence is not a negation.

Sentences are synthetic (written for the tests), except t02 and t05, read from the T14d held-out set
(dev material since T14e).
"""

import json
import shutil

import pytest

from callverse.coordinator import atlas_coordinator as gate
from callverse.coordinator.coordinator import new_case
from callverse.coordinator.negation import negated_request
from callverse.data.atlas import db as atlas_db
from callverse.data.atlas.seed import seed as seed_atlas
from callverse.intake.request_words import asks_for_money_back
from callverse.tickets import store
from callverse.tools import proposal_tools

HELD = {m["id"]: m for m in json.loads(open("tests/data/t14d_heldout_messages.json", encoding="utf-8").read())["messages"]}


@pytest.fixture(scope="module")
def atlas_template(tmp_path_factory):
    return seed_atlas(tmp_path_factory.mktemp("atlas_template_t14e") / "atlas.db")


@pytest.fixture(autouse=True)
def fresh_center(tmp_path, atlas_template):
    shutil.copyfile(atlas_template, tmp_path / "atlas.db")
    atlas_db.use_db(tmp_path / "atlas.db")
    store.use_db(tmp_path / "callverse.db")
    yield
    atlas_db.use_db(atlas_db.DEFAULT_DB_PATH)
    store.use_db(store.DEFAULT_DB_PATH)


# ---------- item 1: the money-back words ----------

ASKS = [
    "I want my money back",
    "refund me",
    "Please refund my ticket for booking 7008.",
    "Cancelled ticket 2 months back and still no refund.",
    "When will I be refunded?",
    "Can you pay me back for the flight?",
    "Please reimburse my ticket, the flight never left.",
    "I will file a chargeback with my bank.",
    "Where is our money? Booking 7003.",
    "I am still waiting for the refunds on booking 7005.",
    "They gave me a different room. I want something back.",
]
DOES_NOT_ASK = [
    "my flight was cancelled, help",
    "no confirmation from BA to the hotel",
    "My booking is non-refundable, is that right?",
    "What time does my flight leave tomorrow?",
    "The flight was delayed 6 hours and nobody told us anything.",
    "Please confirm my hotel booking 7004.",
    "I paid 690 TND for this ticket and the seat was broken.",
    "Can you check the status of booking 7008?",
    "The airline is useless, what now?",
]


@pytest.mark.parametrize("sentence", ASKS)
def test_money_back_words_are_found(sentence):
    assert asks_for_money_back(sentence)


@pytest.mark.parametrize("sentence", DOES_NOT_ASK)
def test_no_money_back_words(sentence):
    assert not asks_for_money_back(sentence)


# ---------- item 2: the Coordinator asks first without them ----------

def atlas_proposal(quote, booking_id=7008):
    return proposal_tools.atlas_proposal("B", "refund", {"booking_type": "flight", "booking_id": booking_id,
                                                         "rule_id": "AT-FLT-01", "facts_used": {}, "user_confirmed": True,
                                                         "user_quote": quote})


def atlas_case(message, reason="refund_request", booking_id=7008):
    return {**new_case("T-1"), "order_id": booking_id, "booking_type": "flight", "main_reason": reason,
            "user_message": message}


def refund_rows(booking_id: int) -> list:
    with atlas_db.connect() as con:
        return con.execute("SELECT * FROM refunds WHERE booking_id = ?", (booking_id,)).fetchall()


def test_t02_asks_first_and_writes_nothing():
    """t02: a cancelled flight and a hotel question, no money-back word: ask first, no 690 TND refund."""
    text = HELD["t02"]["text"]
    decision = gate.review(atlas_proposal(text), atlas_case(text))
    assert decision["outcome"] == "ask_user"
    assert decision["must_say"] == ["Please confirm that you want a refund of 690.00 TND for booking 7008."]
    assert not refund_rows(7008)


@pytest.mark.parametrize("message", ["My flight was cancelled, help. Booking 7008.",
                                     "Flight 7008 got cancelled. What are my options?",
                                     "My flight was cancelled. I did not ask for anything yet. Booking 7008."])
def test_no_money_words_asks_first(message):
    decision = gate.review(atlas_proposal(message.split(".")[0]), atlas_case(message))
    assert decision["outcome"] == "ask_user" and not refund_rows(7008)


@pytest.mark.parametrize("message", ["My flight was cancelled. I want my money back. Booking 7008.",
                                     "refund me, booking 7008 was cancelled",
                                     "Cancelled flight, booking 7008: please pay me back."])
def test_money_words_refund(message):
    decision = gate.review(atlas_proposal(message.split(".")[0]), atlas_case(message))
    assert decision["outcome"] == "approve" and len(refund_rows(7008)) == 1


def test_a_negative_money_sentence_does_not_count():
    """The only money words say NO: ask first."""
    text = "My flight 7008 was cancelled. I do not want a refund, I want another flight."
    confirmed, why = gate.confirmation({"action": "refund", "user_quote": "my flight 7008 was cancelled"},
                                       {"main_reason": "refund_request", "user_message": text})
    assert not confirmed and "money back" in why


def test_compensation_does_not_need_money_words():
    """Only a refund needs the words: a compensation keeps its own path (every one waits for finance anyway)."""
    text = "My flight was delayed 6 hours, I want compensation. Booking 7001."
    confirmed, _ = gate.confirmation({"action": "compensation", "user_quote": "I want compensation"},
                                     {"main_reason": "compensation_request", "user_message": text})
    assert confirmed


def test_hotel_cancellation_keeps_its_own_path():
    """T21: cancelling a confirmed hotel booking needs no money word ("cancel my booking" is the request)."""
    text = "Please cancel my hotel booking 7004."
    confirmed, _ = gate.confirmation({"action": "cancel_hotel", "user_quote": text},
                                     {"main_reason": "cancellation", "user_message": text})
    assert confirmed


# ---------- item 3: t05 ----------

def test_t05_still_no_refund_is_a_money_back_request():
    """t05 failed in the model (Agent B gave a text answer, no proposal), not in a rule: the words count and the
    sentence is not a negation, so a refund proposal for it is confirmed."""
    text = HELD["t05"]["text"]
    sentence = "Cancelled ticket 2 months back and still no refund."
    assert asks_for_money_back(sentence) and not negated_request(sentence)
    decision = gate.review(atlas_proposal(sentence), atlas_case(text))
    assert decision["outcome"] == "approve" and decision["facts"]["amount_tnd"] == 690.0
