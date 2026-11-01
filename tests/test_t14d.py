"""T14d tests: a write must match what the client asked. No API call (no LLM is used in these tests).

1. ShopNova: money words are not an order cancellation (request_words.cancels_order, Intake + Coordinator).
2. Atlas: costs around the trip (hotel costs, meals, taxi, reimbursement) are a compensation question, and a ticket
   refund needs a money-back request (request_words.asks_for_expenses, atlas_coordinator ACTION_REASONS).
3. The runner counts an order-status change that `expect` does not allow as a wrong write.
4. Negation: "<thing> not refunded till date / yet / for 10 days" is a complaint, not a negation.

Sentences are synthetic (written for the tests), except the practice messages read from tests/dev and the T14c
held-out set, which T14d turns into dev material (h03, h04, h12).
"""

import json
import shutil

import pytest

from callverse.coordinator import atlas_coordinator as gate
from callverse.coordinator.coordinator import cancel_confirmed, new_case
from callverse.coordinator.negation import negated_request
from callverse.data.atlas import db as atlas_db
from callverse.data.atlas.seed import seed as seed_atlas
from callverse.intake import llm_fallback, reasons
from callverse.intake.request_words import asks_for_expenses, cancels_order
from callverse.tickets import store
from callverse.tools import proposal_tools
from scripts.run_t14c import status_wrong_write


def load(path: str) -> dict:
    return {m["id"]: m for m in json.loads(open(path, encoding="utf-8").read())["messages"]}


DEV = load("tests/data/t14c_heldout_messages.json")          # T14c held-out, dev material since T14d
PRACTICE = load("tests/dev/t14c_practice_messages.json")
DECLINE_PRACTICE = load("tests/dev/decline_practice_messages.json")


@pytest.fixture(scope="module")
def atlas_template(tmp_path_factory):
    return seed_atlas(tmp_path_factory.mktemp("atlas_template_t14d") / "atlas.db")


@pytest.fixture(autouse=True)
def fresh_center(tmp_path, atlas_template):
    shutil.copyfile(atlas_template, tmp_path / "atlas.db")
    atlas_db.use_db(tmp_path / "atlas.db")
    store.use_db(tmp_path / "callverse.db")
    yield
    atlas_db.use_db(atlas_db.DEFAULT_DB_PATH)
    store.use_db(store.DEFAULT_DB_PATH)


def main_reason(text: str, company: str) -> str | None:
    found = [r["reason"] for r in reasons.match_reasons(text, company=company)["reasons"]]
    order = {"shopnova": ["cancel_order", "refund_request"], "atlas": ["compensation_request", "refund_request"]}
    return next((r for r in order[company] if r in found), None)


# ---------- item 1: money words are not an order cancellation ----------

@pytest.mark.parametrize("sentence", [
    "Please cancel my order 4511.",
    "I need to cancel order #4514, I was charged twice for it.",       # the order is named: it wins over money words
    "Need to cancel an order. Unable to do so.",
    "my delivery didn't arrive yesterday so I need to cancel my order 4510",
    "cancel 4512 please",
    "I tap on cancel and nothing happens, please cancel my purchase",
])
def test_a_cancel_about_the_order_stays_a_cancellation(sentence):
    assert cancels_order(sentence, sentence)


@pytest.mark.parametrize("sentence, message", [
    ("Please cancel this payment Order 4514.", None),                    # the thing cancelled is money
    ("Can you cancel the charge on my Visa?", None),
    ("cancel my membership please", None),                               # T14a rule kept
    ("I pressed cancel by accident, how do I fix this?", None),          # a button pressed by accident
    ("Accidentally hit cancel at checkout.", None),
    ("Please cancel it.", "I see a $11 Prime charge on my statement. Please cancel it."),   # money talk, no order named
    ("Please cancel it ASAP.", "There is a payment I never made. Please cancel it ASAP."),
])
def test_a_cancel_about_money_or_a_button_is_not_an_order_cancellation(sentence, message):
    assert not cancels_order(sentence, message or sentence)


def test_h12_is_no_longer_an_order_cancellation():
    text = DEV["h12"]["text"]
    assert main_reason(text, "shopnova") != "cancel_order"
    assert not llm_fallback.cancel_is_justified(text)                    # the LLM fallback may not say it either


@pytest.mark.parametrize("text", [PRACTICE["s03"]["text"], PRACTICE["s05"]["text"], DECLINE_PRACTICE["t12"]["text"],
                                  "I am trying 2 cancel order I placed yesterday Order #4511 but I am not getting the "
                                  "cancel option on app. Pls help"])   # the shape of T14a's h08
def test_the_cancel_positive_paths_still_find_cancel_order(text):
    assert main_reason(text, "shopnova") == "cancel_order"


def test_the_coordinator_does_not_confirm_a_payment_cancel():
    text = DEV["h12"]["text"]
    case = {"main_reason": "cancel_order", "user_message": text}
    assert cancel_confirmed({"user_quote": "please cancel this payment Order 4514"}, case) == \
        (False, "the cancel is not about the order")
    ok = "Please cancel my order 4514."
    assert cancel_confirmed({"user_quote": ok}, {"main_reason": "cancel_order", "user_message": ok})[0]


# ---------- item 2: costs around the trip are not a ticket refund ----------

@pytest.mark.parametrize("sentence", [
    "I want reimbursement for my hotel stay after the cancelled flight.",
    "Who pays for the hotel? My flight was cancelled.",
    "Please cover my hotel costs and meals.",
    "Can I claim my taxi and food expenses?",
    "I had out of pocket costs, please compensate me for the hotel.",
])
def test_costs_around_the_trip_are_expenses(sentence):
    assert asks_for_expenses(sentence)


@pytest.mark.parametrize("sentence", [
    "Please refund my cancelled ticket. Booking 7008.",
    "Please reimburse my ticket, the flight was cancelled.",
    "Refund my hotel stay, booking 7001.",                                # the stay itself is the booking
    "I want my money back for the flight.",
])
def test_a_money_back_request_is_not_an_expense(sentence):
    assert not asks_for_expenses(sentence)


def test_h03_is_a_compensation_question_and_a_plain_refund_is_still_a_refund():
    assert main_reason(DEV["h03"]["text"], "atlas") == "compensation_request"
    assert main_reason("My flight was cancelled, please refund my ticket. Booking 7008.", "atlas") == "refund_request"


def atlas_proposal(action, booking_type, booking_id, rule_id, quote):
    return proposal_tools.atlas_proposal("B", action, {"booking_type": booking_type, "booking_id": booking_id,
                                                       "rule_id": rule_id, "facts_used": {}, "user_confirmed": True,
                                                       "user_quote": quote})


def atlas_case(booking_type, booking_id, reason, message):
    return {**new_case("T-1"), "order_id": booking_id, "booking_type": booking_type, "main_reason": reason,
            "user_message": message}


def refund_rows(booking_id: int) -> list:
    with atlas_db.connect() as con:
        return con.execute("SELECT * FROM refunds WHERE booking_id = ?", (booking_id,)).fetchall()


def test_a_ticket_refund_for_hotel_costs_gets_the_compensation_decline():
    """h03: the agent proposes the ticket refund (AT-FLT-01) for a hotel-costs question: the client gets the rule's no
    to what they asked (AT-FLT-06, weather), and nothing is written."""
    text = DEV["h03"]["text"]
    quote = "Hey I've emailed a couple times about reimbursement (hotel stay) for the cancelled VS20 flight last week"
    decision = gate.review(atlas_proposal("refund", "flight", 7008, "AT-FLT-01", quote),
                           atlas_case("flight", 7008, "compensation_request", text))
    assert (decision["outcome"], decision["rule_id"]) == ("decline", "AT-FLT-06")
    assert not refund_rows(7008)


def test_a_plain_ticket_refund_still_works():
    text = "My flight was cancelled, please refund my ticket. Booking 7008."
    decision = gate.review(atlas_proposal("refund", "flight", 7008, "AT-FLT-01", text),
                           atlas_case("flight", 7008, "refund_request", text))
    assert decision["outcome"] == "approve" and decision["facts"]["amount_tnd"] == 690.0
    assert len(refund_rows(7008)) == 1


@pytest.mark.parametrize("action, reason", [("refund", "compensation_request"), ("cancel_hotel", "compensation_request"),
                                            ("compensation", "cancellation")])
def test_the_action_must_match_the_request(action, reason):
    text = "Please help with booking 7008."
    confirmed, why = gate.confirmation({"action": action, "user_quote": text}, {"main_reason": reason, "user_message": text})
    assert not confirmed and why.startswith("the client asked for")


def test_a_refund_quote_about_expenses_is_not_confirmed():
    text = "My flight was cancelled, please refund my hotel costs. Booking 7008."
    confirmed, why = gate.confirmation({"action": "refund", "user_quote": text},
                                       {"main_reason": "refund_request", "user_message": text})
    assert not confirmed and "costs around the trip" in why


# ---------- item 3: the runner's order-status check ----------

def test_an_unexpected_order_status_change_is_a_wrong_write():
    problems = status_wrong_write(4514, "processing", "cancelled", {"order_status": "processing", "refund_rows": 0})
    assert problems and problems[0].startswith("WRONG WRITE: order 4514 status processing -> cancelled")
    assert status_wrong_write(4514, "processing", "cancelled", {})                           # no expect = no change
    assert not status_wrong_write(4511, "processing", "cancelled", {"order_status": "cancelled"})   # allowed
    assert not status_wrong_write(4510, "shipped", "shipped", {})                            # nothing changed
    assert not status_wrong_write(None, None, None, {})                                      # no order


# ---------- item 4: "not refunded till date" is a complaint ----------

@pytest.mark.parametrize("sentence", [
    "tickets cancelled 15 days back, amount not refunded till date, tried reaching support team",   # h04
    "money not returned yet",
    "deposit not refunded still, please help",
    "amount not credited for 10 days",
    "payment not refunded since last week",
    "my fare not refunded 2 weeks ago when you cancelled",
    "the ticket price not yet refunded",
    "amount not reimbursed until now",
])
def test_not_refunded_with_a_time_word_is_a_request(sentence):
    assert not negated_request(sentence)


@pytest.mark.parametrize("sentence", [
    "I should be rerouted NOT refunded",
    "I do not want to refund it",
    "I do not want to return the shoes",
    "please do not refund, rebook me",
    "not refunded, I want a voucher instead",
    "I never asked for a refund",
    "I do not want it refunded yet",
    "Please do not cancel order 4511.",
])
def test_a_real_negation_stays_a_negation(sentence):
    assert negated_request(sentence)
