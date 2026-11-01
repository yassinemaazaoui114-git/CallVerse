"""RL1 / RL1b tests: reply styles (short / warm / warm_next_step), the situation features, the default unchanged.

No Ollama and no API: the SLM is a fake. A style changes wording only: facts, must_say and the rule check stay the same.
"""

import hashlib
import json
from types import SimpleNamespace

import pytest

from callverse.learning.situation import FIELDS, situation
from callverse.slm import reply_styles, templates, writer
from callverse.slm.reply_styles import REPLY_STYLES
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


EMPATHY = "Waiting without news about this is stressful."


def warm_body_for(decision):
    """What a good small model writes in a warm style: one empathy sentence, then the decision."""
    return f"{EMPATHY} {body_for(decision)}"


def greeting_of(reply):
    return writer.GREETING_RE.match(reply).group(0).strip()


# ---------- the style table ----------

def test_three_styles_exist_and_none_is_the_default():
    assert set(REPLY_STYLES) == {"short", "warm", "warm_next_step"}
    assert reply_styles.of({}) is None
    assert reply_styles.of({"reply_style": "short"}) == "short"


def test_the_rl1_names_are_gone():
    for old in ("apology_first", "apology_next_step"):
        with pytest.raises(ValueError):
            reply_styles.of({"reply_style": old})
    assert not hasattr(reply_styles, "FIXED_CLOSING")   # the RL1 generic line is removed


def test_unknown_style_is_an_error_not_a_silent_default():
    with pytest.raises(ValueError):
        reply_styles.of({"reply_style": "shouting"})


def test_env_var_and_decision_key(monkeypatch):
    monkeypatch.setenv("CALLVERSE_REPLY_STYLE", "warm")
    assert reply_styles.of({}) == "warm"
    assert reply_styles.of({"reply_style": "short"}) == "short"   # the decision wins over the env var


def test_config_default_is_null():
    from callverse.config import load_config
    assert load_config()["slm"]["reply_style"] is None


# ---------- the greeting: by code, the same for all 3 styles ----------

@pytest.mark.parametrize("key", CASES)
@pytest.mark.parametrize("formality, expected", [("formal", "Dear customer,"), ("neutral", "Hello,"), ("casual", "Hello,")])
def test_greeting_is_the_same_for_every_style(key, formality, expected):
    style = {**NEUTRAL, "formality": formality}
    for name in ALL_STYLES:
        decision = decision_for(key, name, style=style)
        body = body_for(decision) if name == "short" else warm_body_for(decision)
        out = write_reply(decision, chat_fn=fake_slm("Hi there, " + body))   # the model's own greeting is replaced
        assert out["check"]["passed"] and not out["used_template"], (name, out)
        assert out["reply"].startswith(expected + " ") and greeting_of(out["reply"]) == expected
        assert writer.polish(templates.render(decision), decision).startswith(expected + " ")   # the template too


def test_the_model_is_told_not_to_write_a_greeting():
    for name in ALL_STYLES:
        text = build_messages(decision_for(("shopnova", "approve"), name))[1]["content"]
        assert "Do NOT write a greeting" in text and "Start with exactly" not in text


# ---------- short ----------

@pytest.mark.parametrize("key", CASES)
@pytest.mark.parametrize("calm_client", [True, False])
def test_short_has_no_apology_and_no_empathy(key, calm_client):
    decision = decision_for(key, "short", style=NEUTRAL if calm_client else UPSET)
    out = write_reply(decision, chat_fn=fake_slm("I'm so sorry. " + warm_body_for(decision)))   # the model adds feelings anyway
    reply = out["reply"]
    assert out["check"]["passed"] and not out["used_template"]
    assert "sorry" not in reply.lower() and EMPATHY.lower() not in reply.lower() and OPENER not in reply
    for item in decision["must_say"]:
        assert item.lower() in reply.lower()


def test_short_prompt_asks_for_the_decision_only():
    text = build_messages(decision_for(("shopnova", "approve"), "short", style=UPSET))[1]["content"]
    assert "at most 45 words" in text and "Write ONLY the decision" in text and "Do NOT write a greeting, an apology" in text
    assert "added before your text automatically" not in text   # upset client, but this style adds no opener


def test_short_with_an_apology_left_fails_the_check():
    decision = decision_for(("shopnova", "info"), "short")
    assert writer.styled_problems("Hello, your order 4510 is on its way, sorry about that.", decision)


# ---------- warm: exactly one empathy sentence before the decision ----------

@pytest.mark.parametrize("key", CASES)
@pytest.mark.parametrize("name", ["warm", "warm_next_step"])
def test_warm_has_exactly_one_extra_sentence_before_the_decision(key, name):
    decision = decision_for(key, name)
    short = write_reply(decision_for(key, "short"), chat_fn=fake_slm(body_for(decision)))["reply"]
    out = write_reply(decision, chat_fn=fake_slm(warm_body_for(decision)))
    assert out["check"]["passed"] and not out["used_template"], out
    reply = out["reply"]
    if name == "warm_next_step" and reply_styles.closing_line(decision):
        reply = reply[: -len(reply_styles.closing_line(decision))].strip()
    warm_sentences, short_sentences = sentences(reply), sentences(short)
    assert len(warm_sentences) == len(short_sentences) + 1
    assert warm_sentences[0] == "Hello, " + EMPATHY[0].lower() + EMPATHY[1:]
    assert " ".join(warm_sentences[1:]).lower() == short.split(", ", 1)[1].lower()   # then the same decision as short


def test_warm_keeps_only_one_empathy_sentence():
    decision = decision_for(("shopnova", "approve"), "warm")
    out = write_reply(decision, chat_fn=fake_slm("I'm so sorry. " + EMPATHY + " I understand your frustration. "
                                                 + body_for(decision)))
    assert out["check"]["passed"]
    assert sentences(out["reply"])[0] == "Hello, " + EMPATHY[0].lower() + EMPATHY[1:]
    assert "sorry" not in out["reply"].lower() and "frustration" not in out["reply"].lower()


def test_an_empathy_sentence_written_after_the_decision_is_moved_first():
    """qwen2.5:1.5b often writes the decision first and the feeling after it (RL1b run): code moves it, adds nothing."""
    decision = decision_for(("shopnova", "info"), "warm")
    out = write_reply(decision, chat_fn=fake_slm(f"{body_for(decision)} {EMPATHY}"))
    assert not out["used_template"]
    assert out["reply"] == f"Hello, {EMPATHY[0].lower()}{EMPATHY[1:]} {body_for(decision)}"


@pytest.mark.parametrize("name", ALL_STYLES)
def test_filler_and_copied_client_words_are_removed(name):
    decision = decision_for(("shopnova", "info"), name)
    raw = (f"Hello there. {EMPATHY} {body_for(decision)} Parcel supposed to arrive for the party. "
           "Please let me know if you need any further assistance.")
    reply = write_reply(decision, chat_fn=fake_slm(raw))["reply"]
    assert "there" not in reply.split(".")[0] and "party" not in reply and "assistance" not in reply
    assert reply.startswith("Hello, ")


def test_an_invented_sentence_with_the_order_number_is_removed():
    """RL1b run, a05: "Your hotel booking 7008 is also cancelled." was kept because it had the number."""
    decision = decision_for(("atlas", "info"), "short")
    reply = write_reply(decision, chat_fn=fake_slm(f"{body_for(decision)} Your hotel booking 7008 is also cancelled."))["reply"]
    assert "hotel" not in reply


@pytest.mark.parametrize("bad", ["The client is upset and wants the money.", "Thank you for your understanding."])
def test_empathy_must_speak_to_the_client_about_the_problem(bad):
    assert reply_styles.empathy_problems(bad, decision_for(("shopnova", "info")))


def test_warm_prompt_ends_with_the_empathy_line_and_default_does_not():
    assert build_messages(decision_for(("shopnova", "info"), "warm"))[1]["content"].endswith(reply_styles.EMPATHY_LAST_LINE)
    assert build_messages(decision_for(("shopnova", "info"), "short"))[1]["content"].endswith("Write the reply now.")


def test_a_warm_reply_with_no_feeling_sentence_falls_back():
    decision = decision_for(("shopnova", "info"), "warm")
    out = write_reply(decision, chat_fn=fake_slm(f"{body_for(decision)} Is this your service?"))
    assert out["used_template"]


def test_warm_prompt_asks_for_one_empathy_sentence_first():
    text = build_messages(decision_for(("shopnova", "approve"), "warm"),
                          history=[{"role": "user", "content": "where is my money??"}])[1]["content"]
    assert "First write ONE short sentence" in text and "no number, no date, no name, no promise" in text
    assert "where is my money??" in text   # the client's words, for tone only (as before)


@pytest.mark.parametrize("bad", ["Waiting 6 days is stressful.",                      # a number
                                 "We will fix this for you.",                          # a promise
                                 "Good news, it is approved.",                         # a decision
                                 "Waiting since Monday is stressful.",                 # a date
                                 "We will keep you updated, this is stressful."])      # a forbidden promise (check.py too)
@pytest.mark.parametrize("name", ["warm", "warm_next_step"])
def test_a_bad_empathy_sentence_fails_then_the_style_template_answers(bad, name):
    decision = decision_for(("shopnova", "approve"), name)
    out = write_reply(decision, chat_fn=fake_slm(f"{bad} {body_for(decision)}"))
    assert out["used_template"] and out["attempts"] == writer.MAX_ATTEMPTS
    assert out["reply"].startswith(f"Hello, {OPENER}")   # template warm: greeting + fixed opener
    assert out["check"]["passed"]


def test_a_warm_reply_without_an_empathy_sentence_fails():
    decision = decision_for(("shopnova", "approve"), "warm")
    out = write_reply(decision, chat_fn=fake_slm(body_for(decision)))   # the model forgot the empathy sentence
    assert out["used_template"]


def test_empathy_check_accepts_a_plain_sentence_about_the_problem():
    decision = decision_for(("shopnova", "approve"))
    assert reply_styles.empathy_problems("Waiting for a parcel that does not come is stressful.", decision) == []
    assert reply_styles.empathy_problems("Not getting your money back yet is frustrating.", decision) == []
    assert reply_styles.empathy_problems("", decision)


# ---------- warm_next_step: the closing line by outcome (approved table) ----------

CLOSING_TABLE = {   # task RL1b, step 1: exact texts
    ("shopnova", "approve"): "If the money does not arrive, reply here and we will check it.",
    ("shopnova", "decline"): "If you think something is wrong, reply here with the details and we will check it.",
    ("shopnova", "ask_proof"): None,
    ("shopnova", "layer3_pending"): None,
    ("shopnova", "info"): "We will message you here if anything changes.",
    ("atlas", "approve"): "If the money does not arrive, reply here and we will check it.",
    ("atlas", "decline"): "If you think something is wrong, reply here with the details and we will check it.",
    ("atlas", "ask_proof"): None,
    ("atlas", "layer3_pending"): None,
    ("atlas", "info"): "We will message you here if anything changes.",
}


def test_closing_line_per_outcome_matches_the_table():
    for key, expected in CLOSING_TABLE.items():
        assert reply_styles.closing_line(DECISIONS[key]) == expected, key
    assert (reply_styles.closing_line({"outcome": "approve", "action": "cancel"})
            == "If you need anything else for this order, reply here.")
    assert (reply_styles.closing_line({"outcome": "approve", "action": "cancel_hotel", "case_word": "booking"})
            == "If you need anything else for this booking, reply here.")
    for outcome in ("ask_user", "ask_proof", "layer3_pending", "send_back", "escalate"):
        assert reply_styles.closing_line({"outcome": outcome, "action": "refund"}) is None


@pytest.mark.parametrize("key", CASES)
def test_warm_next_step_ends_with_the_closing_line_once(key):
    decision = decision_for(key, "warm_next_step")
    closing = CLOSING_TABLE[key]
    for out in (write_reply(decision, chat_fn=fake_slm(warm_body_for(decision))), write_reply(decision)):   # SLM, template
        assert out["check"]["passed"]
        if closing:
            assert out["reply"].endswith(" " + closing) and out["reply"].count(closing) == 1
        else:
            assert out["reply"] == write_reply(decision_for(key, "warm"), chat_fn=fake_slm(warm_body_for(decision)))["reply"] \
                or out["used_template"]


def test_the_model_never_writes_the_closing_line_and_still_sees_the_next_step():
    decision = decision_for(("shopnova", "approve"), "warm_next_step")
    text = build_messages(decision)[1]["content"]
    assert "no closing sentence" in text and CLOSING_TABLE[("shopnova", "approve")] not in text
    assert 'End with the next step, almost word for word: "Your order 4512 is now refunded."' in text


# ---------- the template fallback matches the style ----------

@pytest.mark.parametrize("key", CASES)
@pytest.mark.parametrize("name", ALL_STYLES)
def test_template_fallback_matches_the_style(key, name):
    decision = decision_for(key, name)
    out = write_reply(decision)   # conftest: the SLM is offline, so the template answers
    reply = out["reply"]
    assert out["used_template"] and out["check"]["passed"]
    assert reply.startswith("Hello, ")
    if name == "short":
        assert "sorry" not in reply.lower()
    else:
        assert sentences(reply)[0] == f"Hello, {OPENER}"
    if name == "warm_next_step" and CLOSING_TABLE[key]:
        assert sentences(reply)[-1] == CLOSING_TABLE[key]
    for item in decision["must_say"]:
        assert item.lower() in reply.lower()


@pytest.mark.parametrize("key", CASES)
def test_the_three_templates_differ_when_the_outcome_has_a_closing_line(key):
    replies = {name: write_reply(decision_for(key, name))["reply"] for name in ALL_STYLES}
    assert replies["short"] != replies["warm"]
    if CLOSING_TABLE[key]:
        assert replies["warm"] != replies["warm_next_step"]


# ---------- the style never changes the content ----------

@pytest.mark.parametrize("key", CASES)
def test_facts_next_step_and_must_say_are_identical_across_styles(key):
    allowed = []
    for name in [None] + ALL_STYLES:
        decision = decision_for(key, name)
        messages = build_messages(decision)[1]["content"]
        allowed.append(json.loads(messages.split("(nothing else):\n")[1].split("\n\n")[0]))
    for a in allowed:
        assert a == allowed[0]


@pytest.mark.parametrize("key", CASES)
def test_must_say_is_in_every_style_reply(key):
    for name in ALL_STYLES:
        decision = decision_for(key, name)
        for out in (write_reply(decision), write_reply(decision, chat_fn=fake_slm(
                body_for(decision) if name == "short" else warm_body_for(decision)))):
            for item in decision["must_say"]:
                assert item.lower() in out["reply"].lower(), (name, out["reply"])


def test_the_style_does_not_change_the_decision_dict():
    decision = decision_for(("shopnova", "approve"), "warm_next_step")
    before = json.dumps(decision, sort_keys=True)
    write_reply(decision, chat_fn=fake_slm(warm_body_for(decision)))
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
