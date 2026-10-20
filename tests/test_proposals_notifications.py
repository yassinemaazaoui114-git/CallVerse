"""P06: proposals audit table, create_refund needs an approved proposal, notifications, simulator data."""

import json
import sqlite3
from contextlib import closing

from callverse import trace
from callverse.data import db
from callverse.data.reports import get_pending_notifications, list_rows
from callverse.data.simulator_data import list_scenario_cases, read_own_case
from callverse.data.writes import (create_refund, create_subscription, mark_subscription_sent, record_decision,
                                   record_proposal, set_order_status)
from callverse.tools import registry

PROPOSAL = {"agent": "B", "action": "refund", "params": {"order_id": 4512, "amount": 59.90},
            "rule_id": "R-REF-03", "facts_used": {"days_late": 6, "paid": 59.90, "delivered": False},
            "user_confirmed": True, "user_quote": "I want my money back"}


def _last_trace() -> dict:
    return json.loads(trace.current_path().read_text(encoding="utf-8").splitlines()[-1])


# --- proposals -------------------------------------------------------------

def test_record_proposal_ids_in_order_and_stored():
    assert record_proposal(PROPOSAL) == "P-0001"
    assert record_proposal({**PROPOSAL, "params": {"order_id": 4512, "amount": 70.0}}) == "P-0002"
    assert _last_trace()["step"] == "db_write"
    rows = {r["id"]: r for r in list_rows("proposals")}
    p1 = rows["P-0001"]
    assert p1["agent"] == "B" and p1["action"] == "refund" and p1["rule_id"] == "R-REF-03"
    assert p1["params"] == {"order_id": 4512, "amount": 59.90} and p1["facts_used"]["days_late"] == 6
    assert p1["user_confirmed"] is True and p1["decision"] is None and p1["created_at"] == "2026-10-09"
    assert p1["ai_generated"] == 0 and p1["scripted"] == 0


def test_record_proposal_refuses_bad_input():
    assert "error" in record_proposal({"action": "refund"})                                    # no agent
    assert "error" in record_proposal({"agent": "B"})                                          # no action
    assert "error" in record_proposal({**PROPOSAL, "params": {"amount": float("nan")}})         # not JSON-safe
    assert "error" in record_proposal("refund 59.90")
    assert _last_trace()["step"] == "db_write_refused"


def test_record_decision():
    pid = record_proposal(PROPOSAL)
    row = record_decision(pid, "send_back", "amount above paid")
    assert row["decision"] == "send_back" and row["decision_reason"] == "amount above paid"
    assert row["decided_at"] == "2026-10-09"
    assert "error" in record_decision(pid, "approve", "again")      # decided once: audit is never rewritten
    assert "error" in record_decision("P-9999", "approve", "x")
    assert "error" in record_decision(record_proposal(PROPOSAL), "maybe", "x")


def test_create_refund_needs_an_approved_proposal_for_the_same_order():
    assert "not found" in create_refund(4512, 59.90, "R-REF-03", "p-made-up")["error"]
    pid = record_proposal(PROPOSAL)
    assert "not approved" in create_refund(4512, 59.90, "R-REF-03", pid)["error"]       # not decided yet
    record_decision(pid, "approve", "R-REF-03 holds")
    assert "order 4512" in create_refund(4515, 59.90, "R-REF-03", pid)["error"]          # other order
    assert create_refund(4512, 59.90, "R-REF-03", pid)["status"] == "approved"
    assert "already used" in create_refund(4512, 1.00, "R-REF-03", pid)["error"]          # one refund per proposal
    sent_back = record_proposal(PROPOSAL)
    record_decision(sent_back, "send_back", "x")
    assert "not approved" in create_refund(4512, 1.00, "R-REF-03", sent_back)["error"]


def test_layer3_flow_4515():
    """Finance approves first, then the Coordinator records approve, then the refund is written."""
    from callverse.data.layer3 import layer3_decide
    pid = record_proposal({**PROPOSAL, "params": {"order_id": 4515, "amount": 378.00}})
    assert layer3_decide(4515, 378.00, "late, above 300 TND")["decision"] == "approved"
    record_decision(pid, "approve", "finance approved (Layer 3)")
    assert create_refund(4515, 378.00, "R-REF-03", pid)["status"] == "approved"


# --- notifications ---------------------------------------------------------

def test_s3_pending_then_sent():
    sub = create_subscription(4512, "delivered")
    assert get_pending_notifications() == []                     # nothing happened yet
    set_order_status(4512, "out_for_delivery")                   # an event, but not the one subscribed to
    assert get_pending_notifications() == []
    set_order_status(4512, "delivered")
    pending = get_pending_notifications()
    assert len(pending) == 1
    item = pending[0]
    assert item["subscription_id"] == sub["id"] and item["order_id"] == 4512 and item["event"] == "delivered"
    assert item["event_at"] == "2026-10-09"
    assert item["user"] == {"id": 1, "name": "Sara Ben Ali", "email": "sara@example.com", "phone": "+216 20 111 222"}

    row = mark_subscription_sent(sub["id"])
    assert row["status"] == "sent" and _last_trace()["step"] == "db_write"
    assert get_pending_notifications() == []
    assert "error" in mark_subscription_sent(sub["id"])          # second call refused
    assert _last_trace()["step"] == "db_write_refused"
    assert "error" in mark_subscription_sent(999)


# --- simulator data ---------------------------------------------------------

def test_read_own_case_4512():
    case = read_own_case(4512)
    assert case["days_late"] == 6 and case["paid"] == 59.90 and case["status"] == "stuck_at_depot"
    assert case["user"] == {"name": "Sara Ben Ali", "email": "sara@example.com"}
    assert case["promised_date"] == "2026-10-03" and case["items"][0]["name"] == "Wireless Earbuds"
    assert "refunds" not in case and "user_id" not in case       # only what the client knows
    assert "error" in read_own_case(9999)


def test_list_scenario_cases():
    cases = {c["order_id"]: c["scenario"] for c in list_scenario_cases()}
    assert cases == {4512: "late_refund", 4506: "already_refunded", 4510: "on_time",
                     4507: "damaged", 4515: "layer3"}
    with closing(sqlite3.connect(db.db_path())) as con:              # all are scripted orders
        for oid in cases:
            assert con.execute("SELECT scripted FROM orders WHERE id = ?", (oid,)).fetchone()[0] == 1


def test_new_functions_are_not_tools():
    names = ("record_proposal", "record_decision", "mark_subscription_sent", "get_pending_notifications",
             "read_own_case", "list_scenario_cases")
    for name in names:
        assert name not in registry.TOOL_FUNCTIONS and name not in registry.TOOL_SCHEMAS
        assert all(name not in allowed for allowed in registry.ALLOW_LISTS.values())
