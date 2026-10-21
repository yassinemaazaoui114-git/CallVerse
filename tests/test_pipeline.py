"""T04 tests: router rules, queue order, main-reason precedence, Intake allow-list, pipeline flow.
(T06: route B and Agent A's handover now run Agent B.)

No API call: Agent A gets a fake LLM; Intake runs with use_llm=False (local models only).
The messages are written for these tests (not from the held-out Intake test set).
"""

from types import SimpleNamespace

import pytest

from callverse import pipeline
from callverse.intake import intake, priority
from callverse.queues.queue import QueueManager
from callverse.queues.router import route
from callverse.tools.registry import run_tool


def make_ticket(main_reason="order_status", label="low", ticket_id="T-1", order_id=4512):
    """A hand-made ticket with only the fields the router, queue and pipeline read."""
    return {"ticket_id": ticket_id, "text": "test message", "order_id": order_id,
            "main_reason": main_reason, "priority_label": label}


def text_reply(text):
    return SimpleNamespace(content=text, tool_calls=None)


@pytest.mark.parametrize("reason, agent", [
    ("order_status", "A"), ("late_delivery", "A"), ("other", "A"),
    ("refund_request", "B"), ("return_item", "B"), ("damaged_item", "B"),
])
def test_router_rules(reason, agent):
    r = route(make_ticket(main_reason=reason, label="medium"))
    assert r == {"agent": agent, "layer": "L1", "reason": reason, "priority_label": "medium"}


def test_queue_high_medium_low_then_arrival():
    q = QueueManager()
    for tid, label in [("1", "low"), ("2", "high"), ("3", "medium"), ("4", "high"), ("5", "low")]:
        q.add(make_ticket(label=label, ticket_id=tid))
    order = [q.next()["ticket_id"] for _ in range(5)]
    assert order == ["2", "4", "3", "1", "5"]
    assert q.next() is None


def test_main_reason_precedence():
    assert intake.pick_main_reason(["late_delivery", "refund_request"]) == "refund_request"
    assert intake.pick_main_reason(["order_status", "damaged_item"]) == "damaged_item"
    assert intake.pick_main_reason(["order_status"]) == "order_status"


def test_late_plus_refund_goes_to_b():
    t = intake.process("Order 4512 is a week late. I want my money back.", use_llm=False)
    assert t["main_reason"] == "refund_request"

    def fake(role_key, messages, tools=None):
        assert messages[0]["content"].startswith("You are Agent B"), "Agent A must not run"
        return text_reply("Your request is sent for checking.")

    out = pipeline.handle_ticket(t, chat_fn=fake)
    assert out["route"]["agent"] == "B" and out["handover"] == "B"
    assert out["agent_text"] == "Your request is sent for checking."   # kept for the trace only
    assert "sent for checking" not in out["final_reply"]                # T08: never sent to the user


def test_intake_cannot_read_user_data():
    assert "not allowed" in run_tool("INTAKE", "get_user", {"email": "sara@example.com"})["error"]
    assert run_tool("INTAKE", "get_order", {"order_id": 4512})["id"] == 4512


def test_time_pressure_zero_when_delivered():
    # 4507 was delivered 2 days late: lateness still counts for severity, but there is no time pressure left
    facts = intake.get_facts(4507)
    assert facts["delivered"] is True and facts["days_late"] == 2
    assert priority.compute(["late_delivery"], facts, 0.0)["time_pressure"] == 0.0


def test_pipeline_route_a_answers():
    seen = []

    def fake(role_key, messages, tools=None):
        seen.append(messages[-1]["content"])
        return text_reply("Your order 4512 is stuck at the depot and 6 days late.")

    out = pipeline.handle_ticket(make_ticket(), chat_fn=fake)
    assert out["route"]["agent"] == "A" and out["handover"] is None
    assert "6 days late" in out["agent_text"]
    # T08: no proposal -> info decision from get_tracking; the reply comes from the decision, not the agent
    assert out["decision"]["outcome"] == "info" and out["decision"]["facts"]["days_late"] == 6
    assert "Your order 4512 is delayed at the delivery depot." in out["final_reply"]
    assert out["reply_source"] == "template"                            # SLM offline in tests
    assert "order id = 4512" in seen[0] and "main reason = order_status" in seen[0]


def test_pipeline_agent_a_handover_goes_to_agent_b():
    def fake(role_key, messages, tools=None):
        if messages[0]["content"].startswith("You are Agent A"):
            return text_reply("Your request is passed on for checking. [HANDOVER: B]")
        return text_reply("Agent B answer.")

    out = pipeline.handle_ticket(make_ticket(), chat_fn=fake)
    assert out["route"]["agent"] == "A"
    assert out["handover"] == "B" and out["agent_text"] == "Agent B answer."
    assert out["handover_text"] == "Your request is passed on for a refund check."
