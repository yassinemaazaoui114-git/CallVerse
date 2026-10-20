"""A tool outside the agent's allow-list is refused and logged."""

import json

from callverse import trace
from callverse.tools.registry import run_tool


def test_tool_outside_allow_list_is_refused_and_logged():
    result = run_tool("A", "issue_refund", {"order_id": 4512, "amount": 59.90})
    assert "error" in result and "not allowed" in result["error"]

    lines = trace.current_path().read_text(encoding="utf-8").splitlines()
    last = json.loads(lines[-1])
    assert last["step"] == "tool_refused"
    assert last["data"]["tool"] == "issue_refund"


def test_allowed_tool_runs():
    result = run_tool("A", "get_tracking", {"order_id": 4512})
    assert result["days_late"] == 6
