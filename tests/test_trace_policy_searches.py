"""The trace-reading script finds each policy search and what the agent and Coordinator did after it.

Offline: a small fake trace is written to a temp file, no model and no API call.
"""

import json
import sys

from scripts import trace_policy_searches as tps


def _line(step, data):
    return {"step": step, "actor": "x", "data": data}


def test_lists_searches_with_cited_rule_and_coordinator_rule(tmp_path, monkeypatch, capsys):
    lines = [
        _line("intake_start", {"ticket_id": "T-1", "text": "Order 4512 is late, refund me"}),
        _line("policy_search", {"query": "late refund", "k": 2,
                                "results": [{"id": "R-REF-03", "score": 0.8}, {"id": "R-DEL-02", "score": 0.7}]}),
        _line("tool_call", {"agent": "B", "tool": "search_policy"}),
        _line("proposal", {"order_id": 4512, "rule_id": "R-REF-03"}),
        _line("final_answer", {"output": {"agent": "B", "answer": "Proposed under R-REF-03."}}),
        _line("coordinator_decision", {"outcome": "approve", "rule_id": "R-REF-03"}),
        _line("intake_start", {"ticket_id": "T-2", "text": "Return my shoes"}),
        _line("policy_search", {"query": "return shoes", "k": 2,
                                "results": [{"id": "R-RET-01", "score": 0.6}, {"id": "R-DMG-01", "score": 0.5}]}),
        _line("tool_call", {"agent": "B", "tool": "search_policy"}),
        _line("final_answer", {"output": {"agent": "B", "answer": "Not late under R-DEL-02."}}),
        _line("coordinator_decision", {"outcome": "info", "rule_id": None}),
    ]
    found = tps.policy_searches(lines)
    assert len(found) == 2
    assert found[0]["returned"] == [("R-REF-03", 0.8), ("R-DEL-02", 0.7)]
    assert found[0]["cited"] == ["R-REF-03"] and found[0]["coordinator"] == ("approve", "R-REF-03")
    assert found[1]["cited"] == ["R-DEL-02"] and found[1]["coordinator"] == ("info", None)

    path = tmp_path / "run.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["trace_policy_searches", str(path)])
    tps.main()
    out = capsys.readouterr().out
    assert "all among returned: True" in out and "all among returned: False" in out
    assert "Total: 2 policy searches" in out
