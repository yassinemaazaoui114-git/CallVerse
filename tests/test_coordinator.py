"""T07 tests: the Coordinator (rules only, no LLM, no API call) and the send-back loop of the pipeline.

Each test runs on a fresh placeholder database (conftest.py), so proposal ids start at P-0001.
"""

import json
from contextlib import closing
from types import SimpleNamespace

from callverse import pipeline, trace
from callverse.coordinator.coordinator import new_case, review
from callverse.data import db
from callverse.data.writes import record_proposal
from callverse.kb import search
from callverse.tools.shopnova_tools import get_order, get_refunds


def refund(order_id=4512, amount=59.90, rule_id="R-REF-03", confirmed=True, facts=None):
    return {"agent": "B", "action": "refund", "params": {"order_id": order_id, "amount": amount},
            "rule_id": rule_id, "facts_used": facts or {"days_late": 6}, "user_confirmed": confirmed,
            "user_quote": "I want my money back."}


def subscribe(order_id=4512, event="out_for_delivery", rule_id="R-NOT-01"):
    return {"agent": "A", "action": "subscribe", "params": {"order_id": order_id, "event": event},
            "rule_id": rule_id, "facts_used": {}, "user_confirmed": True, "user_quote": "Tell me when it comes."}


def steps():
    return [json.loads(line) for line in trace.current_path().read_text(encoding="utf-8").splitlines()]


def test_s1_refund_is_approved_and_written():
    d = review(refund(), new_case("T-1"))
    assert d["outcome"] == "approve" and d["proposal_id"] == "P-0001"
    assert d["facts"] == {"order_status": "refunded", "days_late": 6, "amount_tnd": 59.90}   # SLM format (T08)
    assert d["must_say"] == ["Your refund of 59.90 TND is approved."]
    assert d["next_step"] == "Your order 4512 is now refunded."   # T17 F3: the status the data has
    rows = get_refunds(4512)["refunds"]
    assert len(rows) == 1 and rows[0]["amount"] == 59.90 and rows[0]["rule_id"] == "R-REF-03"
    assert rows[0]["status"] == "approved" and rows[0]["proposal_id"] == "P-0001"
    assert get_order(4512)["status"] == "refunded"
    checks = [s["data"]["check"] for s in steps() if s["step"] == "coordinator_check"]
    assert {"order_exists", "rule_condition", "refund_limit", "user_confirmed"} <= set(checks)
    assert any(s["step"] == "coordinator_decision" for s in steps())


def test_amount_above_paid_is_sent_back_with_r_ref_05():
    case = new_case("T-2")
    d = review(refund(amount=70.00), case)
    assert d["outcome"] == "send_back" and "R-REF-05" in d["reason"] and case["send_backs"] == 1
    assert get_refunds(4512)["refunds"] == []          # nothing written


def test_already_refunded_is_sent_back():
    assert review(refund(), new_case("T-3a"))["outcome"] == "approve"
    d = review(refund(amount=10.0), new_case("T-3b"))   # 59.90 already refunded
    assert d["outcome"] == "send_back" and "R-REF-05" in d["reason"]


def test_rule_condition_false_is_sent_back_even_if_the_agent_says_otherwise():
    # 4510 is not late; the agent claims 9 days late: the Coordinator re-reads the data itself.
    d = review(refund(order_id=4510, amount=10.0, facts={"days_late": 9, "delivered": False}), new_case("T-4"))
    assert d["outcome"] == "send_back" and "R-REF-03 does not apply" in d["reason"]
    assert d["facts"]["days_late"] == 0


def test_rule_that_cannot_justify_a_refund_is_sent_back():
    d = review(refund(rule_id="R-REF-05"), new_case("T-4b"))
    assert d["outcome"] == "send_back" and "cannot justify" in d["reason"]


def test_not_confirmed_asks_the_user():
    d = review(refund(confirmed=False), new_case("T-5"))
    assert d["outcome"] == "ask_user" and get_refunds(4512)["refunds"] == []


def test_damaged_without_proof_asks_for_proof():
    d = review(refund(order_id=4507, amount=10.0, rule_id="R-DMG-01"), new_case("T-5b"))
    assert d["outcome"] == "ask_proof"


def test_4515_goes_to_layer3_and_is_approved():
    d = review(refund(order_id=4515, amount=378.00), new_case("T-6"))
    assert d["outcome"] == "approve" and d["facts"]["layer3_decision"] == "approved"
    assert d["facts"]["threshold_tnd"] == 300.0
    assert d["must_say"] == ["Your refund of 378.00 TND is approved after a check by our finance team."]
    assert get_refunds(4515)["refunds"][0]["amount"] == 378.00


def test_600_is_refused_by_layer3():
    with closing(db.connect()) as con:     # temp test DB only: make 600 TND possible under R-REF-05
        con.execute("UPDATE orders SET paid = 650 WHERE id = 4515")
        con.commit()
    d = review(refund(order_id=4515, amount=600.00), new_case("T-7"))
    assert d["outcome"] == "layer3_refused" and get_refunds(4515)["refunds"] == []


def test_third_send_back_becomes_escalate():
    case = new_case("T-8")
    outcomes = [review(refund(amount=70.00), case)["outcome"] for _ in range(3)]
    assert outcomes == ["send_back", "send_back", "escalate"]


def test_subscribe_event_outside_r_not_01_is_sent_back():
    assert review(subscribe(event="stuck_at_depot"), new_case("T-9"))["outcome"] == "send_back"


def test_subscribe_is_approved_and_written():
    d = review(subscribe(), new_case("T-9b"))
    assert d["outcome"] == "approve" and d["action"] == "subscribe"


def test_a_proposal_decided_twice_is_refused():
    proposal = {**refund(), "proposal_id": record_proposal(refund())["id"]}
    assert review(proposal, new_case("T-10"))["outcome"] == "approve"
    again = review(proposal, new_case("T-10"))
    assert again["outcome"] == "refused" and "already decided" in again["reason"]
    assert len(get_refunds(4512)["refunds"]) == 1      # still only one refund


# ---------- pipeline: send_back -> the same agent corrects -> approve (S2 with a fake LLM) ----------

def tool_call_reply(name, arguments):
    tc = SimpleNamespace(id="c1", function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))
    return SimpleNamespace(content=None, tool_calls=[tc])


def text_reply(text):
    return SimpleNamespace(content=text, tool_calls=None)


def test_pipeline_send_back_then_corrected_proposal_is_approved(monkeypatch):
    monkeypatch.setattr(search, "search_policy", lambda q, k=3: [{"id": "R-REF-03", "title": "", "text": "", "score": 1}])
    args = {"order_id": 4512, "rule_id": "R-REF-03", "facts_used": {"days_late": 6}, "user_confirmed": True,
            "user_quote": "I want my money back."}
    seen = []

    def fake(role_key, messages, tools=None):
        last = messages[-1]
        if last["role"] == "user":                        # start of a B turn
            seen.append(last["content"])
            amount = 59.90 if "sent back" in last["content"] else 70.00
            return tool_call_reply("propose_refund", {**args, "amount": amount})
        return text_reply("Your refund request is sent for checking (rule R-REF-03).")

    ticket = {"ticket_id": "T-S2", "text": "Order 4512 is a week late. I want my money back.",
              "order_id": 4512, "main_reason": "refund_request", "priority_label": "high"}
    out = pipeline.handle_ticket(ticket, chat_fn=fake)

    assert [p["params"]["amount"] for p in out["proposals"]] == [70.00, 59.90]
    assert out["decision"]["outcome"] == "approve" and out["decision"]["proposal_id"] == "P-0002"
    assert "R-REF-05" in seen[1]                           # the reason went back to Agent B
    assert get_refunds(4512)["refunds"][0]["amount"] == 59.90
