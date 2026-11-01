"""RL1 tests: reply styles (short / apology_first / apology_next_step), the situation features, the default unchanged.

No Ollama and no API: the SLM is a fake. A style changes wording only: facts, must_say and the rule check stay the same.
"""

import hashlib
import json
from types import SimpleNamespace

import pytest

from callverse.learning.situation import FIELDS, situation
from callverse.slm import reply_styles, templates, writer
from callverse.slm.check import check_reply
from callverse.slm.reply_styles import FIXED_CLOSING, REPLY_STYLES
from callverse.slm.writer import build_messages, write_reply

NEUTRAL = {"formality": "neutral", "length": "medium", "shouting": False, "sentiment": "neutral", "emotion": "neutral"}
UPSET = {**NEUTRAL, "sentiment": "negative", "emotion": "anger"}
OPENER = "I'm sorry for the trouble."   # config.yaml slm.calm_openers.neutral

# One decision per outcome and company (texts as the Coordinators write them).
DECISIONS = {
    ("shopnova", "approve"): {
        "outcome": "approve", "action": "refund", "order_id": 4512, "rule_id": "R-REF-03",
        "facts": {"amount_tnd": 59.9, "days_late": 6, "order_status": "refunded"},
        "must_say": ["Your refund of 59.90 TND is approved."], "next_step": "Your order 4512 is now refunded."},
    ("shopnova", "decline"): {
        "outcome": "decline", "action": "refund", "order_id": 4509, "rule_id": "R-RET-01",
        "facts": {"order_status": "delivered", "days_since_delivery": 15},
        "must_say": ["Returns are possible within 14 days of delivery.",
                     "Order 4509 was delivered 15 days ago, so it can no longer be returned."], "next_step": ""},
    ("shopnova", "ask_proof"): {
        "outcome": "ask_proof", "action": "refund", "order_id": 4507, "rule_id": "R-DMG-01",
        "facts": {"order_status": "delivered"}, "must_say": ["Please send us a photo of the damage."], "next_step": ""},
    ("shopnova", "layer3_pending"): {
        "outcome": "layer3_pending", "action": "refund", "order_id": 4515, "rule_id": "R-ESC-01",
        "facts": {"amount_tnd": 378.0, "layer3_decision": "pending"},
        "must_say": ["Your refund of 378.00 TND for order 4515 needs approval from our finance team."],
        "next_step": "We will reply here as soon as it has been reviewed."},
    ("shopnova", "info"): {
        "outcome": "info", "action": "status", "order_id": 4510, "rule_id": None,
        "facts": {"order_status": "shipped", "days_late": 0, "promised_date": "2026-10-10", "carrier": "Aramex"},
        "must_say": ["Your order 4510 is on its way."], "next_step": ""},
    ("atlas", "approve"): {
        "company": "atlas", "case_word": "booking", "outcome": "approve", "action": "refund", "order_id": 7008,
        "booking_type": "flight", "rule_id": "AT-FLT-01",
        "facts": {"booking_status": "cancelled", "flight_status": "cancelled", "amount_tnd": 690.0},
        "must_say": ["Your refund of 690.00 TND for booking 7008 is approved."], "next_step": ""},
    ("atlas", "decline"): {
        "company": "atlas", "case_word": "booking", "outcome": "decline", "action": "compensation", "order_id": 7006,
        "booking_type": "flight", "rule_id": "AT-FLT-06", "facts": {"booking_status": "flown", "flight_status": "delayed"},
        "must_say": ["The flight of booking 7006 was delayed because of air traffic control.",
                     "This is an extraordinary cause, so no compensation is paid."],
        "next_step": "You can still cancel the trip for a full refund."},
    ("atlas", "ask_proof"): {
        "company": "atlas", "case_word": "booking", "outcome": "ask_proof", "action": "refund", "order_id": 7003,
        "booking_type": "hotel", "rule_id": "AT-HOT-02", "facts": {"booking_status": "confirmed", "needed": "a medical certificate"},
        "must_say": ["Please send us a medical certificate for booking 7003."], "next_step": ""},
    ("atlas", "layer3_pending"): {
        "company": "atlas", "case_word": "booking", "outcome": "layer3_pending", "action": "compensation", "order_id": 7004,
        "booking_type": "flight", "rule_id": "AT-FLT-03",
        "facts": {"booking_status": "flown", "flight_status": "delayed", "amount_tnd": 839.5, "layer3_decision": "pending"},
        "must_say": ["Your compensation of 839.50 TND for booking 7004 needs approval from our finance team."],
        "next_step": "We will reply here as soon as it has been reviewed."},
    ("atlas", "info"): {
        "company": "atlas", "case_word": "booking", "outcome": "info", "action": "status", "order_id": 7008,
        "booking_type": "flight", "rule_id": None, "facts": {"booking_status": "cancelled", "flight_status": "cancelled"},
        "must_say": ["Your flight booking 7008 is cancelled."], "next_step": ""},
}
CASES = list(DECISIONS)
ALL_STYLES = list(REPLY_STYLES)


def decision_for(key, reply_style=None, style=NEUTRAL):
    return {**DECISIONS[key], "style": style, "reply_style": reply_style}


def fake_slm(text):
    """A fake SLM that answers `text` (a body with the content; the writer's code parts are added around it)."""
    return lambda role, messages, **kw: SimpleNamespace(content=text, tool_calls=None)


def body_for(decision):
    """What a good small model writes: the must_say sentences (and the next step, as in the default prompt)."""
    return " ".join(list(decision["must_say"]) + ([decision["next_step"]] if decision["next_step"] else []))


def sentences(text):
    return [s for s in writer.SENTENCE_SPLIT_RE.split(text.strip()) if s]


# ---------- the style table ----------

def test_three_styles_exist_and_none_is_the_default():
    assert set(REPLY_STYLES) == {"short", "apology_first", "apology_next_step"}
    assert reply_styles.of({}) is None
    assert reply_styles.of({"reply_style": "short"}) == "short"


def test_unknown_style_is_an_error_not_a_silent_default():
    with pytest.raises(ValueError):
        reply_styles.of({"reply_style": "shouting"})


def test_env_var_and_decision_key(monkeypatch):
    monkeypatch.setenv("CALLVERSE_REPLY_STYLE", "apology_first")
    assert reply_styles.of({}) == "apology_first"
    assert reply_styles.of({"reply_style": "short"}) == "short"   # the decision wins over the env var


def test_config_default_is_null():
    from callverse.config import load_config
    assert load_config()["slm"]["reply_style"] is None


# ---------- each style, both companies, fake SLM ----------

@pytest.mark.parametrize("key", CASES)
@pytest.mark.parametrize("calm_client", [True, False])
def test_short_has_no_apology_and_keeps_the_must_say(key, calm_client):
    decision = decision_for(key, "short", style=NEUTRAL if calm_client else UPSET)
    out = write_reply(decision, chat_fn=fake_slm(body_for(decision)))
    assert OPENER not in out["reply"] and "sorry" not in out["reply"].lower()
    assert out["check"]["passed"]
    for item in decision["must_say"]:
        assert item.lower() in out["reply"].lower()


@pytest.mark.parametrize("key", CASES)
def test_apology_first_starts_with_the_opener_even_for_a_calm_client(key):
    decision = decision_for(key, "apology_first", style=NEUTRAL)
    out = write_reply(decision, chat_fn=fake_slm(body_for(decision)))
    assert out["reply"].startswith(OPENER)
    assert out["check"]["passed"]
    for item in decision["must_say"]:
        assert item.lower() in out["reply"].lower()


@pytest.mark.parametrize("key", CASES)
def test_apology_next_step_has_opener_and_a_closing_sentence_by_code(key):
    decision = decision_for(key, "apology_next_step", style=NEUTRAL)
    out = write_reply(decision, chat_fn=fake_slm(body_for(decision)))
    reply = out["reply"]
    assert reply.startswith(OPENER) and out["check"]["passed"]
    assert sentences(reply)[-1] == reply_styles.closing_for(decision)
    assert reply.lower().count(reply_styles.closing_for(decision).lower()) == 1   # said once
    for item in decision["must_say"]:
        assert item.lower() in reply.lower()


def test_closing_comes_from_next_step_then_the_request_then_the_fixed_line():
    assert reply_styles.closing_for(decision_for(("shopnova", "approve"))) == "Your order 4512 is now refunded."
    assert reply_styles.closing_for(decision_for(("shopnova", "ask_proof"))) == "Please send us a photo of the damage."
    assert reply_styles.closing_for(decision_for(("shopnova", "info"))) == FIXED_CLOSING
    assert reply_styles.closing_for(decision_for(("atlas", "decline"))) == "You can still cancel the trip for a full refund."


def test_fixed_closing_line_passes_the_rule_check_for_every_decision():
    for key in CASES:
        decision = decision_for(key, "apology_next_step")
        reply = templates.render(decision)
        assert check_reply(reply, decision)["passed"], (key, reply)


def test_the_model_is_told_not_to_write_the_closing_and_is_not_shown_the_next_step():
    decision = decision_for(("shopnova", "approve"), "apology_next_step")
    text = json.dumps(build_messages(decision))
    assert "added after your text automatically" in text
    assert "End with the next step" not in text
    assert json.loads(build_messages(decision)[1]["content"].split("(nothing else):\n")[1].split("\n\n")[0])["next_step"] == ""


def test_short_prompt_asks_for_45_words_and_no_apology():
    decision = decision_for(("shopnova", "approve"), "short", style=UPSET)
    text = build_messages(decision)[1]["content"]
    assert "at most 45 words" in text and "Do NOT apologise" in text
    assert "added before your text automatically" not in text   # upset client, but this style adds no opener


def test_short_template_is_short_for_every_decision():
    for key in CASES:
        reply = templates.render(decision_for(key, "short"))
        assert len(reply.split()) <= 45, (key, reply)
        assert "sorry" not in reply.lower()


def test_atlas_short_template_still_names_the_booking():
    decision = decision_for(("atlas", "info"), "short")
    assert check_reply(templates.render(decision), decision)["passed"]


# ---------- the template fallback matches the style ----------

@pytest.mark.parametrize("key", CASES)
@pytest.mark.parametrize("name", ALL_STYLES)
def test_template_fallback_matches_the_style(key, name):
    decision = decision_for(key, name)
    out = write_reply(decision)   # conftest: the SLM is offline, so the template answers
    reply = out["reply"]
    assert out["used_template"] and out["check"]["passed"]
    if name == "short":
        assert OPENER not in reply and len(reply.split()) <= 45
    else:
        assert reply.startswith(OPENER)
    if name == "apology_next_step":
        assert sentences(reply)[-1] == reply_styles.closing_for(decision)
    for item in decision["must_say"]:
        assert item.lower() in reply.lower()


def test_a_bad_model_reply_fails_the_check_and_falls_back_to_the_style_template():
    decision = decision_for(("shopnova", "approve"), "apology_next_step")
    out = write_reply(decision, chat_fn=fake_slm("We guarantee your money back within 24 hours."))
    assert out["used_template"] and out["attempts"] == writer.MAX_ATTEMPTS
    assert out["reply"].startswith(OPENER) and sentences(out["reply"])[-1] == "Your order 4512 is now refunded."


# ---------- the style never changes the content ----------

@pytest.mark.parametrize("key", CASES)
def test_facts_and_must_say_are_identical_across_styles(key):
    allowed = []
    for name in [None] + ALL_STYLES:
        decision = decision_for(key, name)
        messages = build_messages(decision)[1]["content"]
        allowed.append(json.loads(messages.split("(nothing else):\n")[1].split("\n\n")[0]))
    for a in allowed:
        assert a["facts"] == allowed[0]["facts"] and a["must_say"] == allowed[0]["must_say"]
        assert [k for k in a if k.endswith("_number")] == [k for k in allowed[0] if k.endswith("_number")]


def test_the_style_does_not_change_the_decision_dict():
    decision = decision_for(("shopnova", "approve"), "apology_next_step")
    before = json.dumps(decision, sort_keys=True)
    write_reply(decision, chat_fn=fake_slm(body_for(decision)))
    assert json.dumps(decision, sort_keys=True) == before


def test_redirect_ignores_the_reply_style():
    redirect = {"outcome": "info", "action": "redirect", "order_id": None, "rule_id": None, "facts": {},
                "must_say": ["I can help with your ShopNova orders: delivery, refunds, returns and damaged items."],
                "next_step": "If your question is about an order, please send us the order number.", "style": UPSET}
    plain = write_reply(redirect)["reply"]
    for name in ALL_STYLES:
        assert write_reply({**redirect, "reply_style": name})["reply"] == plain
    assert OPENER not in plain


# ---------- the default (no reply style) is today's writer ----------

def sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


@pytest.mark.parametrize("style", [NEUTRAL, UPSET, {**UPSET, "formality": "formal", "length": "short"}])
def test_default_prompt_and_template_do_not_depend_on_the_new_code(style):
    """With reply_style None (or missing) the messages and the template are what main produced:
    the pinned digest below was computed on main (eeece27) with the same decisions."""
    out = {}
    for key in CASES:
        d = {**DECISIONS[key], "style": style}
        out["|".join(key)] = [build_messages(d), templates.render(d), writer.polish(templates.render(d), d)]
        # the same with the key present and None
        assert out["|".join(key)] == [build_messages({**d, "reply_style": None}), templates.render({**d, "reply_style": None}),
                                      writer.polish(templates.render({**d, "reply_style": None}), d)]
    assert sha(out) == DEFAULT_DIGESTS[style["formality"], style["sentiment"]]


DEFAULT_DIGESTS = {   # computed on main (eeece27) with the same decisions and styles
    ("neutral", "neutral"): "d1455d4281c51bf9f8203b883c401796967740adb783ff1d91fabfd04effe1a5",
    ("neutral", "negative"): "607eb73da27c7fc1dddb560a7d0ce5d4e7fe5cbfa98be842c73d98671490033c",
    ("formal", "negative"): "22132878047651727c2365f05fc4f500630388d0ce07298097294f269c9d5924",
}


def test_default_opener_rule_is_unchanged():
    calm = {"outcome": "info", "action": "status", "order_id": 4510, "facts": {}, "must_say": ["Your order 4510 is on its way."],
            "next_step": "", "style": NEUTRAL}
    assert templates.decision_opener(calm) is None
    assert templates.decision_opener({**calm, "style": UPSET}) == OPENER


# ---------- situation ----------

TICKET = {"ticket_id": "T-1", "company": "shopnova", "main_reason": "refund_request", "emotion": {"label": "anger", "score": 0.9},
          "sentiment": {"label": "negative", "score": 0.8}, "priority_label": "high", "facts": {"days_late": 6, "paid": 59.9}}


def test_situation_has_exactly_the_spec_fields():
    s = situation(TICKET, DECISIONS[("shopnova", "approve")])
    assert list(s) == list(FIELDS)
    assert s == {"company": "shopnova", "reason": "refund_request", "outcome": "approve", "action": "refund",
                 "rule_id": "R-REF-03", "emotion": "anger", "sentiment": "negative", "priority": "high", "days_late": 6}


def test_situation_atlas_and_missing_fields():
    s = situation({"company": "atlas", "main_reason": "cancellation"}, DECISIONS[("atlas", "decline")])
    assert s["company"] == "atlas" and s["days_late"] is None and s["emotion"] is None and s["priority"] is None
    assert list(s) == list(FIELDS)
    assert situation({}, {})["company"] == "shopnova"   # no company = ShopNova


def test_situation_takes_days_late_from_the_decision_if_the_ticket_has_none():
    s = situation({"main_reason": "late_delivery"}, {"outcome": "info", "action": "status", "facts": {"days_late": 3}})
    assert s["days_late"] == 3


def test_situation_does_not_change_its_inputs():
    ticket, decision = json.loads(json.dumps(TICKET)), json.loads(json.dumps(DECISIONS[("shopnova", "approve")]))
    situation(ticket, decision)
    assert ticket == TICKET and decision == DECISIONS[("shopnova", "approve")]
