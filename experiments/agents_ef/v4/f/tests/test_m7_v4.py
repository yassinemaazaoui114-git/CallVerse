"""Agent F v4 (M7) tests. Hand-written trace lines in the prototype's format (callverse/trace.py); no API, no LLM.

    python -m pytest v4/f/tests -q          (from experiments/agents_ef)

For every one of the 14 quality checks: a POSITIVE case (flag raised), a NEGATIVE case (clean, no flag) and at
least one BOUNDARY case (the edge of the definition). Plus: evidence refs, rule audit separation, satisfaction
validity, F -> E decision, and the AgentF interface.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from v3.m7 import quality as q3  # noqa: E402
from v4.f.agent_f import AgentF, strip_private  # noqa: E402
from v4.f.m7 import feedback_v4, rule_audit_v4, satisfaction_v4  # noqa: E402
from v4.f.m7.conversations_v4 import parse_trace_v4  # noqa: E402
from v4.f.m7.quality_v4 import CODES, review_v4, verify_refs  # noqa: E402

T0, T1 = "2026-10-09T09:00:00.000", "2026-10-09T09:00:04.000"
REPLY_OK = "Your refund of 59.90 TND is approved. Your order 4512 is now cancelled."


def L(step, actor, data, t=T0):
    return {"time": t, "run_id": "r1", "step": step, "actor": actor, "data": data}


def refund_conv(days_tracking=8, claimed=None, paid=59.9, refunded=0, status="shipped", outcome="approve",
                action="refund", reply=REPLY_OK, reply_source="slm", text="Order 4512 is late. I want my money back.",
                main_reason="refund_request", ask_agent=True, rule_id="R-REF-03", before_done=(), after_ask=(),
                proposal=True, delivered=False):
    """A refund conversation: Agent B reads the order, asks Agent A for the delivery facts, reads refunds,
    proposes; the Coordinator re-reads the facts and decides."""
    claimed = claimed if claimed is not None else {"days_late": days_tracking, "delivered": delivered, "paid": paid,
                                                   "refunded_total": refunded}
    track = {"days_late": days_tracking, "delivered": delivered, "days_since_delivery": None, "status": status}
    rows = [L("intake_start", "intake", {"ticket_id": "T-1", "text": text}),
            L("intake_ticket", "intake", {"ticket_id": "T-1", "order_id": 4512, "main_reason": main_reason,
                                          "priority_label": "high", "emotion": {"label": "anger"}}),
            L("agent_start", "agent_B", {"agent": "Agent B"}),
            L("tool_call", "registry", {"agent": "B", "tool": "get_order", "args": {"order_id": 4512},
                                        "result": {"id": 4512, "paid": paid, "status": status}})]
    if ask_agent:
        rows += [L("agent_start", "agent_A", {"agent": "Agent A"}),
                 L("tool_call", "registry", {"agent": "A", "tool": "get_tracking", "args": {"order_id": 4512},
                                             "result": track}),
                 L("tool_call", "registry", {"agent": "B", "tool": "ask_agent", "args": {"agent": "A"},
                                             "result": {"agent": "A", "answer": "x", "facts": track}})]
    rows += list(after_ask)
    rows += [L("tool_call", "registry", {"agent": "B", "tool": "get_refunds", "args": {"order_id": 4512},
                                         "result": {"refunded_total": refunded}})]
    if proposal:
        reread = {"order_id": 4512, "status": status, "paid": paid, "refunded_total": refunded,
                  "days_late": days_tracking, "delivered": delivered, "days_since_delivery": None,
                  "proof_received": False, "amount": paid}
        rows += [L("proposal", "proposal_tools", {"order_id": 4512, "amount": paid, "rule_id": rule_id,
                                                  "facts_used": claimed, "user_confirmed": True, "user_quote": "x"}),
                 L("tool_call", "registry", {"agent": "B", "tool": "propose_refund", "args": {},
                                             "result": {"status": "submitted to Coordinator"}}),
                 L("coordinator_check", "coordinator", {"check": "facts_from_data", "rule_id": None, "facts": reread,
                                                        "result": "pass", "detail": f"agent claimed: {claimed}"})]
    rows += list(before_done)
    rows += [L("coordinator_decision", "coordinator", {"outcome": outcome, "action": action, "rule_id": rule_id}),
             L("pipeline_done", "pipeline", {"route": {"agent": "B"}, "decision": {"outcome": outcome, "action": action,
                                                                                    "rule_id": rule_id},
                                             "final_reply": reply, "reply_source": reply_source}, t=T1)]
    return rows


def parse(tmp_path, rows, name="c.jsonl"):
    p = tmp_path / name
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return parse_trace_v4(p)


def one(tmp_path, rows):
    [c] = parse(tmp_path, rows)
    return c, review_v4(c)


def codes(r):
    return [f["code"] for f in r["flags"]]


def flag(r, code):
    return [f for f in r["flags"] if f["code"] == code]


# ---------------- the clean case (negative for every check) ----------------

def test_clean_conversation_has_no_flag_and_all_14_codes_are_listed(tmp_path):
    c, r = one(tmp_path, refund_conv())
    assert r["flags"] == [] and r["grade"] == "ok" and len(CODES) == 14


# ---------------- 1 pipeline_error ----------------

def test_pipeline_error_positive_and_does_not_leak_to_other_conversation_in_same_file(tmp_path):
    first = refund_conv()
    second = refund_conv(outcome="escalate", action=None,
                         before_done=[L("pipeline_error", "pipeline", {"error": "RuntimeError: 503"})])
    c1, c2 = parse(tmp_path, first + second)
    assert "pipeline_error" not in codes(review_v4(c1))                 # boundary: same file, other ticket
    f = flag(review_v4(c2), "pipeline_error")
    assert f and f[0]["evidence"]["error"] == "RuntimeError: 503"


# ---------------- 2 claim_false ----------------

def test_claim_false_positive_negative_and_float_boundary(tmp_path):
    _, r = one(tmp_path, refund_conv(days_tracking=2, claimed={"days_late": 8, "delivered": False}))
    f = flag(r, "claim_false")
    assert f and f[0]["evidence"]["claimed"] == 8 and f[0]["evidence"]["data"] == 2
    assert f[0]["evidence"]["agent_had_this_fact"] is True and r["grade"] == "fail"
    assert "claim_unsupported" not in codes(r)                          # B HAD the fact (via ask_agent): false, not unsupported
    _, r = one(tmp_path, refund_conv(claimed={"days_late": 8, "delivered": False, "paid": 59.905}))
    assert "claim_false" not in codes(r)                                # boundary: < 0.01 TND is the same amount
    _, r = one(tmp_path, refund_conv(claimed={"days_late": 8, "delivered": False, "paid": 59.92}))
    assert "claim_false" in codes(r)                                    # boundary: 0.02 TND differs


def test_numbers_written_as_strings_are_the_same_claim_v4_1(tmp_path):
    _, r = one(tmp_path, refund_conv(claimed={"days_late": "8", "delivered": "false", "paid": "59.90"}))
    assert "claim_false" not in codes(r)
    _, r = one(tmp_path, refund_conv(claimed={"days_late": "9", "delivered": "False"}))
    f = flag(r, "claim_false")
    assert len(f) == 1 and f[0]["evidence"]["fact"] == "days_late" and f[0]["evidence"]["claimed_as_string"]
    _, r = one(tmp_path, refund_conv(claimed={"days_late": 8, "delivered": "not yet"}))
    assert "claim_false" in codes(r)                                    # a non-boolean word stays a mismatch


def test_claim_false_bool_boundary(tmp_path):
    _, r = one(tmp_path, refund_conv(claimed={"days_late": 8, "delivered": 0}))
    assert "claim_false" in codes(r)                                    # 0 is not the boolean False the tool gave


# ---------------- 3 claim_unsupported ----------------

def test_claim_unsupported_when_the_agent_never_got_the_fact(tmp_path):
    _, r = one(tmp_path, refund_conv(ask_agent=False))                  # B never asked A: no days_late / delivered
    f = {x["evidence"]["fact"]: x for x in flag(r, "claim_unsupported")}
    assert set(f) == {"days_late", "delivered"} and f["days_late"]["evidence"]["later_data_agrees"] is True
    assert "claim_false" not in codes(r)                                # right by luck: unsupported, not false


def test_claim_unsupported_boundaries_result_after_claim_and_earlier_run(tmp_path):
    rows = refund_conv(ask_agent=False)
    late = L("tool_call", "registry", {"agent": "B", "tool": "get_tracking", "args": {},
                                       "result": {"days_late": 8, "delivered": False}})
    i = next(k for k, x in enumerate(rows) if x["step"] == "coordinator_check")
    _, r = one(tmp_path, rows[:i + 1] + [late] + rows[i + 1:])          # fact arrives AFTER the claim
    assert {x["evidence"]["fact"] for x in flag(r, "claim_unsupported")} == {"days_late", "delivered"}
    # fact given in an EARLIER run of B; a new run (send-back) starts without memory
    rows = refund_conv()
    j = next(k for k, x in enumerate(rows) if x["step"] == "proposal")
    rows = rows[:j] + [L("agent_start", "agent_B", {"agent": "Agent B"})] + rows[j:]
    _, r = one(tmp_path, rows)
    assert {"days_late", "delivered", "paid", "refunded_total"} == \
        {x["evidence"]["fact"] for x in flag(r, "claim_unsupported")}


def test_claim_unsupported_negative_when_the_tool_returned_it(tmp_path):
    _, r = one(tmp_path, refund_conv())
    assert "claim_unsupported" not in codes(r)


# ---------------- 4 cited_missing_rule ----------------

def test_cited_missing_rule_positive_negative_and_refused_proposal_boundary(tmp_path):
    _, r = one(tmp_path, refund_conv(rule_id="R-REF-02", outcome="send_back"))
    assert flag(r, "cited_missing_rule")[0]["evidence"]["rule_id"] == "R-REF-02"
    _, r = one(tmp_path, refund_conv(rule_id="R-REF-03"))
    assert "cited_missing_rule" not in codes(r)
    refused = L("proposal_refused", "proposal_tools", {"fields": {"order_id": 4512, "rule_id": "R-XYZ-09"},
                                                       "problems": ["rule_id R-XYZ-09 does not exist"]})
    _, r = one(tmp_path, refund_conv(after_ask=[refused]))
    assert flag(r, "cited_missing_rule")[0]["evidence"]["rule_id"] == "R-XYZ-09"
    refused_none = L("proposal_refused", "proposal_tools", {"fields": {"order_id": 4512, "rule_id": None},
                                                            "problems": ["rule_id missing"]})
    _, r = one(tmp_path, refund_conv(after_ask=[refused_none]))
    assert "cited_missing_rule" not in codes(r)                          # boundary: no rule id at all


# ---------------- 5 sent_back ----------------

def test_sent_back_zero_one_two(tmp_path):
    sb = lambda: [L("coordinator_decision", "coordinator", {"outcome": "send_back", "reason": "amount too high"}),
                  L("send_back_to_agent", "pipeline", {"note": "x"})]
    _, r = one(tmp_path, refund_conv())
    assert "sent_back" not in codes(r)
    _, r = one(tmp_path, refund_conv(before_done=sb()))
    assert flag(r, "sent_back")[0]["severity"] == "medium"
    _, r = one(tmp_path, refund_conv(before_done=sb() + sb()))
    assert flag(r, "sent_back")[0]["severity"] == "high"                # boundary: 2 send-backs -> high


# ---------------- 6 escalated ----------------

def test_escalated_positive_negative(tmp_path):
    _, r = one(tmp_path, refund_conv(outcome="escalate", reply="Your case needs an extra check."))
    assert "escalated" in codes(r) and r["resolution"] == "escalated"
    _, r = one(tmp_path, refund_conv(outcome="layer3"))
    assert "escalated" not in codes(r)                                  # boundary: finance is not a human escalation


# ---------------- 7 rule_not_searched / 8 agent_answered_without_tools / 14 handover_ignored ----------------

@pytest.mark.parametrize("step,code", [("rule_not_searched", "rule_not_searched"),
                                       ("agent_retry", "agent_answered_without_tools"),
                                       ("handover_ignored", "handover_ignored")])
def test_process_events_positive_negative(tmp_path, step, code):
    ev = L(step, "pipeline", {"rule_id": "R-REF-03", "first_answer": "order number?", "reason": "A has a decision"})
    _, r = one(tmp_path, refund_conv(before_done=[ev]))
    assert code in codes(r) and flag(r, code)[0]["severity"] == "low"
    _, r = one(tmp_path, refund_conv())
    assert code not in codes(r)


# ---------------- 9 proposal_malformed ----------------

def test_proposal_malformed_one_two_none(tmp_path):
    ref = lambda: L("proposal_refused", "proposal_tools", {"fields": {"order_id": 4512, "rule_id": "R-REF-03"},
                                                           "problems": ["amount must be > 0"]})
    _, r = one(tmp_path, refund_conv(after_ask=[ref()]))
    assert len(flag(r, "proposal_malformed")) == 1
    _, r = one(tmp_path, refund_conv(after_ask=[ref(), ref()]))
    assert len(flag(r, "proposal_malformed")) == 2                      # boundary: one flag per refusal
    _, r = one(tmp_path, refund_conv())
    assert "proposal_malformed" not in codes(r)


# ---------------- 10 missed_entitlement ----------------

def test_missed_entitlement_positive_and_day_boundary(tmp_path):
    _, r = one(tmp_path, refund_conv(days_tracking=8, outcome="info", action="status", proposal=False))
    assert "missed_entitlement" in codes(r)
    _, r = one(tmp_path, refund_conv(days_tracking=6, outcome="info", action="status", proposal=False))
    assert "missed_entitlement" in codes(r)                             # boundary: 6 > 5
    _, r = one(tmp_path, refund_conv(days_tracking=5, outcome="info", action="status", proposal=False))
    assert "missed_entitlement" not in codes(r)                         # boundary: 5 is not > 5


def test_missed_entitlement_negatives(tmp_path):
    for kw in ({"refunded": 59.9}, {"status": "cancelled"}, {"outcome": "escalate"}, {"outcome": "approve"},
               {"main_reason": "late_delivery"}):
        args = {"days_tracking": 8, "outcome": "info", "action": "status", "proposal": False, **kw}
        _, r = one(tmp_path, refund_conv(**args))
        assert "missed_entitlement" not in codes(r), kw


def test_missed_entitlement_not_raised_while_waiting_for_the_client_v4_change(tmp_path):
    c, r = one(tmp_path, refund_conv(days_tracking=8, outcome="ask_user", action="refund"))
    assert "missed_entitlement" in codes(q3.review(c))                  # V3 false positive (refund WAS offered)
    assert "missed_entitlement" not in codes(r)


# ---------------- 11 reply_leak ----------------

def test_reply_leak_positive_negative_and_word_boundary(tmp_path):
    for reply in ("Proposal P-0001 approved by the Coordinator.", "Approved under R-REF-03.", "Sent for checking.",
                  "Our agent approved it."):
        _, r = one(tmp_path, refund_conv(reply=reply))
        assert "reply_leak" in codes(r), reply
    _, r = one(tmp_path, refund_conv())
    assert "reply_leak" not in codes(r)
    _, r = one(tmp_path, refund_conv(reply="Your travel agency booking is unrelated; your refund is approved."))
    assert "reply_leak" not in codes(r)                                 # boundary: 'agency' is not 'agent'
    _, r = one(tmp_path, refund_conv(reply="Tracking number RP305110, refund approved."))
    assert "reply_leak" not in codes(r)                                 # boundary: tracking ids are not rule ids
    _, r = one(tmp_path, refund_conv(reply="The reagent kit refund is approved."))
    assert "reply_leak" in codes(r)                                     # known substring false-positive risk (low)


# ---------------- 12 slm_fallback_template ----------------

def test_slm_fallback_template_positive_negative(tmp_path):
    _, r = one(tmp_path, refund_conv(reply_source="template"))
    assert "slm_fallback_template" in codes(r)
    for src in ("slm", "slm_retry"):
        _, r = one(tmp_path, refund_conv(reply_source=src))
        assert "slm_fallback_template" not in codes(r)


# ---------------- 13 reply_language_mismatch ----------------

def test_reply_language_mismatch_positive_negative_and_three_word_boundary(tmp_path):
    _, r = one(tmp_path, refund_conv(text="Bonjour, ma commande 4512 est en retard, je veux être remboursé."))
    assert "reply_language_mismatch" in codes(r)
    _, r = one(tmp_path, refund_conv(text="Bonjour, ma commande 4512 est en retard.",
                                     reply="Votre remboursement de 59.90 TND est approuvé, merci."))
    assert "reply_language_mismatch" not in codes(r)
    _, r = one(tmp_path, refund_conv(text="Bonjour, ma commande 4512 ?"))     # exactly 3 French words
    assert "reply_language_mismatch" in codes(r)
    _, r = one(tmp_path, refund_conv(text="Bonjour, commande 4512 late."))    # 2 French words
    assert "reply_language_mismatch" not in codes(r)


# ---------------- evidence refs ----------------

def test_every_ref_of_every_positive_case_points_to_the_right_line(tmp_path):
    rows = refund_conv(days_tracking=2, claimed={"days_late": 8, "delivered": False}, reply="P-0001 ok",
                       reply_source="template", text="Bonjour, ma commande 4512 est en retard",
                       before_done=[L("rule_not_searched", "coordinator", {"rule_id": "R-REF-03"}),
                                    L("send_back_to_agent", "pipeline", {"note": "x"})])
    c, r = one(tmp_path, rows)
    refs = verify_refs(c, r)
    assert len(refs) >= 6 and all(x["ok"] for x in refs)
    claim = next(x for x in refs if x["code"] == "claim_false" and x["key"] == "data_ref")
    assert claim["step_at_ref"] == "tool_call"


def test_tampered_ref_is_detected(tmp_path):
    c, r = one(tmp_path, refund_conv(days_tracking=2, claimed={"days_late": 8}))
    f = flag(r, "claim_false")[0]
    f["evidence"]["data_ref"] = f"{c['file']}:1"                        # line 1 is intake_start
    assert not all(x["ok"] for x in verify_refs(c, r))
    f["evidence"]["data_ref"] = "other.jsonl:4"                         # wrong file
    assert not all(x["ok"] for x in verify_refs(c, r))


def test_review_does_not_modify_its_input(tmp_path):
    import copy
    [c] = parse(tmp_path, refund_conv(days_tracking=2, claimed={"days_late": 8}))
    before = copy.deepcopy(c)
    review_v4(c)
    assert c == before


# ---------------- rule / knowledge audit ----------------

def test_audit_separates_consistency_from_freshness_on_real_policies():
    a = rule_audit_v4.audit_v4([], [], "2026-10-09")
    assert a["internal_consistency"] == []
    assert {f["kind"] for f in a["coverage"]} == {"knowledge_gap"}
    assert sum(f["kind"] == "unreviewed" for f in a["governance"]) == 8
    assert a["freshness"]["status"] == "NOT_CHECKABLE"
    assert all(p["status"] == "NOT_CHECKABLE" for p in a["freshness"]["per_rule"]) and len(a["freshness"]["per_rule"]) == 8
    assert all(f["false_positive_risk"] for f in rule_audit_v4.all_flags(a))


def test_dated_rules_get_governance_flags_only_when_dates_exist():
    rules = [{"id": "R-RET-01", "title": "t", "text": "Returns within 14 days of delivery.",
              "condition": "delivered and days_since_delivery <= 14", "valid_until": "2026-01-01"},
             {"id": "R-DEL-02", "title": "t", "text": "1 to 5 days late.", "condition": "1 <= days_late <= 5 and "
              "not delivered", "last_reviewed": "2024-05-01"},
             {"id": "R-REF-03", "title": "t", "text": "more than 5 days", "condition": "days_late > 5 and not delivered",
              "last_reviewed": "2026-09-01"}]
    a = rule_audit_v4.audit_v4([], [], "2026-10-09", policies=rules)
    kinds = {(f["kind"], f["rule_id"]) for f in a["governance"]}
    assert ("expired", "R-RET-01") in kinds and ("review_overdue", "R-DEL-02") in kinds
    assert not any(f["rule_id"] == "R-REF-03" for f in a["governance"])        # boundary: reviewed 38 days ago
    assert a["freshness"]["status"] == "NOT_CHECKABLE"                          # dates are governance, not truth


def test_text_condition_mismatch_is_internal_consistency():
    rules = [{"id": "R-RET-01", "title": "t", "text": "Returns within 14 days.",
              "condition": "delivered and days_since_delivery <= 30"}]
    a = rule_audit_v4.audit_v4([], [], "2026-10-09", policies=rules)
    kinds = {(f["kind"], f["rule_id"]) for f in a["internal_consistency"]}
    assert ("inconsistency", "R-RET-01") in kinds
    assert ("stale_reference", "R-REF-03") in kinds          # the code still uses rules missing from this file


def test_freshness_with_a_source_is_not_claimed_checked():
    a = rule_audit_v4.audit_v4([], [], "2026-10-09",
                               sources=[{"rule_id": "R-REF-03", "source": "doc-1", "date": "2026-01-01"}])
    per = {p["rule_id"]: p["status"] for p in a["freshness"]["per_rule"]}
    assert per["R-REF-03"] == "SOURCE_AVAILABLE_NOT_COMPARED" and per["R-DEL-01"] == "NOT_CHECKABLE"


def test_unvalidated_scores_never_create_rule_flags():
    reviews = [{"conversation_id": f"c{i}", "rule_id": "R-REF-03" if i < 25 else "R-NOT-01", "flags": []}
               for i in range(50)]
    scores = {f"c{i}": (1.0 if i < 25 else 5.0) for i in range(50)}
    a = rule_audit_v4.audit_v4(reviews, [], "2026-10-09", scores_valid=False, scores=scores)
    assert a["u5_predicted_satisfaction_per_rule"].startswith("SKIPPED")
    assert not any("predicted satisfaction" in f["what"] for f in a["usage"])
    b = rule_audit_v4.audit_v4(reviews, [], "2026-10-09", scores_valid=True, scores=scores)
    assert any("predicted satisfaction" in f["what"] for f in b["usage"])


# ---------------- satisfaction validity ----------------

class FakeModel:
    def scores(self, texts):
        return [3.0 + 0.1 * (i % 3) for i in range(len(texts))]


def fake_scorer(langs=("en", "zh")):
    return satisfaction_v4.Scorer(FakeModel(), "fake", "0" * 64, {"model": "fake", "languages_validated": list(langs),
                                                                    "label_type": "human_annotation"})


@pytest.mark.parametrize("text,lang", [("Where is my order 4512, please?", "en"),
                                       ("Bonjour, où est ma commande 4512 ?", "fr"),
                                       ("Ma commande est en retard", "fr"),
                                       ("أين طلبي رقم 4512", "ar"), ("我的订单在哪里", "zh"), ("4512 ?!", "unknown")])
def test_detect_language(text, lang):
    assert satisfaction_v4.detect_language(text) == lang


def test_french_is_withheld_not_silently_scored(tmp_path):
    c_en = parse(tmp_path, refund_conv(), "en.jsonl")[0]
    c_fr = parse(tmp_path, refund_conv(text="Bonjour, ma commande 4512 est en retard"), "fr.jsonl")[0]
    recs = satisfaction_v4.score_with_validity([c_en, c_fr], fake_scorer(), card={"corpus": "uss"})
    en, fr = recs
    assert en["validity"] == "indicative_out_of_domain" and en["predicted_satisfaction"] is not None
    assert en["usable_for"] == ["kpi_indicative"] and any("turns" in x for x in en["reasons"])
    assert fr["validity"] == "withheld_language_not_validated" and fr["predicted_satisfaction"] is None
    assert fr["usable_for"] == []
    forced = satisfaction_v4.score_with_validity([c_fr], fake_scorer(), None, score_unvalidated_languages=True)[0]
    assert forced["predicted_satisfaction"] is not None and forced["validity"].startswith("unvalidated_language")
    cv = satisfaction_v4.score_with_validity([c_en], fake_scorer(),
                                             {"corpus": "callverse", "domain": "support_conversation"})[0]
    assert cv["validity"] == "validated" and cv["usable_for"] == ["kpi"]
    none = satisfaction_v4.score_with_validity([c_en], None)[0]
    assert none["validity"] == "no_score" and none["predicted_satisfaction"] is None


# ---------------- F -> E ----------------

GOOD = {"model": "m", "label_type": "genuine_customer_rating", "domain": "support_conversation", "corpus": "callverse",
        "test_n": 1000, "mae": 0.5, "mae_mean_baseline": 0.8, "spearman_ci_low": 0.45}


def test_e_reward_false_with_reasons_for_annotator_card_and_no_card():
    recs = [{"conversation_id": "a", "validity": "indicative_out_of_domain", "predicted_satisfaction": 3.0}]
    d = feedback_v4.e_reward_decision({**GOOD, "label_type": "human_annotation", "domain": "task_oriented_dialogue"},
                                      recs)
    assert d["e_reward_allowed"] is False and any("label_type" in x for x in d["reasons"])
    assert any("domain" in x for x in d["reasons"]) and any("coverage" in x for x in d["reasons"])
    d0 = feedback_v4.e_reward_decision(None, recs)
    assert d0["e_reward_allowed"] is False and d0["reasons"]


def test_e_reward_allowed_only_with_good_card_and_validated_coverage():
    ok = [{"conversation_id": c, "validity": "validated", "predicted_satisfaction": 4.0} for c in "abcdefghijklmnopqrst"]
    assert feedback_v4.e_reward_decision(GOOD, ok)["e_reward_allowed"] is True
    one_fr = ok[:-1] + [{"conversation_id": "t", "validity": "withheld_language_not_validated",
                         "predicted_satisfaction": None}]
    d = feedback_v4.e_reward_decision(GOOD, one_fr)                      # coverage 19/20 = 0.95: boundary passes
    assert d["e_reward_allowed"] is True
    two_fr = one_fr[:-2] + [dict(one_fr[-1], conversation_id="s"), one_fr[-1]]
    assert feedback_v4.e_reward_decision(GOOD, two_fr)["e_reward_allowed"] is False    # 18/20 = 0.90
    rows = feedback_v4.per_conversation_v4([{"conversation_id": "t", "route": "B"}], one_fr, {}, d)
    assert rows[0]["e_reward_eligible"] is False and rows[0]["use"] == "kpi_only"


# ---------------- AgentF interface ----------------

def test_agent_f_process_and_owner_report_without_model(tmp_path):
    p = tmp_path / "t1.jsonl"
    rows = refund_conv(days_tracking=2, claimed={"days_late": 8, "delivered": False}) + refund_conv()
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    f = AgentF.load({"scorer": "none"})
    outs = f.process(p)
    assert isinstance(outs, list) and len(outs) == 2
    o = outs[0]
    for k in ("predicted_satisfaction", "satisfaction_validity", "quality_flags", "rule_knowledge_warnings",
              "e_reward_eligible", "evidence_check"):
        assert k in o
    assert o["predicted_satisfaction"] is None and o["satisfaction_validity"]["validity"] == "no_score"
    assert o["e_reward_eligible"]["eligible"] is False and o["e_reward_eligible"]["reasons"]
    assert o["evidence_check"]["n_refs"] == o["evidence_check"]["n_ok"] > 0
    json.dumps(strip_private(o), default=str)
    rep = f.owner_report(outs, "unit test")
    assert "e_reward_allowed = false" in rep["markdown"] and "NOT_CHECKABLE" in rep["markdown"]
    assert rep["json"]["actions"][0]["code"] == "claim_false" and rep["json"]["actions"][0]["example_refs"]


def test_agent_f_flags_coverage_gap_for_delivered_late_order_past_return_window(tmp_path):
    rows = refund_conv(outcome="info", action="status", proposal=False, main_reason="late_delivery",
                       delivered=True)
    for r in rows:                                              # delivered, 8 days late, 30 days ago
        if r["step"] == "tool_call" and r["data"]["tool"] in ("get_tracking", "ask_agent"):
            res = r["data"]["result"]
            (res["facts"] if "facts" in res else res)["days_since_delivery"] = 30
    p = tmp_path / "gap.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    o = AgentF.load({"scorer": "none"}).process(p)
    assert any(w["kind"] == "knowledge_gap" for w in o["rule_knowledge_warnings"])


FV3 = Path("/tmp/claude-0/-home-user/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/f_v3")


@pytest.mark.skipif(not (FV3 / "ckpt/tfidf_ridge_tail256/meta.json").exists(), reason="checkpoint outside git")
def test_agent_f_with_the_real_tfidf_scorer(tmp_path):
    p = tmp_path / "fr.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in refund_conv(text="Bonjour, ma commande 4512 est en retard")))
    q = tmp_path / "en.jsonl"
    q.write_text("".join(json.dumps(r) + "\n" for r in refund_conv()))
    f = AgentF.load({"scorer": f"tfidf:{FV3}/ckpt/tfidf_ridge_tail256"})
    fr, en = f.process(p), f.process(q)
    assert fr["predicted_satisfaction"] is None and 1 <= en["predicted_satisfaction"] <= 5
    assert en["satisfaction_validity"]["model_sha256"].startswith("1c2018") and f.card["corpus"] == "uss"


def test_learn_from_reviews_uses_only_measured_consented_ratings_and_needs_50(tmp_path):
    import numpy as np
    from v4.f.annotation.make_synthetic_fixture import make
    labels, _, _ = make(n=80)                                     # SYNTHETIC records (is_test_or_synthetic = true)
    rng = np.random.default_rng(0)
    gold = {}
    for r in labels:
        gold.setdefault(r["conversation_id"], []).append(r["rating"])
    results = [{"conversation_id": c, "predicted_satisfaction": float(2.6 + 0.2 * np.mean(v) + rng.normal(0, 0.05))}
               for c, v in gold.items()]                          # compressed scores, as on USS
    f = AgentF.load({"scorer": "none"})
    rep = f.learn_from_reviews(labels, results)
    assert rep["n_reviewed_and_scored"] == 0 and f.calibrator is None   # synthetic records refused by default
    rep = f.learn_from_reviews(labels, results, allow_synthetic=True)
    assert rep["calibrator"]["used"] is True and rep["calibrator"]["cv_mae_calibrated"] < rep["calibrator"]["cv_mae_raw"]
    rep = f.learn_from_reviews(labels[:3 * 30], results, allow_synthetic=True)   # 30 reviews < 50
    assert rep["calibrator"]["used"] is False and f.calibrator is None


def test_demo_runs_offline(tmp_path):
    from v4.f import demo_agent_f
    demo_agent_f.main(["--scorer", "none", "--out", str(tmp_path)])
    assert "e_reward_allowed = false" in (tmp_path / "owner_report.md").read_text()
