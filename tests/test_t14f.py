"""T14f tests. No API call (no LLM is used in these tests).

1. ShopNova: a refund (R-REF-03, R-DMG-01, R-RET-01) is approved only when a non-negative sentence of the client's
   message asks for money back in the client's own words (negation.money_back_asked, the same function as Atlas's
   T14e check). Otherwise the client is asked first and nothing is written. A cancellation keeps its own path.
2. Atlas: search_policy puts the rules of the ticket's booking type first (flight -> AT-FLT / AT-AST / AT-REF / AT-ESC,
   hotel -> AT-HOT / AT-REF / AT-ESC). The booking type is given by our code (registry), never by the model.

Sentences are synthetic (written for the tests), except t05, read from the T14d held-out set (dev material since T14e).
"""

import json

import pytest

from callverse.coordinator import atlas_coordinator, negation
from callverse.coordinator.coordinator import new_case, review
from callverse.tools import atlas_tools, registry
from callverse.tools.shopnova_tools import get_order, get_refunds

HELD = {m["id"]: m for m in json.loads(open("tests/data/t14d_heldout_messages.json", encoding="utf-8").read())["messages"]}


def refund(message_quote, order_id=4512, amount=59.90, rule_id="R-REF-03"):
    return {"agent": "B", "action": "refund", "params": {"order_id": order_id, "amount": amount},
            "rule_id": rule_id, "facts_used": {}, "user_confirmed": True, "user_quote": message_quote}


def case(message, reason="refund_request", order_id=4512):
    c = new_case("T14f")
    c.update(order_id=order_id, main_reason=reason, user_message=message)
    return c


# ---------- item 1: ShopNova refunds need the client's money-back words ----------

ASKS = [   # synthetic ShopNova messages that ask for money back
    "Order 4512 is a week late. I want my money back.",
    "My parcel 4512 never came, please refund me.",
    "Order 4512 is late again. Refund it please!",
    "Where is my order 4512? Just give me back... no, pay me back.",
    "I was promised delivery last week for 4512. Can I get a refund?",
    "Late again. I want a refund for order 4512",
    "Order 4512: still nothing. When will I be refunded?",
    "4512 is so late, I will do a chargeback if you do not pay me back.",
    "I am tired of waiting for order 4512. Send me back my money, I mean my money back.",
]
DOES_NOT_ASK = [   # synthetic ShopNova messages that do not ask for money back
    "Where is my order 4512?",
    "Order 4512 is late, what is going on?",
    "My order 4512 has not arrived yet. Help",
    "Can you tell me when 4512 will arrive?",
    "I do not want a refund, I just want my order 4512.",
    "Order 4512 is late. I never asked for a refund, just send it.",
    "The delivery of 4512 is a week late and nobody answers.",
    "I paid 59.90 TND for order 4512 and it is still not here.",
    "Is the item of order 4512 refundable?",
]


@pytest.mark.parametrize("message", ASKS)
def test_money_words_are_found(message):
    assert negation.money_back_asked(message)


@pytest.mark.parametrize("message", DOES_NOT_ASK)
def test_no_money_words_are_found(message):
    assert not negation.money_back_asked(message)


@pytest.mark.parametrize("message", ASKS)
def test_shopnova_refund_with_money_words_is_approved(message):
    d = review(refund("4512"), case(message))
    assert d["outcome"] == "approve"
    assert len(get_refunds(4512)["refunds"]) == 1


@pytest.mark.parametrize("message", DOES_NOT_ASK)
def test_shopnova_refund_without_money_words_asks_first(message):
    d = review(refund("4512"), case(message))
    assert d["outcome"] == "ask_user"
    assert d["must_say"] == ["Please confirm that you want a refund of 59.90 TND for order 4512."]
    assert get_refunds(4512)["refunds"] == [] and get_order(4512)["status"] != "refunded"   # nothing written


def test_shopnova_no_message_asks_first():
    """A case without the client's message has no words to read: ask first."""
    d = review(refund("4512"), new_case("T14f-empty"))
    assert d["outcome"] == "ask_user" and get_refunds(4512)["refunds"] == []


def test_agent_says_not_confirmed_still_asks_even_with_money_words():
    """The word check only adds a condition: the agent's "not confirmed" still asks first."""
    d = review({**refund("4512"), "user_confirmed": False}, case("I want my money back for 4512."))
    assert d["outcome"] == "ask_user" and get_refunds(4512)["refunds"] == []


def test_shopnova_damage_refund_needs_money_words_too():
    """R-DMG-01 after the photo: without money-back words, ask first."""
    c = case("Order 4507 arrived broken. Here is the photo.", reason="damaged_item", order_id=4507)
    c["proof_received"] = True
    d = review(refund("4507", order_id=4507, amount=10.0, rule_id="R-DMG-01"), c)
    assert d["outcome"] == "ask_user" and get_refunds(4507)["refunds"] == []
    c2 = case("Order 4507 arrived broken. Here is the photo, I want a refund.", reason="damaged_item", order_id=4507)
    c2["proof_received"] = True
    d2 = review(refund("4507", order_id=4507, amount=10.0, rule_id="R-DMG-01"), c2)
    assert d2["outcome"] == "approve" and len(get_refunds(4507)["refunds"]) == 1


def test_large_refund_without_money_words_never_reaches_layer3():
    """The word check runs before finance (Layer 3): no proposal is queued for a refund nobody asked for."""
    d = review(refund("4515", order_id=4515, amount=350.0), case("Where is my order 4515?", order_id=4515))
    assert d["outcome"] == "ask_user" and "layer3_decision" not in d.get("facts", {})


def test_shopnova_cancellation_keeps_its_own_path():
    """A cancellation (R-CAN-01) does not need money words: the cancel words decide (T14a / T14d)."""
    c = case("Please cancel my order 4511.", reason="cancel_order", order_id=4511)
    d = review({"agent": "B", "action": "cancel", "params": {"order_id": 4511}, "rule_id": "R-CAN-01",
                "facts_used": {}, "user_confirmed": True, "user_quote": "cancel my order 4511"}, c)
    assert d["outcome"] in ("approve", "layer3_pending", "decline")
    assert "money back" not in d.get("reason", "")


def test_atlas_uses_the_same_shared_function():
    assert atlas_coordinator.money_back_asked is negation.money_back_asked


# ---------- item 2: Atlas rule search by booking type ----------

T05 = HELD["t05"]["text"]


def ids(result):
    return [r["id"] for r in result["results"]]


def test_flight_booking_still_no_refund_finds_a_flight_rule_first():
    first = ids(atlas_tools.search_policy(T05, booking_type="flight"))[0]
    assert first.startswith(("AT-FLT-", "AT-AST-", "AT-REF-", "AT-ESC-"))


def test_hotel_booking_finds_a_hotel_rule_first():
    first = ids(atlas_tools.search_policy("I cancelled my stay and still no refund.", booking_type="hotel"))[0]
    assert first.startswith(("AT-HOT-", "AT-REF-", "AT-ESC-"))


def test_without_booking_type_the_search_is_by_meaning_only():
    """No booking named: the same results as before T14f (t05's query found hotel rules then)."""
    assert ids(atlas_tools.search_policy(T05)) == ids(atlas_tools.search.company_search_tool("atlas", T05))


def test_registry_sets_the_booking_type_not_the_model():
    """The model cannot pick the booking type: the registry replaces any argument it gives."""
    out = registry.run_tool("B", "search_policy", {"query": T05, "booking_type": "hotel"}, company="atlas",
                            booking_type="flight")
    assert ids(out)[0].startswith(("AT-FLT-", "AT-AST-", "AT-REF-", "AT-ESC-"))


def test_shopnova_search_is_unchanged():
    out = registry.run_tool("B", "search_policy", {"query": "my parcel is late, refund"}, company="shopnova",
                            booking_type="flight")
    assert out["results"] and all(r["id"].startswith("R-") for r in out["results"])


def test_prefer_first_keeps_the_score_order_inside_each_group():
    from callverse.kb.search import prefer_first
    rows = [{"id": "AT-HOT-03"}, {"id": "AT-FLT-02"}, {"id": "AT-HOT-02"}, {"id": "AT-FLT-01"}]
    assert [r["id"] for r in prefer_first(rows, ("AT-FLT-",))] == ["AT-FLT-02", "AT-FLT-01", "AT-HOT-03", "AT-HOT-02"]
    assert prefer_first(rows, None) == rows
