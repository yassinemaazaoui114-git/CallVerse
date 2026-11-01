"""T14b tests: ShopNova reply-writer fixes, facts whitelist, language line, hidden fields, Intake fallback.

No API call: the SLM and the agents' LLM are fake functions (or offline, see conftest). Atlas is checked to be unchanged.
"""

import json
from types import SimpleNamespace

import pytest

from callverse.intake import language, llm_fallback
from callverse.slm import writer
from callverse.slm.check import check_reply
from callverse.slm.writer import (COMPANY_PROMPT, SYSTEM_PROMPT, build_messages, ensure_order_reference, polish,
                                  style_guide, writer_facts)
from callverse.tools import registry
from callverse.tools.shopnova_tools import get_order, get_refunds, get_user

STYLE = {"formality": "neutral", "length": "short", "shouting": False, "emotion": "neutral", "sentiment": "neutral"}
INFO = {"outcome": "info", "action": "status", "order_id": 4510, "rule_id": None,
        "facts": {"order_status": "shipped", "days_late": 0, "promised_date": "2026-10-10", "carrier": "Aramex"},
        "must_say": ["Your order 4510 is on its way."], "next_step": "", "style": STYLE}
ATLAS = {"outcome": "approve", "action": "cancel_hotel", "order_id": 7001, "rule_id": "AT-HTL-01", "company": "atlas",
         "case_word": "booking", "facts": {"amount_tnd": 120.0}, "must_say": [], "next_step": "", "style": STYLE}


def fake_slm(reply="Hello. Your order 4510 is on its way."):
    """A fake SLM that keeps the messages it was given."""
    seen = []

    def chat(role, messages):
        seen.append(messages)
        return SimpleNamespace(content=reply)

    chat.seen = seen
    return chat


def user_text(decision) -> str:
    return build_messages(decision)[1]["content"]


# ---------- step 2: no forced order sentence ----------

def test_shopnova_prompt_no_longer_forces_the_order_number_first():
    assert "FIRST sentence" not in SYSTEM_PROMPT
    assert "order 1234" not in SYSTEM_PROMPT and "order 7001" not in SYSTEM_PROMPT
    assert "<ORDER_NUMBER>" in SYSTEM_PROMPT
    assert "first sentence must contain" not in user_text(INFO)
    assert "Start directly with the content" not in user_text(INFO)   # only for an upset client


def test_upset_shopnova_client_is_not_told_to_start_with_the_order():
    upset = {**STYLE, "shouting": True}
    assert "Start directly with the content." in style_guide(upset, order_first=False)
    assert "Start directly with the order." in style_guide(upset)   # the default (Atlas) is unchanged
    assert "Start directly with the content." in user_text({**INFO, "style": upset})


def test_atlas_prompt_still_forces_the_booking_number():
    assert "booking 1234" in COMPANY_PROMPT and "FIRST sentence" in COMPANY_PROMPT
    text = user_text(ATLAS)
    assert 'Your first sentence must contain the exact words "booking 7001"' in text
    assert "Start directly with the order." in user_text({**ATLAS, "style": {**STYLE, "shouting": True}})


def test_shopnova_gets_no_order_sentence_by_code_but_atlas_does():
    assert ensure_order_reference("Your parcel is on its way.", INFO) == "Your parcel is on its way."
    atlas_reply = ensure_order_reference("Your stay is cancelled.", ATLAS)
    assert "About your booking 7001" in atlas_reply


def test_shopnova_reply_without_the_order_number_passes_a_wrong_number_fails():
    decision = {**INFO, "must_say": []}
    assert check_reply("Your parcel is on its way.", decision)["passed"]
    assert check_reply("Your order 4510 is on its way.", decision)["passed"]
    bad = check_reply("Your order 4511 is on its way.", decision)
    assert not bad["passed"] and any("wrong order number: 4511" in p for p in bad["problems"])
    assert not check_reply("Hello, order number 4510 and order #4511.", decision)["passed"]


def test_atlas_reply_must_still_mention_its_booking_number():
    problems = check_reply("Your stay is cancelled. The refund is 120.00 TND.", ATLAS)["problems"]
    assert any("is not mentioned" in p for p in problems)


def test_write_reply_keeps_a_good_reply_without_the_order_number():
    chat = fake_slm("Hello, your parcel is on its way.")
    out = writer.write_reply({**INFO, "must_say": [], "facts": {}}, chat_fn=chat)
    assert out["attempts"] == 1 and not out["used_template"]
    assert "4510" not in out["reply"]   # nothing was added by code


# ---------- step 2c: layer3_pending ----------

def test_layer3_pending_has_its_own_guide():
    decision = {"outcome": "layer3_pending", "action": "refund", "order_id": 4515, "rule_id": "R-ESC-01",
                "facts": {"amount_tnd": 350.0}, "next_step": "We will reply here as soon as it has been reviewed.",
                "must_say": ["Your refund of 350.00 TND for order 4515 needs approval from our finance team."],
                "style": STYLE}
    text = user_text(decision)
    assert "passed to the finance team" in text and "Say nothing about when" in text
    assert "Give the client the facts" not in text   # the "info" guide is no longer used for it


# ---------- step 3: facts whitelist ----------

def test_status_answer_hides_raw_order_details():
    # "shipped" is not in the sentence to copy ("on its way"), "0 days late", the date and the carrier are raw details
    assert writer_facts(INFO) == {}


def test_days_late_is_kept_only_when_positive_and_about_lateness():
    late = {**INFO, "facts": {"days_late": 3, "carrier": "Aramex"}}
    assert writer_facts(late) == {"days_late": 3}
    approve = {"outcome": "approve", "action": "refund", "rule_id": "R-REF-03", "order_id": 4512, "must_say": [],
               "next_step": "", "facts": {"amount_tnd": 59.9, "days_late": 6, "order_status": "stuck_at_depot"}}
    assert writer_facts(approve) == {"amount_tnd": 59.9, "days_late": 6}   # the raw status code is not shown
    other_rule = {**approve, "rule_id": "R-DMG-01", "action": "return"}
    assert "days_late" not in writer_facts(other_rule)
    decline = {"outcome": "decline", "action": "refund", "rule_id": "R-REF-03", "order_id": 4510, "next_step": "",
               "must_say": ["Order 4510 is on its way and is not late: it is due by 2026-10-10."],
               "facts": {"order_status": "shipped", "days_late": 0, "promised_date": "2026-10-10"}}
    assert writer_facts(decline) == {"promised_date": "2026-10-10"}   # in a sentence to copy; days_late 0 is hidden


def test_amounts_and_other_money_facts_stay():
    facts = {"amount_tnd": 350.0, "layer3_decision": "approved", "threshold_tnd": 300.0, "event": "out_for_delivery"}
    decision = {"outcome": "approve", "action": "refund", "order_id": 1, "must_say": [], "next_step": "", "facts": facts}
    assert writer_facts(decision) == facts


def test_the_writer_prompt_shows_only_the_whitelisted_facts():
    text = user_text(INFO)
    assert "promised_date" not in text and "Aramex" not in text and "days_late" not in text
    assert "Your order 4510 is on its way." in text   # the sentence to copy is still there


def test_atlas_facts_are_not_filtered():
    decision = {**ATLAS, "facts": {"amount_tnd": 120.0, "status": "confirmed", "hours_to_start": 100}}
    assert writer_facts(decision) == decision["facts"]


def test_the_atlas_writer_is_byte_identical_to_the_code_before_t14b():
    """Fingerprints taken with the writer of main (before T14b): the Atlas prompt and its messages (calm and upset)."""
    import hashlib

    def h(obj):
        return hashlib.sha256(json.dumps(obj, ensure_ascii=False).encode()).hexdigest()

    def decision(style):
        return {"outcome": "approve", "action": "cancel_hotel", "order_id": 7001, "rule_id": "AT-HTL-01",
                "company": "atlas", "case_word": "booking", "facts": {"amount_tnd": 120.0, "status": "confirmed",
                                                                       "hours_to_start": 100},
                "must_say": ["Your booking 7001 is cancelled."], "next_step": "The refund is on its way.", "style": style}

    assert hashlib.sha256(COMPANY_PROMPT.encode()).hexdigest() == "a916dc3a19d818c853ebd9b65862d3f32ff23d9eb4cc0b7f49a524105bf0520d"
    assert h(build_messages(decision(STYLE))) == "1f562207f35e5db28719b063acb30fe858403d019c682b50bff0cffef0d424a9"
    assert h(build_messages(decision({**STYLE, "shouting": True}))) == (
        "700da6c2c650cb9df3f488e00548e2affbf3c6e18d138b4ad2f9d329367c90d0")


def test_the_checker_still_knows_the_whole_decision():
    # The writer does not see promised_date, but a number that came from it is still "in the decision" for the checker.
    assert check_reply("Your order 4510 is on its way.", INFO)["passed"]


# ---------- step 4: language ----------

@pytest.mark.parametrize("text, code", [
    ("Bonjour, ma commande 4512 n'est toujours pas arrivée, je veux un remboursement", "fr"),
    ("Hola, mi pedido todavía no ha llegado y quiero un reembolso", "es"),
    ("Ciao, il mio ordine non è ancora arrivato", "it"),
    ("Hallo, meine Bestellung ist noch nicht angekommen", "de"),
    ("مرحبا طلبي لم يصل بعد", "ar"),
    ("Where is my order 4512?", "en"),
    ("plz refund order 4510", "en"),
    ("I FUCKING HATE YOU THIS IS THE THIRD TIME IN A ROW YOU ARE LATE", "en"),
    ("ok", "en"),
    ("", "en"),
    (None, "en"),
])
def test_language_detector(text, code):
    assert language.detect(text) == code


def test_intake_puts_the_language_on_the_ticket_and_the_reply_style():
    from callverse import pipeline
    from callverse.intake import intake
    ticket = intake.process("Bonjour, ma commande 4510 n'est toujours pas arrivée, où est mon colis ?", use_llm=False)
    assert ticket["language"] == "fr"
    assert pipeline.reply_style(ticket)["language"] == "fr"
    assert pipeline.reply_style({"ticket_id": "T-x"})["language"] == "en"   # a hand-made ticket


def test_language_line_in_the_prompt_for_french_and_not_for_english():
    french = {**INFO, "style": {**STYLE, "language": "fr"}}
    chat = fake_slm()
    writer.write_reply(french, chat_fn=chat)
    system, user = chat.seen[0][0]["content"], chat.seen[0][1]["content"]
    assert "write the reply in French" in user
    assert "Write in English" not in system

    for style in ({**STYLE, "language": "en"}, STYLE):
        chat = fake_slm()
        writer.write_reply({**INFO, "style": style}, chat_fn=chat)
        assert "writes in" not in chat.seen[0][1]["content"]
        assert "Write in English" in chat.seen[0][0]["content"]


def test_atlas_gets_no_language_line():
    chat = fake_slm("Your booking 7001 is cancelled. The refund is 120.00 TND.")
    writer.write_reply({**ATLAS, "style": {**STYLE, "language": "fr"}}, chat_fn=chat)
    assert "writes in" not in chat.seen[0][1]["content"]
    assert "Write in English" in chat.seen[0][0]["content"]


# ---------- step 5: hidden fields ----------

HIDDEN = ("source", "source_id", "city", "payment")


def keys_anywhere(value) -> set:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys_anywhere(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys_anywhere(v)}
    return set()


@pytest.mark.parametrize("agent, tool, args", [
    ("A", "get_order", {"order_id": 4510}), ("B", "get_order", {"order_id": 4510}),
    ("A", "get_user", {"user_id": 2}), ("A", "get_tracking", {"order_id": 4510}),
    ("B", "get_refunds", {"order_id": 4506}), ("INTAKE", "get_order", {"order_id": 4510}),
])
def test_agents_do_not_see_the_hidden_fields(agent, tool, args):
    result = registry.run_tool(agent, tool, args)
    assert "error" not in result
    assert not keys_anywhere(result) & set(HIDDEN)


def test_the_database_functions_still_return_the_hidden_fields():
    assert "payment" in get_order(4510) and "source" in get_order(4510)
    assert "source" in get_user(user_id=2)
    assert any("source" in row for row in get_refunds(4506)["refunds"])


def test_the_agents_still_see_the_useful_order_fields():
    order = registry.run_tool("A", "get_order", {"order_id": 4510})
    assert {"id", "status", "total", "paid", "promised_date", "carrier", "items"} <= set(order)


def test_ask_agent_answer_has_no_hidden_data_field():
    from callverse.agents import ask
    facts = ask.compact_facts([{"tool": "get_tracking", "result": registry.run_tool("A", "get_tracking", {"order_id": 4510})}])
    assert not set(facts) & {"source_id", "city", "payment"}


def test_atlas_tools_are_unchanged_by_the_registry_filter():
    from callverse.tools import atlas_tools
    direct = atlas_tools.FUNCTIONS["get_hotel_booking"](booking_id=7001)
    via_registry = registry.run_tool("A", "get_hotel_booking", {"booking_id": 7001}, company="atlas")
    assert via_registry == direct


# ---------- step 7: Intake fallback and the cancel word ----------

def answer(reasons, order_id=None):
    return lambda role, messages: SimpleNamespace(content=json.dumps({"reasons": reasons, "order_id": order_id}))


@pytest.mark.parametrize("text, reasons, expected", [
    ("Please stop order 4510 from shipping.", ["cancel_order"], ["other"]),
    ("Please stop order 4510 from shipping, I want my money.", ["cancel_order", "refund_request"], ["refund_request"]),
    ("Please cancel order 4510.", ["cancel_order"], ["cancel_order"]),
    ("Please cancle order 4510.", ["cancel_order"], ["cancel_order"]),
    ("I want to cancel my Prime subscription.", ["cancel_order"], ["other"]),
    ("Hi. I want to cancel my Prime subscription. Please cancel order 4510 too.", ["cancel_order"], ["cancel_order"]),
    ("Where is my parcel?", ["order_status"], ["order_status"]),
])
def test_fallback_accepts_cancel_order_only_with_the_cancel_word(text, reasons, expected):
    assert llm_fallback.classify(text, chat_fn=answer(reasons))["reasons"] == expected


def test_fallback_uses_the_same_regexes_as_reasons_py():
    from callverse.intake import reasons
    assert llm_fallback.CANCEL_WORD_RE is reasons.CANCEL_WORD_RE
    assert llm_fallback.NOT_AN_ORDER_RE is reasons.NOT_AN_ORDER_RE


def test_atlas_fallback_is_not_touched():
    result = llm_fallback.classify("Please stop my booking.", chat_fn=answer(["cancellation"]), company="atlas")
    assert result["reasons"] == ["cancellation"]


# ---------- step 6: off-topic opener ----------

from callverse.coordinator.coordinator import off_topic_decision   # noqa: E402
from callverse.slm.templates import render                          # noqa: E402

UPSET = {**STYLE, "sentiment": "negative", "shouting": True}


def test_shopnova_off_topic_reply_has_no_apology_opener():
    decision = {**off_topic_decision(), "style": UPSET}
    reply = render(decision)
    assert "sorry" not in reply.lower()
    assert "I can help with your ShopNova orders" in reply
    out = writer.write_reply(decision, chat_fn=fake_slm(
        "I'm so sorry. I can help with your ShopNova orders: delivery, refunds, returns and damaged items. "
        "If your question is about an order, please send us the order number."))
    assert "I'm sorry for the trouble." not in out["reply"]   # code adds no opener (the model's own words are kept)


def test_shopnova_off_topic_prompt_does_not_announce_an_opener():
    text = user_text({**off_topic_decision(), "style": UPSET})
    assert "an apology sentence is added" not in text


def test_an_upset_status_reply_still_gets_its_calm_opener():
    assert render({**INFO, "style": UPSET}).startswith("I'm sorry for the trouble.")


def test_atlas_off_topic_has_no_opener_since_t14c():
    # T14c (item 6): Atlas's redirect is the same fixed text as ShopNova's (no calm opener, no SLM call).
    from callverse.coordinator import atlas_coordinator
    decision = {**atlas_coordinator.off_topic_decision(), "style": UPSET, "company": "atlas"}
    assert render(decision).startswith("Hello, I can help with your Atlas Travel bookings")


def test_shopnova_off_topic_template_reads_naturally():
    reply = writer.polish(render({**off_topic_decision(), "style": UPSET}), off_topic_decision())
    assert reply == ("Hello, I can help with your ShopNova orders: delivery, refunds, returns and damaged items. "
                     "If your question is about an order, please send us the order number.")
    formal = render({**off_topic_decision(), "style": {**STYLE, "formality": "casual"}})
    assert formal.startswith("Hi, I can help")


def test_a_model_reply_that_changes_the_scope_sentence_falls_back_to_that_template():
    # The small model wrote "returns, and damaged items" (an extra comma): not word for word, so the template is used.
    chat = fake_slm("Hello, I can help with your ShopNova orders: delivery, refunds, returns, and damaged items. "
                    "If your question is about an order, please send us the order number.")
    out = writer.write_reply({**off_topic_decision(), "style": STYLE}, chat_fn=chat)
    assert out["used_template"] and out["reply"].startswith("Hello, I can help with your ShopNova orders")
