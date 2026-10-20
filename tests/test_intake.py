"""Intake tests. No API call: the LLM fallback is either not used or replaced by a fake.

The held-out test set (tests/data/intake_test_messages.json) is NOT used here; it is only for
scripts/eval_intake.py. The messages below are written for these tests.
"""

from types import SimpleNamespace

import pytest

from callverse.intake import extract, intake, llm_fallback, priority, style


# ---------- extraction (regex) ----------

@pytest.mark.parametrize("text, expected", [
    ("Where is my order 4512?", 4512),
    ("Order #4510 hasn't moved", 4510),
    ("my parcel #451200 is late", 451200),
    ("I paid 1500 TND for order 4512", 4512),        # the amount is skipped, the order number is kept
    ("I paid 1500 TND, nothing arrived", None),       # an amount alone is not an order number
    ("It was promised on 03/10/2026", None),          # a date is not an order number
    ("Call me on +216 20 111 222", None),             # a phone number is not an order number
    ("Where is my parcel?", None),
])
def test_find_order_id(text, expected):
    assert extract.find_order_id(text) == expected


def test_find_email_and_phone():
    ids = extract.extract("I'm Sara (Sara@Example.com), phone 20-111-222, order 4512.")
    assert ids == {"order_id": 4512, "email": "sara@example.com", "phone": "+216 20 111 222"}
    assert extract.find_phone("call +21622333444") == "+216 22 333 444"
    assert extract.extract("hello") == {"order_id": None, "email": None, "phone": None}


# ---------- priority formula on fixed numbers ----------

def test_priority_late_refund_is_high():
    # refund 0.5 + 0.3 (6 days late) = 0.8 ; time 6/7 ; emotion 0.1
    p = priority.compute(["refund_request"], {"days_late": 6, "delivered": False, "paid": 59.9}, 0.1)
    assert p["severity"] == 0.8
    assert p["time_pressure"] == round(6 / 7, 3)
    assert p["priority_score"] == round(0.6 * 0.8 + 0.25 * 6 / 7 + 0.15 * 0.1, 3)   # 0.709
    assert p["priority_label"] == "high"


def test_priority_angry_but_on_time_is_low():
    p = priority.compute(["order_status"], {"days_late": 0, "delivered": False, "paid": 74.9}, 0.95)
    assert p["severity"] == 0.2 and p["time_pressure"] == 0.0
    assert p["priority_score"] == round(0.6 * 0.2 + 0.15 * 0.95, 3)                  # 0.263
    assert p["priority_label"] == "low"


def test_priority_bonuses_and_cap():
    # damaged 0.6 + 0.3 (late) + 0.2 (paid > 300) = 1.1 -> capped at 1 ; time capped at 1
    p = priority.compute(["damaged_item"], {"days_late": 10, "delivered": False, "paid": 450}, 0.0)
    assert p["severity"] == 1.0 and p["time_pressure"] == 1.0
    assert p["priority_score"] == 0.85 and p["priority_label"] == "high"


def test_priority_no_order_and_worst_reason_counts():
    no_order = {"days_late": None, "delivered": None, "paid": None}
    p = priority.compute(["order_status", "damaged_item"], no_order, 0.5)
    assert p["severity"] == 0.6                       # the most severe sub-case
    assert p["time_pressure"] == 0.0
    assert p["priority_label"] == "medium"            # 0.36 + 0.075 = 0.435


# ---------- style rules ----------

def test_style_formal_long_calm():
    text = ("Dear Sir or Madam, I would like to know the status of my order 4512. It was promised for "
            "the 3rd of October and I have not received it yet. Could you please check it with the carrier "
            "and tell me when I can expect it to arrive at my home address? Thank you in advance for your "
            "help. Kind regards, Sara")
    s = style.profile(text)
    assert s["formality"] == "formal" and s["length"] == "long"
    assert not s["exclamation"] and not s["shouting"]


def test_style_casual_short_shouting():
    s = style.profile("hey WHERE IS MY ORDER?? pls asap!!!")
    assert s["formality"] == "casual" and s["length"] == "short"
    assert s["exclamation"] and s["exclamation_count"] == 3
    assert s["shouting"]


def test_style_abbreviations_are_not_shouting():
    s = style.profile("I paid 59.90 TND by SMS link, where is my order?")
    assert not s["shouting"] and s["formality"] == "neutral"


# ---------- LLM fallback answer validation (no API) ----------

def test_fallback_parses_and_validates_json():
    ok = llm_fallback.parse_answer('```json\n{"reasons": ["refund_request", "other"], "order_id": 4512}\n```')
    assert ok == {"reasons": ["refund_request"], "order_id": 4512, "valid": True}

    invented = llm_fallback.parse_answer('{"reasons": ["angry_customer"], "order_id": "4512"}')
    assert invented["reasons"] == ["other"] and invented["valid"] is False

    assert llm_fallback.parse_answer("Sorry, I cannot help.")["reasons"] == ["other"]
    assert llm_fallback.parse_answer('{"reasons": ["late_delivery"], "order_id": "abc"}')["order_id"] is None


def test_fallback_uses_fake_llm():
    fake = lambda role_key, messages, tools=None: SimpleNamespace(
        content='{"reasons": ["return_item"], "order_id": null}')
    assert llm_fallback.classify("blah", chat_fn=fake)["reasons"] == ["return_item"]


# ---------- whole pipeline with the local models (no API: use_llm=False) ----------

def test_priority_pair_calm_late_refund_beats_angry_on_time():
    """Priority comes from the real situation: a calm client with a 6-days-late order (4512)
    must come before a very angry client whose order (4510) is on time."""
    calm = intake.process("Hello, my order 4512 still has not arrived. Could I please get a refund? Thank you.",
                          use_llm=False)
    angry = intake.process("WHERE IS MY ORDER 4510??? This is ridiculous, I am so angry with you!!!",
                           use_llm=False)

    assert calm["facts"]["days_late"] == 6 and angry["facts"]["days_late"] == 0
    assert angry["emotion_intensity"] > calm["emotion_intensity"]       # the angry one sounds worse...
    assert calm["priority_score"] > angry["priority_score"]             # ...but the calm one goes first
    assert calm["priority_label"] == "high"


def test_ticket_has_all_fields():
    t = intake.process("My order 4512 is late.", use_llm=False)
    expected = {"ticket_id", "text", "order_id", "email", "phone", "reasons", "main_reason", "emotion",
                "sentiment", "facts", "severity", "time_pressure", "emotion_intensity", "priority_score",
                "priority_label", "style", "needs_llm"}
    assert expected <= set(t)
    assert t["order_id"] == 4512 and t["facts"] == {"days_late": 6, "delivered": False, "paid": 59.9}
