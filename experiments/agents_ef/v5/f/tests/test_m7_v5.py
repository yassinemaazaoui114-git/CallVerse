"""Tests for the M7 v5 checks (v5/f/m7/quality_v5.py): a POSITIVE and a NEGATIVE case per new check, plus
boundary cases. Hand-written trace lines in the prototype's format; no model, no network.

    python -m pytest v5/f/tests -q          (from experiments/agents_ef)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from v4.f.m7.conversations_v4 import parse_trace_v4  # noqa: E402
from v5.f.m7.quality_v5 import CODES, NEW_CODES, new_flags, review_v5  # noqa: E402

T0, T1 = "2026-10-09T09:00:00.000", "2026-10-09T09:00:04.000"


def L(step, actor, data, t=T0):
    return {"time": t, "run_id": "r1", "step": step, "actor": actor, "data": data}


def conv(tmp_path, reply, outcome="approve", action="refund", facts=None, writes=(), text="Order 4512 is late, "
         "I want my money back.", paid=59.9, refunded=0, must_say=(), handover=None, order_id=4512):
    facts = facts if facts is not None else {"order_status": "refunded", "days_late": 8, "amount_tnd": paid}
    decision = {"outcome": outcome, "action": action, "order_id": order_id, "rule_id": "R-REF-03", "facts": facts,
                "must_say": list(must_say), "next_step": ""}
    rows = [L("intake_start", "intake", {"ticket_id": "T-1", "text": text}),
            L("intake_ticket", "intake", {"ticket_id": "T-1", "order_id": order_id, "main_reason": "refund_request",
                                          "priority_label": "high"}),
            L("coordinator_check", "coordinator", {"check": "facts_from_data", "facts": {
                "order_id": order_id, "paid": paid, "refunded_total": refunded, "days_late": 8, "delivered": False,
                "promised_date": "2026-10-01"}, "result": "pass", "detail": "agent claimed: {}"})]
    rows += [L("db_write", "db", w) for w in writes]
    rows += [L("coordinator_decision", "coordinator", decision),
             L("pipeline_done", "pipeline", {"route": {"agent": "B"}, "decision": decision, "final_reply": reply,
                                             "reply_source": "slm", "handover": handover}, t=T1)]
    p = tmp_path / "c.jsonl"
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    [c] = parse_trace_v4(p)
    return c


REFUND_W = {"function": "create_refund", "args": {"order_id": 4512, "amount": 59.9}, "result": {"status": "approved"}}
SUB_W = {"function": "create_subscription", "args": {"order_id": 4512, "event": "delivered"}, "result": {"id": 1}}
OK = "Hello, your request has been approved about your order 4512. The amount is 59.90 TND."


def codes(c):
    return [f["code"] for f in new_flags(c)]


def test_codes_listed_and_clean_case(tmp_path):
    assert len(NEW_CODES) == 7 and len(CODES) == 21
    c = conv(tmp_path, OK, writes=[REFUND_W])
    assert codes(c) == []
    assert review_v5(c)["checks_version"] == "m7-v5"


# 1 refund promise
def test_refund_promise_without_approval_positive(tmp_path):
    c = conv(tmp_path, "Your refund of 59.90 TND has been approved for order 4512.", outcome="layer3")
    assert "reply_refund_promise_unbacked" in codes(c)


def test_refund_promise_approved_but_not_executed_positive(tmp_path):
    c = conv(tmp_path, "Your refund of 59.90 TND has been approved for order 4512.", writes=[])
    f = [x for x in new_flags(c) if x["code"] == "reply_refund_promise_unbacked"]
    assert f and "executed" in f[0]["what"]


def test_refund_promise_approved_and_executed_negative(tmp_path):
    c = conv(tmp_path, "Your refund of 59.90 TND has been approved for order 4512.", writes=[REFUND_W])
    assert "reply_refund_promise_unbacked" not in codes(c)


def test_refund_promise_french_positive_and_neutral_french_negative(tmp_path):
    c = conv(tmp_path, "Bonjour, vous serez remboursé pour la commande 4512.", outcome="ask_proof")
    assert "reply_refund_promise_unbacked" in codes(c)
    c = conv(tmp_path, "Bonjour, nous avons besoin d'une preuve pour la commande 4512.", outcome="ask_proof")
    assert "reply_refund_promise_unbacked" not in codes(c)       # boundary: mentions the case, promises nothing


# 2 delivery promise
def test_delivery_promise_positive(tmp_path):
    c = conv(tmp_path, "Your order 4512 will arrive tomorrow.", outcome="info", action="status")
    assert "reply_delivery_promise_unsupported" in codes(c)


def test_delivery_promise_repeating_data_date_negative(tmp_path):
    c = conv(tmp_path, "Your order 4512 should be delivered by 2026-10-01 as promised.", outcome="info",
             action="status", facts={"promised_date": "2026-10-01"})
    assert "reply_delivery_promise_unsupported" not in codes(c)


def test_delivery_status_without_promise_negative(tmp_path):
    c = conv(tmp_path, "Your order 4512 is out for delivery.", outcome="info", action="status", facts={})
    assert "reply_delivery_promise_unsupported" not in codes(c)


# 3 numbers
def test_number_unsupported_positive_and_client_number_negative(tmp_path):
    c = conv(tmp_path, "Your refund of 75.00 TND for order 4512 is approved.", writes=[REFUND_W])
    f = [x for x in new_flags(c) if x["code"] == "reply_number_unsupported"]
    assert f and f[0]["evidence"]["numbers"] == [75.0]
    c = conv(tmp_path, "About your order 4512: you wrote it is late.", outcome="info", action="status", facts={})
    assert "reply_number_unsupported" not in codes(c)            # 4512 is the order id (allowed)


# 4 instruction leak
def test_instruction_leak_positive_and_negative(tmp_path):
    c = conv(tmp_path, 'As an AI I followed my instructions: {"outcome": "approve"} order 4512, 59.90 TND.',
             writes=[REFUND_W])
    assert "reply_instruction_leak" in codes(c)
    assert "reply_instruction_leak" not in codes(conv(tmp_path, OK, writes=[REFUND_W]))


# 5 language
def test_english_client_french_reply_positive_and_french_client_negative(tmp_path):
    fr = "Bonjour, votre commande 4512 est livrée, merci pour votre patience."
    c = conv(tmp_path, fr, outcome="info", action="status", facts={}, text="Where is my order 4512? It is late.")
    assert "reply_language_unexpected" in codes(c)
    c = conv(tmp_path, fr, outcome="info", action="status", facts={},
             text="Bonjour, ma commande 4512 est en retard, merci")
    assert "reply_language_unexpected" not in codes(c)


# 6 follow-ups
def test_notification_promise_without_subscription_positive_with_negative(tmp_path):
    r = "Sure, for your order 4512 you will get a message when it is delivered."
    assert "followup_promise_unbacked" in codes(conv(tmp_path, r, action="subscribe", facts={}))
    assert "followup_promise_unbacked" not in codes(conv(tmp_path, r, action="subscribe", facts={}, writes=[SUB_W]))


def test_contact_promise_requires_escalation(tmp_path):
    r = "A colleague will take over your request about your order 4512."
    assert "followup_promise_unbacked" in codes(conv(tmp_path, r, outcome="info", action="status", facts={}))
    assert "followup_promise_unbacked" not in codes(conv(tmp_path, r, outcome="escalate", action=None, facts={}))


# 7 business rule
def test_refund_exceeds_balance_positive_and_boundary(tmp_path):
    big = {**REFUND_W, "args": {"order_id": 4512, "amount": 59.9}}
    c = conv(tmp_path, OK, writes=[big], refunded=20.0)
    f = [x for x in new_flags(c) if x["code"] == "refund_exceeds_balance"]
    assert f and abs(f[0]["evidence"]["amount"] - 59.9) < 1e-9
    assert "refund_exceeds_balance" not in codes(conv(tmp_path, OK, writes=[big], refunded=0))   # exactly the balance
