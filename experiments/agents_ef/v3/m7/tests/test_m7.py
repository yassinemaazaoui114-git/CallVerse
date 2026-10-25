"""M7 (Agent F quality & knowledge) tests. Hand-written trace lines in the prototype's format; no model, no API.

    python -m pytest v3/m7/tests -q          (from experiments/agents_ef)
"""

import copy
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from v3.m7 import feedback_e, quality, rule_audit  # noqa: E402
from v3.m7.conversations import dialogue_text, load_conversations, parse_trace  # noqa: E402
from v3.m7.satisfaction import ReviewCalibrator  # noqa: E402

T0 = "2026-10-09T09:00:00.000"


def line(step, actor, data, t=T0):
    return json.dumps({"time": t, "run_id": "r1", "step": step, "actor": actor, "data": data})


def refund_trace(claimed_days=8, data_days=2, reply="Your refund of 59.90 TND is approved.", outcome="approve",
                 main_reason="refund_request", delivered=False, status="shipped", extra=()):
    facts = {"days_late": claimed_days, "delivered": False, "paid": 59.9, "refunded_total": 0.0}
    rows = [line("intake_start", "intake", {"ticket_id": "T-1", "text": "Order 4512 is late. I want my money back."}),
            line("intake_ticket", "intake", {"ticket_id": "T-1", "order_id": 4512, "main_reason": main_reason,
                                             "priority_label": "high", "emotion": {"label": "anger"}}),
            line("tool_call", "registry", {"agent": "B", "tool": "get_order", "args": {"order_id": 4512},
                                           "result": {"id": 4512, "paid": 59.9, "status": status}}),
            line("tool_call", "registry", {"agent": "A", "tool": "get_tracking", "args": {"order_id": 4512},
                                           "result": {"days_late": data_days, "delivered": delivered,
                                                      "days_since_delivery": None, "status": status}}),
            line("tool_call", "registry", {"agent": "B", "tool": "get_refunds", "args": {"order_id": 4512},
                                           "result": {"refunded_total": 0}}),
            line("proposal", "proposal_tools", {"order_id": 4512, "amount": 59.9, "rule_id": "R-REF-03",
                                                "facts_used": facts, "user_confirmed": True, "user_quote": "x"}),
            line("coordinator_check", "coordinator", {"check": "facts_from_data", "rule_id": None, "facts": {},
                                                      "result": "pass", "detail": f"agent claimed: {facts}"}),
            *extra,
            line("coordinator_decision", "coordinator", {"outcome": outcome, "rule_id": "R-REF-03"}),
            line("pipeline_done", "pipeline", {"route": {"agent": "B"}, "decision": {"outcome": outcome,
                                               "rule_id": "R-REF-03"}, "final_reply": reply, "reply_source": "slm"},
                 t="2026-10-09T09:00:04.500")]
    return "\n".join(rows) + "\n"


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_parser_builds_one_closed_conversation_with_refs(tmp_path):
    p = write(tmp_path, "c1.jsonl", refund_trace())
    [c] = parse_trace(p)
    assert c["conversation_id"] == "c1" and c["seconds"] == 4.5
    assert c["ticket"]["order_id"] == 4512 and len(c["tool_calls"]) == 3
    assert c["tool_calls"][1]["ref"] == "c1.jsonl:4"
    assert dialogue_text(c).startswith("Customer: Order 4512") and "Agent: Your refund" in dialogue_text(c)


def test_open_conversation_is_not_returned(tmp_path):
    text = "\n".join(refund_trace().splitlines()[:-1]) + "\n"        # no pipeline_done yet
    assert parse_trace(write(tmp_path, "open.jsonl", text)) == []


def test_claim_that_contradicts_tool_data_is_flagged_with_both_refs(tmp_path):
    write(tmp_path, "c.jsonl", refund_trace(8, 2))
    [c] = load_conversations(tmp_path)
    r = quality.review(c)
    f = [x for x in r["flags"] if x["code"] == "claim_contradicts_data"]
    assert f and f[0]["evidence"]["claimed"] == 8 and f[0]["evidence"]["data"] == 2
    assert f[0]["evidence"]["data_ref"] == "c.jsonl:4" and r["grade"] == "fail"


def test_grounded_clean_conversation_gets_no_flag(tmp_path):
    [c] = parse_trace(write(tmp_path, "c.jsonl", refund_trace(8, 8)))
    r = quality.review(c)
    assert r["flags"] == [] and r["grade"] == "ok" and r["resolution"] == "resolved"


def test_leak_and_language_mismatch_are_flagged(tmp_path):
    t = refund_trace(8, 8, reply="Proposal P-0001 approved by the Coordinator under R-REF-03.")
    t = t.replace("Order 4512 is late. I want my money back.", "Bonjour, ma commande 4512 est en retard, je veux être remboursé.")
    [c] = parse_trace(write(tmp_path, "c.jsonl", t))
    codes = {f["code"] for f in quality.review(c)["flags"]}
    assert {"reply_leak", "reply_language_mismatch"} <= codes


def test_missed_entitlement_when_refund_due_but_not_given(tmp_path):
    [c] = parse_trace(write(tmp_path, "c.jsonl", refund_trace(8, 8, outcome="info")))
    assert "missed_entitlement" in {f["code"] for f in quality.review(c)["flags"]}
    [c2] = parse_trace(write(tmp_path, "d.jsonl", refund_trace(2, 2, outcome="info")))   # 2 days late: not due
    assert "missed_entitlement" not in {f["code"] for f in quality.review(c2)["flags"]}


def test_missing_rule_send_back_and_process_events(tmp_path):
    extra = (line("coordinator_check", "coordinator", {"check": "rule_exists", "rule_id": "R-REF-02",
                                                       "result": "fail"}),
             line("coordinator_decision", "coordinator", {"outcome": "send_back", "reason": "rule R-REF-02 does not exist"}),
             line("send_back_to_agent", "pipeline", {"note": "sent back"}),
             line("rule_not_searched", "coordinator", {"rule_id": "R-REF-03"}),
             line("pipeline_error", "pipeline", {"error": "RuntimeError: 503"}))
    [c] = parse_trace(write(tmp_path, "c.jsonl", refund_trace(8, 8, extra=extra)))
    codes = {f["code"] for f in quality.review(c)["flags"]}
    assert {"cited_missing_rule", "sent_back", "rule_not_searched", "pipeline_error"} <= codes


def test_missing_rule_in_a_refused_proposal_is_caught(tmp_path):
    extra = (line("proposal_refused", "proposal_tools", {"fields": {"order_id": 4512, "rule_id": "R-REF-02"},
                                                         "problems": ["amount must be > 0"]}),)
    [c] = parse_trace(write(tmp_path, "c.jsonl", refund_trace(8, 8, extra=extra)))
    f = [x for x in quality.review(c)["flags"] if x["code"] == "cited_missing_rule"]
    assert f and f[0]["evidence"] == {"rule_id": "R-REF-02", "ref": "c.jsonl:8"}


def test_review_does_not_modify_its_input(tmp_path):
    [c] = parse_trace(write(tmp_path, "c.jsonl", refund_trace()))
    before = copy.deepcopy(c)
    quality.review(c)
    assert c == before


# ---------------- rule / knowledge audit ----------------

def test_static_audit_on_real_policies_finds_no_inconsistency():
    kinds = {f["kind"] for f in rule_audit.static_audit()}
    assert "inconsistency" not in kinds and "unverifiable" not in kinds and "stale_reference" not in kinds
    assert "knowledge_gap" in kinds              # delivered-late orders past the return window: no rule


def test_static_audit_flags_text_condition_mismatch_and_unknown_fact():
    rules = [{"id": "R-RET-01", "title": "t", "text": "Returns within 14 days of delivery.",
              "condition": "delivered and days_since_delivery <= 30"},
             {"id": "R-X-01", "title": "t", "text": "VIP clients get 10 TND.", "condition": "vip_level > 10"}]
    flags = rule_audit.static_audit(rules)
    assert any(f["kind"] == "inconsistency" and f["rule_id"] == "R-RET-01" for f in flags)
    assert any(f["kind"] == "unverifiable" and f["rule_id"] == "R-X-01" for f in flags)


def test_coordinator_fact_names_are_read_from_code():
    assert {"days_late", "delivered", "paid", "refunded_total", "proof_received", "amount"} <= \
        rule_audit.coordinator_fact_names()


def test_usage_audit_turns_repeated_missing_rule_into_stale_reference():
    reviews = [{"conversation_id": f"c{i}", "rule_id": None, "flags": [
        {"code": "cited_missing_rule", "evidence": {"rule_id": "R-REF-02", "ref": f"c{i}.jsonl:9"}}]}
        for i in range(6)]
    flags = rule_audit.usage_audit(reviews, [], None)
    [f] = [f for f in flags if f["kind"] == "stale_reference"]
    assert f["rule_id"] == "R-REF-02" and f["severity"] == "high" and f["evidence"]["n"] == 6


# ---------------- feedback to Agent E ----------------

GOOD_CARD = {"model": "m", "label_type": "genuine_customer_rating", "domain": "support_conversation",
             "test_n": 1000, "mae": 0.5, "mae_mean_baseline": 0.8, "spearman_ci_low": 0.45}


def test_gate_blocks_annotations_and_product_stars():
    assert feedback_e.gate({**GOOD_CARD, "label_type": "human_annotation"})["usable_for_reward"] is False
    assert feedback_e.gate({**GOOD_CARD, "domain": "product_review"})["usable_for_reward"] is False
    assert feedback_e.gate(None)["usable_for_reward"] is False


def test_gate_passes_only_with_all_conditions():
    assert feedback_e.gate(GOOD_CARD, coverage=0.99)["usable_for_reward"] is True
    assert feedback_e.gate(GOOD_CARD, coverage=0.5)["usable_for_reward"] is False
    assert feedback_e.gate({**GOOD_CARD, "spearman_ci_low": 0.1})["usable_for_reward"] is False
    assert feedback_e.gate({**GOOD_CARD, "mae": 0.9})["usable_for_reward"] is False


def test_feedback_units_match_env_v3_shortfall_and_steps():
    reviews = [{"conversation_id": c, "route": "B", "priority": "high", "resolution": "resolved"} for c in "abc"]
    ends = {"a": "2026-10-09T09:01:00", "b": "2026-10-09T09:04:59", "c": "2026-10-09T09:05:00"}
    recs, g = feedback_e.per_conversation(reviews, {"a": 5.0, "b": 1.0, "c": 3.0}, ends, GOOD_CARD)
    assert [r["shortfall"] for r in recs] == [0.0, 1.0, 0.5] and all(r["use"] == "reward" for r in recs)
    steps = feedback_e.aggregate(recs)
    assert [(s["step_start"][-8:], s["n"], s["shortfall_sum"]) for s in steps] == [("09:00:00", 2, 1.0),
                                                                                    ("09:05:00", 1, 0.5)]
    recs2, _ = feedback_e.per_conversation(reviews, {"a": 4.0}, ends, None)
    assert all(r["use"] == "kpi_only" for r in recs2) and recs2[1]["shortfall"] is None


# ---------------- learning from the few reviews ----------------

def test_review_calibrator_needs_enough_reviews_and_fixes_a_monotone_bias():
    rng = np.random.default_rng(0)
    true = rng.integers(1, 6, 400).astype(float)                   # SYNTHETIC check of the mechanism only
    raw = 2.0 + 0.3 * true + rng.normal(0, 0.2, 400)               # compressed, shifted model scores
    small = ReviewCalibrator(min_reviews=50).fit(raw[:20], true[:20])
    assert small["used"] is False
    cal = ReviewCalibrator(min_reviews=50)
    rep = cal.fit(raw, true)
    assert rep["used"] is True and rep["cv_mae_calibrated"] < rep["cv_mae_raw"]
    assert np.all((cal.apply(raw) >= 1) & (cal.apply(raw) <= 5))


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
