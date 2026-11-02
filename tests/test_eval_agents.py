"""Tests of the test bench scripts/eval_agents.py (no model call): scoring rules, case files, held-out guard,
and Agent D's cases (rules: they run here for real, with the template wording)."""

import json
from pathlib import Path
from types import SimpleNamespace

from scripts import eval_agents as ev

ROOT = Path(__file__).resolve().parent.parent


def run(**kw):
    base = {"tools": [], "refused": [], "proposals": [], "claimed": 0, "handover": None, "answer": "", "promises": []}
    return {**base, **kw}


B01 = {"agent": "B", "must_call": ["get_order", "search_policy"], "must_not_call": [], "cite": "R-REF-03",
       "expect": {"act": "propose", "action": "refund", "rule_id": "R-REF-03", "params": {"order_id": 4512, "amount": 59.9}}}
B02 = {"agent": "B", "must_call": ["get_order"], "must_not_call": ["propose_refund"], "expect": {"act": "none"}}
A11 = {"agent": "A", "must_call": [], "must_not_call": [], "expect": {"act": "handover", "handover": "C"}}
C01 = {"agent": "C", "must_call": ["get_order"], "must_not_call": [],
       "expect": {"act": "propose", "action": "replace", "rule_id": "R-RPL-01", "params": {"order_id": 4512},
                  "outcome": "ask_user"}}
GOOD = {"action": "refund", "rule_id": "R-REF-03", "params": {"order_id": 4512, "amount": 59.90}}
REPLACE = {"action": "replace", "rule_id": "R-RPL-01", "params": {"order_id": 4512, "product_id": 1, "qty": 1}}


def test_pass_and_failure_types():
    ok = run(tools=["get_order", "search_policy", "propose_refund"], proposals=[GOOD], answer="(rule R-REF-03)")
    assert ev.score(B01, ok) == []
    assert ev.score(B01, run()) == ["no_tool", "did_not_act", "answer_rule"]
    wrong_amount = {**GOOD, "params": {"order_id": 4512, "amount": 70.0}}
    assert "bad_args" in ev.score(B01, run(tools=["get_order", "search_policy"], proposals=[wrong_amount]))
    acted = ev.score(B02, run(tools=["get_order", "propose_refund"], proposals=[GOOD]))
    assert "acted_wrongly" in acted and "wrong_tool" in acted
    assert ev.score(A11, run(handover="C")) == [] and ev.score(A11, run()) == ["wrong_handover"]


def test_outcome_is_scored_for_c():
    assert ev.score(C01, run(tools=["get_order"], proposals=[REPLACE], outcome="ask_user")) == []
    assert ev.score(C01, run(tools=["get_order"], proposals=[REPLACE], outcome="approve")) == ["wrong_outcome"]


def test_case_files_shape_and_split():
    dev = json.loads((ROOT / "tests/dev/agents_cases.json").read_text(encoding="utf-8"))["cases"]
    hidden = json.loads((ROOT / "tests/data/agents_heldout.json").read_text(encoding="utf-8-sig"))["cases"]
    assert {c["split"] for c in dev} == {"dev"} and {c["split"] for c in hidden} == {"heldout"}
    assert not {c["id"] for c in dev} & {c["id"] for c in hidden}
    assert {c["agent"] for c in dev} == set("ABCD") and {c["agent"] for c in hidden} == set("AB")
    for c in dev + hidden:
        assert c["expect"].get("act", "scan") in ("none", "propose", "handover", "any", "scan")


def test_heldout_file_is_refused_without_the_flag():
    assert ev.main(["--file", "tests/data/agents_heldout.json", "--model", "x"]) == 2


def test_d_cases_pass_with_the_template_wording(tmp_path, monkeypatch):
    def no_model(*a, **k):
        raise ConnectionError("no model in tests")
    monkeypatch.setattr("callverse.agents.agent_d.llm", SimpleNamespace(chat=no_model))
    dev = json.loads((ROOT / "tests/dev/agents_cases.json").read_text(encoding="utf-8"))["cases"]
    for case in [c for c in dev if c["agent"] == "D"]:
        out = ev.run_case(case, tmp_path)
        assert out["pass"], (case["id"], out["fails"])
        assert out["notes_by_model"] == 0


def test_override_wrapper_passes_extra_keywords(monkeypatch):
    """T26: the real run_tool takes booking_type (T14f); the bench wrapper must pass it through, not crash."""
    seen = {}

    def fake_run_tool(agent, name, args, chat_fn=None, company="shopnova", **kwargs):
        seen.update(kwargs)
        return {"status": "ok"}
    monkeypatch.setattr(ev.registry, "run_tool", fake_run_tool)
    wrapped = ev.with_overrides({"get_order": {"status": "late"}})
    out = wrapped("B", "get_order", {"order_id": 1}, company="atlas", booking_type="flight")
    assert seen == {"booking_type": "flight"} and out == {"status": "late"}
