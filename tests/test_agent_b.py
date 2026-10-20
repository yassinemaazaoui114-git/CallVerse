"""T06 tests: policy search ranking, propose_refund checks, allow-lists, Agent B in the pipeline,
the R-ESC-01 threshold in Intake, the plain-text rule in the prompts.

No API call: agents get a fake LLM. The policy-search ranking uses hand-made (stubbed) vectors.
The held-out file tests/data/policy_search_questions.json is NOT used here (final evaluation only).
"""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from callverse import pipeline, trace
from callverse.agents import agent_a, agent_b
from callverse.intake import priority
from callverse.kb import search
from callverse.tools import proposal_tools
from callverse.tools.registry import run_tool


def tool_call_reply(name, arguments, call_id="call_1"):
    tool_call = SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))
    return SimpleNamespace(content=None, tool_calls=[tool_call])


def text_reply(text):
    return SimpleNamespace(content=text, tool_calls=None)


def trace_steps():
    return [json.loads(line)["step"] for line in trace.current_path().read_text(encoding="utf-8").splitlines()]


# ---------- policy search ----------

RULES = [{"id": "R-1", "title": "one", "text": "t1"},
         {"id": "R-2", "title": "two", "text": "t2"},
         {"id": "R-3", "title": "three", "text": "t3"}]
VECTORS = np.eye(3)   # rule i points along axis i


def test_rank_best_first_with_stubbed_vectors():
    query = np.array([0.2, 0.9, 0.4])                 # closest to R-2, then R-3, then R-1
    ranked = search.rank(query, VECTORS, RULES, k=3)
    assert [r["id"] for r in ranked] == ["R-2", "R-3", "R-1"]
    assert ranked[0]["score"] == 0.9 and ranked[0]["title"] == "two" and ranked[0]["text"] == "t2"
    assert [r["id"] for r in search.rank(query, VECTORS, RULES, k=1)] == ["R-2"]


def test_search_policy_uses_k_and_is_traced(monkeypatch):
    monkeypatch.setattr(search, "load_policies", lambda: RULES)
    monkeypatch.setattr(search, "policy_vectors", lambda: VECTORS)
    monkeypatch.setattr(search, "embed", lambda texts: np.array([[0.9, 0.1, 0.3]]))
    assert [r["id"] for r in search.search_policy("anything", k=2)] == ["R-1", "R-3"]
    assert len(search.search_policy("anything", k=99)) == 3      # never more than the number of rules
    assert "policy_search" in trace_steps()


def test_search_policy_tool_refuses_empty_query():
    assert "error" in search.search_policy_tool("  ")


# ---------- propose_refund ----------

GOOD = {"order_id": 4512, "amount": 59.90, "rule_id": "R-REF-03",
        "facts_used": {"days_late": 6, "delivered": False, "paid": 59.90, "refunded_total": 0.0},
        "user_confirmed": True, "user_quote": "I want my money back."}


def test_propose_refund_gives_an_id_and_writes_nothing():
    out = run_tool("B", "propose_refund", GOOD)
    assert out == {"proposal_id": "P-0001", "status": "submitted to Coordinator"}
    assert proposal_tools.get_proposal("P-0001")["amount"] == 59.90
    assert "proposal" in trace_steps()
    assert run_tool("B", "get_refunds", {"order_id": 4512})["refunds"] == []    # no database write
    assert run_tool("B", "propose_refund", GOOD)["proposal_id"] == "P-0002"


@pytest.mark.parametrize("field, bad", [
    ("rule_id", None), ("rule_id", ""), ("rule_id", "R-XXX-99"),
    ("amount", 0), ("amount", -5), ("amount", float("nan")), ("amount", True), ("amount", "59.90"),
    ("order_id", "4512"), ("order_id", True),
    ("user_confirmed", "yes"), ("facts_used", {}), ("user_quote", ""),
])
def test_propose_refund_refuses_bad_fields(field, bad):
    out = run_tool("B", "propose_refund", {**GOOD, field: bad})
    assert out["error"].startswith("proposal refused") and field in out["error"]
    assert proposal_tools.get_proposal("P-0001") is None


def test_propose_refund_refuses_missing_rule_id():
    args = {k: v for k, v in GOOD.items() if k != "rule_id"}
    assert "rule_id is missing" in run_tool("B", "propose_refund", args)["error"]


# ---------- allow-lists ----------

def test_allow_lists():
    assert "not allowed" in run_tool("B", "get_tracking", {"order_id": 4512})["error"]
    assert "not allowed" in run_tool("A", "propose_refund", GOOD)["error"]
    assert "not allowed" in run_tool("A", "ask_agent", {"agent": "A", "question": "?"})["error"]
    assert run_tool("A", "get_company_profile", {})["name"]          # A may read the company profile


def test_ask_agent_only_agent_a():
    assert "cannot be asked" in run_tool("B", "ask_agent", {"agent": "B", "question": "?"})["error"]


def test_ask_agent_returns_answer_and_facts():
    replies = iter([tool_call_reply("get_tracking", {"order_id": 4512}), text_reply("6 days late.")])
    out = run_tool("B", "ask_agent", {"agent": "A", "question": "Is 4512 late?"},
                   chat_fn=lambda role_key, messages, tools=None: next(replies))
    assert out["answer"] == "6 days late."
    assert out["facts"][0]["tool"] == "get_tracking" and out["facts"][0]["result"]["days_late"] == 6


# ---------- Agent B in the pipeline ----------

def scripted_llm():
    """Fake LLM: Agent B follows its steps and proposes 59.90 under R-REF-03; Agent A reads tracking."""
    b_steps = iter([
        tool_call_reply("get_order", {"order_id": 4512}),
        tool_call_reply("ask_agent", {"agent": "A", "question": "Delivery status of order 4512?"}),
        tool_call_reply("get_refunds", {"order_id": 4512}),
        tool_call_reply("search_policy", {"query": "refund for a late order"}),
        tool_call_reply("propose_refund", GOOD),
    ])
    a_steps = iter([tool_call_reply("get_tracking", {"order_id": 4512}),
                    text_reply("Order 4512 is stuck at the depot, 6 days late.")])

    def fake(role_key, messages, tools=None):
        if messages[0]["content"].startswith("You are Agent A"):
            return next(a_steps)
        step = next(b_steps, None)
        return step or text_reply("Your refund request of 59.90 TND is sent for checking (rule R-REF-03).")
    return fake


def test_route_b_runs_agent_b_and_returns_the_proposal(monkeypatch):
    # stubbed search: no model needed in this test
    monkeypatch.setattr(search, "search_policy", lambda query, k=3: [{"id": "R-REF-03", "title": "", "text": "", "score": 1.0}])
    ticket = {"ticket_id": "T-B", "text": "Order 4512 is a week late. I want my money back.",
              "order_id": 4512, "main_reason": "refund_request", "priority_label": "high"}
    out = pipeline.handle_ticket(ticket, chat_fn=scripted_llm())

    assert out["route"]["agent"] == "B" and out["handover"] == "B"
    assert out["handover_text"] == "Your request is passed on for a refund check."
    assert out["proposal"]["proposal_id"] == "P-0001"
    assert out["proposal"]["amount"] == 59.90 and out["proposal"]["rule_id"] == "R-REF-03"
    assert out["proposal"]["user_confirmed"] is True
    assert "R-REF-03" in out["answer"] and "**" not in out["answer"]


def test_handover_texts_per_reason():
    assert pipeline.handover_text("refund_request") == "Your request is passed on for a refund check."
    assert pipeline.handover_text("return_item") == "Your request is passed on for a returns check."
    assert pipeline.handover_text("damaged_item") == "Your request is passed on for a damage check."
    assert pipeline.handover_text("order_status") == "Your request is passed on for a refund check."


# ---------- R-ESC-01 threshold and plain-text rule ----------

def test_intake_amount_bonus_reads_r_esc_01(monkeypatch):
    cfg = {"severity_base": {"other": 0.2}, "late_bonus": {"days_late_over": 5, "add": 0.3},
           "amount_bonus": {"add": 0.2}}
    assert priority.severity(["other"], 0, 300.0, cfg) == 0.2          # threshold is "> 300"
    assert priority.severity(["other"], 0, 300.01, cfg) == pytest.approx(0.4)
    monkeypatch.setattr(priority, "layer3_threshold", lambda: 100.0)  # the value comes from the rule
    assert priority.severity(["other"], 0, 150.0, cfg) == pytest.approx(0.4)


def test_prompts_ask_for_plain_text():
    for prompt in (agent_a.SYSTEM_PROMPT, agent_b.SYSTEM_PROMPT):
        assert "plain text only, no Markdown" in prompt
        assert "**" not in prompt
    assert "refund team" not in agent_a.SYSTEM_PROMPT
