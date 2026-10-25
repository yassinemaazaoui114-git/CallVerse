"""M7 v4 responsibility 3: rules and knowledge — what CAN be checked, kept apart from what CANNOT.

    audit_v4(reviews, convs, sim_today, policies=None, scores_valid=False, scores=None) -> dict

V3 (`v3/m7/rule_audit.py`) reported every finding as "may be OUTDATED". That wording implied a freshness check
that was never possible: nothing in the platform says when a rule was last true. v4 separates:

  internal_consistency  the rule disagrees with something else IN the system: its own condition (numbers),
                        the facts the Coordinator can read, rule ids used in code/config or cited by agents.
                        (V3 static S1, S2, S4 + usage U1.) Checkable now.
  coverage              realistic order situations no conditional rule covers (V3 fact grid S5). Checkable now;
                        it is a QUESTION for the owner, not an error (owing nothing may be intended).
  governance            AI-written rules without review metadata (V3 S3), plus, when a rule HAS dates, whether its
                        validity has ended or its review is overdue relative to sim_today (v4).
  usage                 how rules behaved in closed conversations (V3 U2-U4). U5 (low PREDICTED satisfaction per
                        rule) runs only when the satisfaction score is validated (scores_valid=True); otherwise it
                        is skipped with the reason — an unvalidated score must not generate rule flags.
  freshness             is a rule still TRUE in the world (law, carrier terms, company decision)? Needs a dated,
                        authoritative source to compare with. There is none in the platform or the policy file,
                        so v4 reports status NOT_CHECKABLE per rule, with what would make it checkable.
Every flag carries `false_positive_risk` (when this flag can be wrong) and the owner action. F never edits a rule.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))          # experiments/agents_ef
from v3.m7 import rule_audit as ra3  # noqa: E402

REVIEW_PERIOD_DAYS = 365          # governance: a dated rule not reviewed for a year is "review_overdue" (fixed)

CATEGORY = {"inconsistency": "internal_consistency", "unverifiable": "internal_consistency",
            "stale_reference": "internal_consistency", "knowledge_gap": "coverage", "unreviewed": "governance",
            "usage_signal": "usage"}

FP_RISK = {
    "inconsistency": "a number written in words in the text ('five days') or a unit difference makes a false "
                     "mismatch; read both texts before acting",
    "unverifiable": "low: the fact list is parsed from coordinator._read_facts; a fact added elsewhere in the "
                    "Coordinator (not in _read_facts) would be missed and flagged wrongly",
    "stale_reference": "low for code/config refs (exact id match); for agent citations, one LLM slip can repeat "
                       "in a batch — the support count is shown",
    "knowledge_gap": "high: 'no rule' may be the intended policy (nothing is owed); it is a question, not a defect",
    "unreviewed": "none for the fact itself (fields are absent); it says nothing about whether the wording is right",
    "usage_signal": "medium/high: depends on the period's case mix (e.g. 'never used' when no client asked); "
                    "minimum support of 5 conversations applies",
    "expired": "low: depends on the date fields being maintained",
    "review_overdue": "low: a rule can be correct and simply not re-reviewed",
}


def _parse_date(v):
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def governance_dates(rules: list[dict], today: date) -> list[dict]:
    """Date-based governance flags (only for rules that HAVE dates; the current policy file has none)."""
    out = []
    for r in rules:
        until, reviewed = _parse_date(r.get("valid_until")), _parse_date(r.get("last_reviewed"))
        if until and until < today:
            out.append(ra3._flag("expired", r["id"], "high", f"validity ended on {until} (sim_today {today})",
                                 {"valid_until": str(until), "sim_today": str(today)},
                                 "renew, replace or retire the rule"))
        if reviewed and (today - reviewed).days > REVIEW_PERIOD_DAYS:
            out.append(ra3._flag("review_overdue", r["id"], "low",
                                 f"last reviewed {reviewed}, {(today - reviewed).days} days before sim_today",
                                 {"last_reviewed": str(reviewed), "review_period_days": REVIEW_PERIOD_DAYS},
                                 "re-review the wording and condition"))
    return out


def freshness(rules: list[dict], sources: list[dict] | None = None) -> dict:
    """Per-rule freshness status. `sources` = dated authoritative references {rule_id, source, date, value}.
    None exist in CallVerse today, so every rule is NOT_CHECKABLE. (With sources, a rule would be compared with
    its source; that comparison is not implemented because there is nothing to compare with.)"""
    by_rule = {}
    for s in sources or []:
        by_rule.setdefault(s.get("rule_id"), []).append(s)
    per = []
    for r in rules:
        src = by_rule.get(r["id"], [])
        per.append({"rule_id": r["id"], "status": "NOT_CHECKABLE" if not src else "SOURCE_AVAILABLE_NOT_COMPARED",
                    "dated_sources": len(src),
                    "has_dates_in_policy_file": any(r.get(k) for k in ("valid_from", "valid_until", "last_reviewed"))})
    return {"status": "NOT_CHECKABLE" if not sources else "PARTIAL",
            "why": "no dated, authoritative source (law, carrier contract, signed company decision) exists for any "
                   "rule, and the policy file has no version or date fields; 'outdated' cannot be shown",
            "what_would_make_it_checkable": ["valid_from / valid_until / last_reviewed / owner fields per rule",
                                             "a dated source reference per rule (document id + date)",
                                             "a change log of the policy file"],
            "per_rule": per}


def audit_v4(reviews: list[dict], convs: list[dict], sim_today: str, policies=None, scores_valid: bool = False,
             scores: dict | None = None, sources=None) -> dict:
    rules = policies or ra3.load_policies()
    today = _parse_date(sim_today)
    static = ra3.static_audit(policies)
    usage = ra3.usage_audit(reviews, convs, scores if scores_valid else None)
    flags = []
    for f in static + usage + governance_dates(rules, today):
        cat = CATEGORY.get(f["kind"], "governance")
        flags.append({**f, "category": cat, "false_positive_risk": FP_RISK.get(f["kind"], "unknown")})
    by_cat = {c: [f for f in flags if f["category"] == c]
              for c in ("internal_consistency", "coverage", "governance", "usage")}
    return {**by_cat, "freshness": freshness(rules, sources),
            "u5_predicted_satisfaction_per_rule": "run" if scores_valid and scores else
            "SKIPPED: satisfaction score not validated for this domain; it must not create rule flags",
            "n_rules": len(rules), "sim_today": sim_today,
            "note": "F reports only; it never changes a rule. 'Outdated' is never claimed: see freshness."}


def all_flags(audit: dict) -> list[dict]:
    return [f for c in ("internal_consistency", "coverage", "governance", "usage") for f in audit[c]]
