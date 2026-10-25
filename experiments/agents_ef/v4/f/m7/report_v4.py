"""M7 v4 responsibility 4: the owner's report — actionable, every item linked to evidence, no unsupported claim.

    build_owner_report(agent_f, results, corpus_label) -> {"json": {...}, "markdown": "..."}

Rules the report follows (each was a weakness of the V3 report):
  - every action item has: what was seen, how many conversations, example evidence refs (file:line), the owner
    decision to take, and what the item does NOT show;
  - satisfaction numbers appear only with their validity; while the model is not validated on CallVerse
    conversations, NO comparison by grade / rule / resolution is shown (V3 showed them: unsupported);
  - rule findings are split into internal consistency / coverage / governance / usage; freshness is reported as
    NOT CHECKABLE instead of "may be outdated";
  - the F -> E answer is explicit: e_reward_allowed with its reasons;
  - the share of evidence refs that were re-read and matched the trace is printed.
"""

import time
from collections import Counter, defaultdict

from v4.f.m7 import feedback_v4, rule_audit_v4, satisfaction_v4
from v4.f.m7.quality_v4 import CODES

SEV = {"high": 3, "medium": 2, "low": 1}
ACTIONS = {  # flag code -> (owner decision, what this does NOT show)
    "pipeline_error": ("check the agents' LLM provider and the error handling; the client got the 'extra check' "
                       "reply", "not why the provider failed"),
    "claim_false": ("read the case; the agent stated a fact that contradicts the platform data (the Coordinator "
                    "re-reads facts, so check the final decision too)", "not whether a wrong refund was paid: "
                                                                        "see the decision in the trace"),
    "claim_unsupported": ("the agent used a fact no tool gave it; check the agent's prompt / tool use",
                          "not that the fact is wrong (see later_data_agrees)"),
    "cited_missing_rule": ("agents cite a rule id that is not in the policy file; check the prompts for an old id",
                           "not which rule was meant"),
    "missed_entitlement": ("a refund the data show is due (R-REF-03) was not given or offered; read the case",
                           "not that the client still wants it"),
    "reply_leak": ("internal words reached the client; check the reply writer", "not that the client noticed"),
    "sent_back": ("the Coordinator had to correct the agent; frequent send-backs mean the agent misreads rules",
                  "not a client-facing error (the Coordinator caught it)"),
    "proposal_malformed": ("the proposal tool refused the agent's proposal; check the agent's prompt",
                           "not a client-facing error"),
    "reply_language_mismatch": ("French-speaking clients were answered in English; add French reply templates "
                                "(prototype lane)", "not that the client could not read English"),
    "escalated": ("cases sent to a human; check the human queue capacity", "not that escalation was wrong"),
    "rule_not_searched": ("agent cited a rule without looking it up", "not that the rule was wrong"),
    "agent_answered_without_tools": ("agent first answered without tools; the pipeline re-ran it",
                                     "not a client-facing error"),
    "slm_fallback_template": ("the SLM gave no passing reply, the fixed template was sent; check the SLM service",
                              "not that the template reply was bad"),
    "handover_ignored": ("a handover tag was ignored because A already had a decision", "not an error by itself"),
}
MAX_REFS = 5


def _ref_of(flag: dict) -> str | None:
    e = flag["evidence"]
    for k in ("ref", "claim_ref", "data_ref"):
        if e.get(k):
            return e[k]
    if e.get("refs"):
        return e["refs"][0]
    return None


def build_owner_report(agent, results: list[dict], corpus_label: str = "") -> dict:
    convs = [r["_conv"] for r in results]
    reviews = [r["_review"] for r in results]
    sat_records = [{"conversation_id": r["conversation_id"], "predicted_satisfaction": r["predicted_satisfaction"],
                    **r["satisfaction_validity"]} for r in results]
    decision = feedback_v4.e_reward_decision(agent.card, sat_records)
    scores_valid = all(r["satisfaction_validity"]["validity"] == "validated" for r in results) and bool(results)
    scores = {r["conversation_id"]: r["predicted_satisfaction"] for r in results
              if r["predicted_satisfaction"] is not None}
    audit = rule_audit_v4.audit_v4(reviews, convs, agent.sim_today, agent.policies, scores_valid, scores)
    ends = {c["conversation_id"]: c.get("end") for c in convs}
    rows = feedback_v4.per_conversation_v4(reviews, sat_records, ends, decision)
    steps = feedback_v4.aggregate(rows)

    # quality: per flag code, count + example refs
    by_code = defaultdict(list)
    for r in results:
        for f in r["quality_flags"]:
            by_code[f["code"]].append((r["conversation_id"], f))
    actions = []
    for code, items in sorted(by_code.items(), key=lambda x: (-max(SEV[f["severity"]] for _, f in x[1]),
                                                              -len(x[1]))):
        sev = max((f["severity"] for _, f in items), key=SEV.get)
        decide, not_shown = ACTIONS.get(code, ("read the cases", "unknown"))
        actions.append({"code": code, "severity": sev, "n_flags": len(items),
                        "n_conversations": len({c for c, _ in items}),
                        "example_refs": list(dict.fromkeys(_ref_of(f) for _, f in items))[:MAX_REFS],
                        "example_what": items[0][1]["what"], "owner_decision": decide, "does_not_show": not_shown})
    ev = [r["evidence_check"] for r in results if r["evidence_check"]]
    evidence = {"n_refs": sum(e["n_refs"] for e in ev), "n_ok": sum(e["n_ok"] for e in ev),
                "failed": [x for e in ev for x in e["failed"]][:20]}
    sat = satisfaction_v4.summary(sat_records)
    warn = Counter((w["kind"], w.get("rule_id")) for r in results for w in r["rule_knowledge_warnings"])
    rep = {"created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "corpus": corpus_label,
           "period": {"from": min((c.get("start") or "" for c in convs), default=None),
                      "to": max((c.get("end") or "" for c in convs), default=None)},
           "n_conversations": len(results), "checks_version": "m7-v4", "flag_codes_checked": list(CODES),
           "kpis": {"resolution": dict(Counter(r["resolution"] for r in results)),
                    "grade": dict(Counter(r["grade"] for r in results)),
                    "outcome": dict(Counter(r["outcome"] for r in results)),
                    "reply_source": dict(Counter(r["reply_source"] for r in results))},
           "actions": actions, "evidence_integrity": evidence,
           "rules_and_knowledge": audit, "per_conversation_rule_warnings": {f"{k[0]}|{k[1]}": n
                                                                            for k, n in warn.items()},
           "satisfaction": {**sat, "model_id": agent.scorer.model_id if agent.scorer else None,
                            "card": agent.card,
                            "comparisons_by_grade_rule_resolution": "NOT SHOWN: the score is not validated on "
                            "CallVerse conversations" if not scores_valid else "see per-conversation file"},
           "e_feedback": {"e_reward_allowed": decision["e_reward_allowed"], "reasons": decision["reasons"],
                          "n_rows": len(rows), "n_eligible": sum(r["e_reward_eligible"] for r in rows),
                          "n_steps": len(steps)},
           "_rows": rows, "_steps": steps}
    return {"json": rep, "markdown": to_markdown(rep)}


def to_markdown(rep: dict) -> str:
    k = rep["kpis"]
    L = [f"# Agent F quality report — {rep['period']['from']} to {rep['period']['to']}", "",
         f"Prepared by Agent F (M7, checks {rep['checks_version']}). F only reads traces and reports; it changed "
         f"nothing. Corpus: {rep['corpus'] or 'traces'}. Closed conversations: {rep['n_conversations']}.", "",
         f"Resolution: {k['resolution']}. Grades: {k['grade']}. Reply source: {k['reply_source']}.", "",
         "## 1. What to decide (most severe first)", "",
         "| # | Finding | Severity | Conversations | Evidence (file:line) | Decision for the owner | Does NOT show |",
         "|---|---|---|---|---|---|---|"]
    for i, a in enumerate(rep["actions"], 1):
        L.append(f"| {i} | `{a['code']}`: {a['example_what']} | {a['severity']} | {a['n_conversations']} | "
                 f"{', '.join(x for x in a['example_refs'] if x)} | {a['owner_decision']} | {a['does_not_show']} |")
    e = rep["evidence_integrity"]
    L += ["", f"Evidence check: {e['n_ok']} of {e['n_refs']} evidence refs were re-read from the traces and matched "
              f"(right file, right step, right value).", "", "## 2. Rules and knowledge", ""]
    au = rep["rules_and_knowledge"]
    for cat, title in (("internal_consistency", "Internal consistency (checkable)"),
                       ("coverage", "Coverage: situations no rule covers (questions, not errors)"),
                       ("governance", "Governance"), ("usage", "Usage in these conversations")):
        L.append(f"**{title}**: {len(au[cat])} flag(s)")
        rows = au[cat]
        if cat == "governance":
            unrev = [f for f in rows if f["kind"] == "unreviewed"]
            if unrev:
                L.append(f"- {len(unrev)} rules are AI-written with no review, version or date "
                         f"({', '.join(f['rule_id'] for f in unrev)}). Decision: review them and add "
                         "version + last_reviewed.")
            rows = [f for f in rows if f["kind"] != "unreviewed"]
        for f in rows:
            L.append(f"- {f['kind']} {f['rule_id'] or ''}: {f['what']}. Decision: {f['owner_action']}. "
                     f"False-positive risk: {f['false_positive_risk']}.")
        L.append("")
    fr = au["freshness"]
    L += [f"**Freshness (is each rule still true today?)**: {fr['status']} — {fr['why']}. Needed: "
          + "; ".join(fr["what_would_make_it_checkable"]) + ".", "",
          f"Predicted-satisfaction-per-rule check: {au['u5_predicted_satisfaction_per_rule']}.", "",
          "## 3. Satisfaction (predicted by a model, NOT reported by clients)", ""]
    s = rep["satisfaction"]
    L += [f"- Model: {s['model_id']}. Validity per conversation: {s['validity']}. Languages: {s['language']}.",
          f"- Scored {s['n_scored']} of {s['n']}; conversations in a language the model was never validated on "
          "get no score.",
          f"- Indicative mean {s['mean_indicative']} (SD {s['sd_indicative']}) — {s['note']}.",
          f"- Comparisons by grade, rule or resolution: {s['comparisons_by_grade_rule_resolution']}."]
    if s.get("card"):
        c = s["card"]
        L.append(f"- What the model was measured on: {c.get('note', '')}; TEST n={c['test_n']}, MAE {c['mae']} "
                 f"(mean baseline {c['mae_mean_baseline']}), Spearman {c['spearman']} [95% CI "
                 f"{c['spearman_ci_low']}, {c['spearman_ci_high']}].")
    fb = rep["e_feedback"]
    L += ["", "## 4. Feedback to Agent E", "",
          f"- **e_reward_allowed = {str(fb['e_reward_allowed']).lower()}**; eligible conversations "
          f"{fb['n_eligible']} / {fb['n_rows']}.",
          "- Reasons: " + ("; ".join(fb["reasons"]) or "all gate checks pass") + ".",
          "- E's safety rules (mask, budget, fallback cap, HIGH protections) never depend on this score.", ""]
    return "\n".join(L) + "\n"
