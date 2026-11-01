"""T14c tests: Atlas declines by code, the shared negation check, the R-DMG-01 proof flag, the damage word in Intake,
the off-topic fixed text, and the hidden data labels. No API call: fake LLMs, the SLM is offline (conftest: template).

The practice messages are read from tests/dev/t14c_practice_messages.json (a practice set, not held-out).
"""

import json
import re
import shutil
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest

from callverse.channels import approvals, web_chat
from callverse.coordinator import atlas_coordinator as gate
from callverse.coordinator import coordinator
from callverse.coordinator.coordinator import cancel_confirmed, new_case
from callverse.coordinator.negation import negated_request
from callverse.data import admin_reads, db
from callverse.data.atlas import db as atlas_db
from callverse.data.atlas import reads
from callverse.data.atlas.seed import seed as seed_atlas
from callverse.data.seed import seed
from callverse.intake import intake
from callverse.intake.reasons import says_damaged, split_sentences
from callverse.kb.policies import get_policy
from callverse.slm import templates, writer
from callverse.tickets import store
from callverse.tools import proposal_tools, registry

PRACTICE = {m["id"]: m for m in json.loads(open("tests/dev/t14c_practice_messages.json",
                                                encoding="utf-8").read())["messages"]}
STYLE = {"formality": "neutral", "length": "short", "shouting": False, "emotion": "neutral", "sentiment": "neutral"}


@pytest.fixture(scope="module")
def atlas_template(tmp_path_factory):
    return seed_atlas(tmp_path_factory.mktemp("atlas_template_t14c") / "atlas.db")


@pytest.fixture(autouse=True)
def fresh_center(tmp_path, atlas_template, monkeypatch):
    """A fresh atlas.db and tickets database per test; Agent B's quota is "there"."""
    shutil.copyfile(atlas_template, tmp_path / "atlas.db")
    atlas_db.use_db(tmp_path / "atlas.db")
    store.use_db(tmp_path / "callverse.db")
    monkeypatch.setattr(web_chat, "agent_b_ready", lambda: True)
    yield
    atlas_db.use_db(atlas_db.DEFAULT_DB_PATH)
    store.use_db(store.DEFAULT_DB_PATH)


@pytest.fixture
def queue(monkeypatch):
    monkeypatch.setenv("CALLVERSE_LAYER3_MODE", "queue")


def sql(statement: str, *params) -> list:
    with closing(atlas_db.connect()) as con:
        rows = con.execute(statement, params).fetchall()
        con.commit()
        return rows


def facts(booking_id: int) -> dict:
    return gate.read_facts(reads.booking_type(booking_id), booking_id)


# ---------- item 2: the shared negation check ----------

@pytest.mark.parametrize("sentence", [
    "I'm not able to cancel my order", "I am not getting the cancel option", "I can't cancel order 4511",
    "Unable to cancel it, please help", "How do I cancel this?", "I tried to cancel yesterday",
    "I am having problems cancelling", "the app won't let me cancel", "I was not refunded",
    "I have not been refunded yet", "I didn't get my refund", "didn't arrive so please cancel",
    "did not arrive so please cancel it", "My flight was not on time, I want compensation",
    "I do not have the cancel option", "Do not wait. Refund me now.", "Notify me and refund me."])
def test_a_request_is_not_a_negation(sentence):
    assert not negated_request(sentence)


@pytest.mark.parametrize("sentence", [
    "Please do not cancel my order", "I don't want to cancel", "I dont want a refund", "NEVER refund me",
    "please suggest do not want to return/refund Order 4509", "I should be rerouted NOT refunded",
    "I never asked for a refund", "I no longer want to cancel booking 7011", "I don’t need compensation",
    "I didn't ask for a refund", "It doesn't need a refund", "I am not asking for a refund"])
def test_a_negated_request_is_a_negation(sentence):
    assert negated_request(sentence)


@pytest.mark.parametrize("message_id", ["s03", "s05"])
def test_practice_cancel_troubles_are_requests(message_id):
    text = PRACTICE[message_id]["text"]
    assert not any(negated_request(s) for s in split_sentences(text))


@pytest.mark.parametrize("message_id", ["s04", "a05"])
def test_practice_negations_are_negations(message_id):
    assert any(negated_request(s) for s in split_sentences(PRACTICE[message_id]["text"]))


def test_shopnova_cancel_confirmation_uses_the_shared_check():
    text = PRACTICE["s03"]["text"]
    quote = "I am having problems canceling an order on the app"
    assert cancel_confirmed({"user_quote": quote}, {"main_reason": "cancel_order", "user_message": text})[0]
    s05 = PRACTICE["s05"]["text"]
    assert cancel_confirmed({"user_quote": "Need to cancel an order"}, {"main_reason": "cancel_order", "user_message": s05})[0]
    no = "Please do not cancel order 4511."
    assert cancel_confirmed({"user_quote": no}, {"main_reason": "cancel_order", "user_message": no}) == \
        (False, "negative sentence")


def test_atlas_confirmation_uses_the_shared_check():
    a05 = PRACTICE["a05"]["text"]
    assert not gate.client_confirmed({"user_quote": "I should be rerouted NOT refunded"},
                                     {"main_reason": "refund_request", "user_message": a05})
    late = "My flight was not on time, I want compensation."
    assert gate.client_confirmed({"user_quote": late}, {"main_reason": "compensation_request", "user_message": late})


def test_the_old_regexes_are_gone():
    assert not hasattr(coordinator, "NOT_CANCEL_RE") and not hasattr(gate, "NEGATIVE_WORDS")


# ---------- item 1: Atlas declines by code ----------

@pytest.mark.parametrize("reason, booking, rule", [
    ("compensation_request", 7007, "AT-FLT-03"),   # 1 h late at arrival
    ("compensation_request", 7008, "AT-FLT-06"),   # cancelled for weather
    ("compensation_request", 7006, "AT-FLT-06"),   # 5 h 18 late, air system
    ("compensation_request", 7004, None),          # 3 h 20 late, carrier: compensation is due
    ("compensation_request", 7005, None),          # cancelled the same day, carrier
    ("refund_request", 7007, "AT-FLT-04"),         # left 1 h late
    ("refund_request", 7006, None),                # left 5 h 30 late: AT-FLT-04 applies
    ("refund_request", 7005, None),                # cancelled: AT-FLT-01 applies
    ("refund_request", 7010, None),                # a future flight: no rule says no here
    ("refund_request", 7002, "AT-HOT-03"),         # non-refundable, cancelled
    ("cancellation", 7002, "AT-HOT-03"),           # already cancelled: the client asks for money
    ("cancellation", 7012, None),                  # confirmed: a real cancellation (T21)
    ("refund_request", 7012, "AT-HOT-03"),         # confirmed non-refundable, money asked
    ("refund_request", 7001, "AT-HOT-01"),         # no deposit
    ("refund_request", 7009, None),                # refundable, cancelled 5 days before: refund due
    ("refund_request", 7003, None),                # stayed, other room: AT-HOT-04 applies
    ("booking_status", 7007, None),                # no request: never a decline
    ("other", 7002, None),
])
def test_decline_rule_on_the_scripted_bookings(reason, booking, rule):
    assert gate.decline_rule(reason, facts(booking)) == rule


def test_decline_rule_on_changed_data():
    sql("UPDATE hotel_bookings SET cancelled_date = '2026-10-11' WHERE id = 7009")    # 1 day before arrival
    assert gate.decline_rule("refund_request", facts(7009)) == "AT-HOT-02"
    sql("UPDATE hotel_bookings SET status = 'no_show' WHERE id = 7011")
    assert gate.decline_rule("refund_request", facts(7011)) == "AT-HOT-05"
    sql("UPDATE flight_bookings SET notice_days = 20 WHERE id = 7005")                # told 20 days before
    assert gate.decline_rule("compensation_request", facts(7005)) == "AT-FLT-02"
    sql("UPDATE flights SET status = 'on_time', arrival_delay_min = 0, departure_delay_min = 0 WHERE id = 7004")
    assert gate.decline_rule("compensation_request", facts(7004)) == "AT-FLT-03"


def test_a_fully_refunded_booking_is_declined(queue):
    sql("INSERT INTO refunds (booking_type, booking_id, amount, status, rule_id, source, ai_generated, scripted) "
        "VALUES ('flight', 7005, 1500, 'completed', 'AT-FLT-01', 'scripted', 1, 1)")
    assert gate.decline_rule("refund_request", facts(7005)) == "AT-REF-01"
    must, _ = gate.decline_words("AT-REF-01", facts(7005), 7005)
    assert must == ["Booking 7005 has already been fully refunded (1500.00 TND), so no further refund is possible."]


def test_the_limits_are_the_rules_own():
    flt03, flt04, flt02 = (get_policy(r, "atlas") for r in ("AT-FLT-03", "AT-FLT-04", "AT-FLT-02"))
    assert "3 hours or more" in flt03["text"] and f"arrival_delay_min >= {gate.COMPENSATION_DELAY_MIN}" in flt03["condition"]
    assert "5 hours or more" in flt04["text"] and f"departure_delay_min >= {gate.REFUND_DELAY_MIN}" in flt04["condition"]
    assert "14 days or more" in flt02["text"] and f"notice_days < {gate.EARLY_NOTICE_DAYS}" in flt02["condition"]
    for cause in gate.EXTRAORDINARY_CAUSES:
        assert cause in get_policy("AT-FLT-06", "atlas")["condition"]


@pytest.mark.parametrize("rule, booking, expected", [
    ("AT-FLT-03", 7007, ["Compensation is paid when a flight arrives 3 hours or more late.",
                         "The flight of booking 7007 arrived 1 hour late, so no compensation is due."]),
    ("AT-FLT-06", 7008, ["The flight of booking 7008 was cancelled because of the weather.",
                         "This is an extraordinary cause, so no compensation is paid."]),
    ("AT-FLT-06", 7006, ["The flight of booking 7006 was delayed because of air traffic control.",
                         "This is an extraordinary cause, so no compensation is paid."]),
    ("AT-FLT-04", 7007, ["A full refund is possible when a flight leaves 5 hours or more late.",
                         "The flight of booking 7007 left 1 hour late, so it cannot be refunded."]),
    ("AT-HOT-03", 7002, ["Hotel booking 7002 is non-refundable, so it is not refunded after cancelling."]),
    ("AT-HOT-01", 7001, ["Hotel booking 7001 had no deposit: nothing was paid in advance, so there is nothing to refund."]),
])
def test_decline_sentences(rule, booking, expected):
    must, _ = gate.decline_words(rule, facts(booking), booking)
    assert must == expected


def test_decline_next_steps_say_what_is_still_possible():
    assert gate.decline_words("AT-FLT-06", facts(7008), 7008)[1] == "You can still choose a full refund or a new flight."
    assert gate.decline_words("AT-FLT-06", facts(7006), 7006)[1] == "You can still cancel the trip and get a full refund."
    assert gate.decline_words("AT-FLT-03", facts(7007), 7007)[1] == ""


@pytest.mark.parametrize("days, words", [(0, "on the day of arrival"), (1, "1 day before arrival"), (-2, "after the arrival date")])
def test_a_late_hotel_cancellation_never_says_0_days(days, words):
    must, _ = gate.decline_words("AT-HOT-02", {"days_before_arrival": days}, 7009)
    assert words in must[1] and "0 days" not in " ".join(must)


@pytest.mark.parametrize("minutes, words", [(60, "1 hour"), (150, "2 hours 30 minutes"), (45, "45 minutes")])
def test_duration_words(minutes, words):
    assert gate._duration(minutes) == words


def atlas_proposal(action, booking_type, booking_id, rule_id, quote):
    return proposal_tools.atlas_proposal("B", action, {"booking_type": booking_type, "booking_id": booking_id,
                                                       "rule_id": rule_id, "facts_used": {}, "user_confirmed": True,
                                                       "user_quote": quote})


def atlas_case(booking_type, booking_id, reason, message):
    return {**new_case("T-1"), "order_id": booking_id, "booking_type": booking_type, "main_reason": reason,
            "user_message": message}


def test_a_proposal_for_a_refused_request_is_declined_not_sent_back(queue):
    message = "Please send me the delay compensation. Booking 7007."
    decision = gate.review(atlas_proposal("compensation", "flight", 7007, "AT-FLT-03", message),
                           atlas_case("flight", 7007, "compensation_request", message))
    assert (decision["outcome"], decision["rule_id"]) == ("decline", "AT-FLT-03")
    assert decision["must_say"][1] == "The flight of booking 7007 arrived 1 hour late, so no compensation is due."
    from callverse.data.atlas import writes
    assert writes.get_proposal(decision["proposal_id"])["decision"] == "decline"
    assert not sql("SELECT * FROM compensations WHERE booking_id = 7007")


def test_a_compensation_that_is_due_still_waits_for_finance(queue):
    message = "What is the compensation for my 4 hour delay? Booking 7004."
    decision = gate.review(atlas_proposal("compensation", "flight", 7004, "AT-FLT-03", message),
                           atlas_case("flight", 7004, "compensation_request", message))
    assert decision["outcome"] == "layer3_pending" and decision["facts"]["amount_tnd"] == 839.50


def test_a_real_hotel_cancellation_is_not_declined():
    message = "I want my money back, please cancel booking 7012."
    decision = gate.review(atlas_proposal("cancel_hotel", "hotel", 7012, "AT-HOT-03", message),
                           atlas_case("hotel", 7012, "refund_request", message))
    assert decision["outcome"] == "approve"   # cancelled, nothing paid (T21), not a decline


def test_without_a_proposal_the_client_gets_the_decline():
    ticket = {"ticket_id": "T-1", "company": "atlas", "order_id": 7007, "main_reason": "compensation_request"}
    said = gate.said_to_user(ticket, None)
    assert (said["outcome"], said["rule_id"], said["action"]) == ("decline", "AT-FLT-03", "compensation")
    status = gate.said_to_user({**ticket, "main_reason": "booking_status"}, None)
    assert status["outcome"] == "info"


def test_the_decline_facts_hold_no_raw_numbers():
    decision = gate.decline_decision(7007, "compensation_request")
    assert decision["facts"] == {"booking_status": "flown", "flight_status": "delayed"}


def scripted_agent(*replies):
    """A fake agent LLM: these replies in order, then a plain text."""
    queue_ = iter(replies)

    def fake(role_key, messages, tools=None):
        return next(queue_, None) or SimpleNamespace(content="Checked.", tool_calls=None)
    return fake


def read_booking(booking_id):
    call = SimpleNamespace(id="c1", function=SimpleNamespace(name="get_flight_booking",
                                                            arguments=json.dumps({"booking_id": booking_id})))
    return SimpleNamespace(content=None, tool_calls=[call])


def test_the_channel_declines_a01_with_the_rule_in_the_reply(queue):
    m = PRACTICE["a01"]
    out = web_chat.send(m["user_id"], "atlas", m["text"], chat_fn=scripted_agent(read_booking(7007)))
    assert out["outcome"] == "decline" and out["status"] == "Solved"
    assert "arrived 1 hour late, so no compensation is due" in out["reply"]
    assert not store.approvals("pending") and not sql("SELECT * FROM compensations")


# ---------- item 1: the Atlas writer and its template ----------

def atlas_decline(style=STYLE):
    return {**gate.decline_decision(7008, "compensation_request"), "style": style}


def test_atlas_decline_has_its_own_writer_guide():
    text = writer.build_messages(atlas_decline())[1]["content"]
    assert writer.OUTCOME_GUIDE["decline_atlas"] in text
    shop = {"outcome": "decline", "action": "refund", "order_id": 4508, "rule_id": "R-RET-01", "facts": {},
            "must_say": ["Returns are possible within 14 days of delivery."], "next_step": "", "style": STYLE}
    assert writer.OUTCOME_GUIDE["decline"] in writer.build_messages(shop)[1]["content"]   # ShopNova unchanged


def test_atlas_decline_template_gives_the_reason_then_the_next_step():
    reply = writer.polish(templates.render(atlas_decline()), atlas_decline())
    reason = reply.index("because of the weather")
    assert reason < reply.index("You can still choose a full refund or a new flight.")
    assert writer.check_reply(reply, atlas_decline())["passed"]


def test_atlas_decline_without_the_slm_passes_the_check():
    out = writer.write_reply(atlas_decline())   # the SLM is offline in tests: the template
    assert out["used_template"] and out["check"]["passed"] and "booking 7008" in out["reply"]


def test_a_one_letter_first_word_is_lowered_after_the_greeting():
    assert writer.fix_punctuation("Hello, A full refund is possible.") == "Hello, a full refund is possible."
    assert writer.fix_punctuation("Hello, I can help.") == "Hello, I can help."


# ---------- item 6: off-topic = fixed text, no SLM call, both companies ----------

def never_called(*args, **kwargs):
    raise AssertionError("the SLM must not be called for the off-topic reply")


@pytest.mark.parametrize("company", ["shopnova", "atlas"])
def test_off_topic_is_a_fixed_text_without_the_slm(company):
    module = gate if company == "atlas" else coordinator
    decision = {**module.off_topic_decision(), "style": {**STYLE, "sentiment": "negative"}}
    out = writer.write_reply(decision, chat_fn=never_called)
    assert out["used_template"] and out["attempts"] == 0 and out["check"]["passed"]
    assert out["reply"].startswith("Hello, I can help with your") and "sorry" not in out["reply"].lower()


def test_atlas_off_topic_text():
    reply = writer.write_reply({**gate.off_topic_decision(), "style": STYLE}, chat_fn=never_called)["reply"]
    assert reply == ("Hello, I can help with your Atlas Travel bookings: flights, hotel stays, refunds and compensation. "
                     "If your question is about a booking, please send us the booking number.")


# ---------- item 3: the R-DMG-01 proof flag ----------

def damaged_refund(amount=350.0):
    return {"agent": "B", "action": "refund", "params": {"order_id": 4515, "amount": amount}, "rule_id": "R-DMG-01",
            "facts_used": {}, "user_confirmed": True, "user_quote": "it arrived broken"}


def test_the_proof_is_stored_with_the_proposal_and_reused_at_approval(queue):
    case = {**new_case("T-1"), "proof_received": True}
    decision = coordinator.review(damaged_refund(), case)
    assert decision["outcome"] == "layer3_pending"
    stored = admin_reads.proposal(decision["proposal_id"])
    assert stored["proof_received"] is True
    assert admin_reads.approval_facts(4515, decision["proposal_id"])["proof_received"] is True
    facts, problem = approvals.recheck(stored)
    assert problem is None and facts["proof_received"] is True


def test_without_the_proof_the_approval_recheck_fails():
    facts, problem = approvals.recheck({**damaged_refund(), "proof_received": False})
    assert problem and "R-DMG-01" in problem


def test_an_agent_cannot_set_the_proof_itself():
    decision = coordinator.review({**damaged_refund(), "proof_received": True}, new_case("T-1"))
    assert decision["outcome"] == "ask_proof"
    assert admin_reads.proposal(decision["proposal_id"])["proof_received"] is False


def test_an_old_database_gets_the_column_with_the_safe_default(tmp_path):
    old = tmp_path / "old_shopnova.db"
    seed(old)
    with closing(sqlite3.connect(old)) as con:
        con.execute("INSERT INTO proposals (id, agent, action, params, rule_id, facts_used, user_confirmed, created_at) "
                    "VALUES ('P-0001', 'B', 'refund', '{}', 'R-DMG-01', '{}', 1, '2026-10-09')")
        try:
            con.execute("ALTER TABLE proposals DROP COLUMN proof_received")   # make it look like a pre-T14c file
        except sqlite3.OperationalError:
            pytest.skip("this SQLite cannot drop a column")
        con.commit()
    db.use_db(old)
    assert admin_reads.proposal("P-0001")["proof_received"] is False


# ---------- item 5: a damaged item by the word ----------

@pytest.mark.parametrize("sentence, damaged", [
    ("had order damaged in transit, how do I sort out refunding / redelivery please?", True),
    ("Everything in the box was destroyed by a broken bottle of laundry detergent.", True),
    ("The screen was cracked when it arrived", True),
    ("The vase arrived smashed", True), ("It is defective", True),
    ("My parcel arrived, not damaged at all", False), ("It wasn't broken", False), ("no damaged items", False),
    ('The "Amazon Video Terms of Use" link is broken.', False), ("the app is broken", False),
    ("Where is my order?", False),
])
def test_says_damaged(sentence, damaged):
    assert says_damaged(sentence) is damaged


@pytest.mark.parametrize("text", [PRACTICE["s01"]["text"], PRACTICE["s02"]["text"],
                                  "had order damaged in transit, how do I sort out refunding / redelivery please? Order 4509."])
def test_intake_finds_the_damaged_item(text):
    assert intake.process(text, use_llm=False)["main_reason"] == "damaged_item"


def test_atlas_has_no_damaged_item_reason():
    ticket = intake.process("My suitcase was damaged on flight booking 7004.", use_llm=False, company="atlas")
    assert ticket["main_reason"] != "damaged_item"


def test_a_damaged_item_without_a_proposal_asks_for_a_photo(queue):
    m = PRACTICE["s01"]
    out = web_chat.send(m["user_id"], "shopnova", m["text"], chat_fn=scripted_agent())
    assert out["outcome"] == "ask_proof" and "Please send us a photo of the damage." in out["reply"]


# ---------- item 4: hidden data labels ----------

@pytest.mark.parametrize("agent, tool, args", [("A", "get_order", {"order_id": 4515}), ("B", "get_order", {"order_id": 4515}),
                                               ("B", "get_refunds", {"order_id": 4506}),
                                               ("A", "get_tracking", {"order_id": 4515})])
def test_agents_do_not_see_the_data_labels(agent, tool, args):
    result = json.dumps(registry.run_tool(agent, tool, args))
    assert not re.search(r'"(ai_generated|scripted)"', result)
