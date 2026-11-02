"""T29 step 3: the eval bench puts fake tracking facts into ask_agent's answer too (B02), and a refund proposal for an
order with nothing paid (cash on delivery, not delivered: order 4514) is refused by code at the tool step (B06)."""

import pytest

from callverse.data import db
from callverse.data.seed import seed
from callverse.tools.proposal_tools import nothing_paid, propose_refund
from scripts.eval_agents import override_facts


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    db.use_db(tmp_path / "shopnova.db")
    seed()
    yield
    db.use_db(db.DEFAULT_DB_PATH)


ARGS = {"amount": 89.0, "rule_id": "R-REF-03", "facts_used": {"paid": 89.0}, "user_confirmed": True,
        "user_quote": "I want my money back for 4514."}


def test_refund_on_unpaid_order_4514_is_refused_by_code():
    out = propose_refund(order_id=4514, **ARGS)
    assert "error" in out and "nothing was paid for order 4514" in out["error"]


def test_refund_on_a_paid_order_is_still_submitted():
    assert nothing_paid(4512) == []
    assert propose_refund(order_id=4512, **{**ARGS, "amount": 59.90}) == {"status": "submitted to Coordinator"}


def test_unknown_order_is_left_to_the_coordinator():
    assert nothing_paid(99999) == []


def test_bench_override_reaches_the_ask_agent_facts():
    result = {"agent": "A", "answer": "6 days late",
              "facts": {"source": "get_tracking", "order_id": 4512, "days_late": 6, "delivered": False}}
    out = override_facts(result, {"get_tracking": {"days_late": 3}})
    assert out["facts"]["days_late"] == 3 and out["facts"]["delivered"] is False
    assert override_facts(result, {}) == result                                # no override: unchanged
    error = {"agent": "A", "facts": {"error": "Agent A did not read the tracking data"}}
    assert override_facts(error, {"get_tracking": {"days_late": 3}}) == error
