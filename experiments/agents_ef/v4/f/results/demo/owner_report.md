# Agent F quality report — 2026-10-25T15:50:13.585 to 2026-10-25T15:51:15.806

Prepared by Agent F (M7, checks m7-v4). F only reads traces and reports; it changed nothing. Corpus: demo traces (/home/user/CallVerse-research/experiments/agents_ef/v4/f/demo_traces). Closed conversations: 6.

Resolution: {'resolved': 3, 'escalated': 2, 'waiting_on_client': 1}. Grades: {'review': 2, 'ok_minor': 2, 'fail': 2}. Reply source: {'template': 6}.

## 1. What to decide (most severe first)

| # | Finding | Severity | Conversations | Evidence (file:line) | Decision for the owner | Does NOT show |
|---|---|---|---|---|---|---|
| 1 | `claim_false`: agent B claimed days_late=8, the data say 0 | high | 1 | dev-0005.jsonl:27 | read the case; the agent stated a fact that contradicts the platform data (the Coordinator re-reads facts, so check the final decision too) | not whether a wrong refund was paid: see the decision in the trace |
| 2 | `sent_back`: the Coordinator sent the proposal back 2 time(s) | high | 1 | dev-0005.jsonl:40 | the Coordinator had to correct the agent; frequent send-backs mean the agent misreads rules | not a client-facing error (the Coordinator caught it) |
| 3 | `pipeline_error`: the agents failed; the client was told the case needs an extra check | high | 1 | dev-0015.jsonl:12 | check the agents' LLM provider and the error handling; the client got the 'extra check' reply | not why the provider failed |
| 4 | `reply_language_mismatch`: client wrote in French, the reply is not in French | medium | 2 | dev-0000.jsonl:39, dev-0095.jsonl:42 | French-speaking clients were answered in English; add French reply templates (prototype lane) | not that the client could not read English |
| 5 | `escalated`: case escalated to a human | medium | 2 | dev-0005.jsonl:104, dev-0015.jsonl:20 | cases sent to a human; check the human queue capacity | not that escalation was wrong |
| 6 | `cited_missing_rule`: agent cited rule R-REF-02, which does not exist | medium | 1 | dev-0095.jsonl:31 | agents cite a rule id that is not in the policy file; check the prompts for an old id | not which rule was meant |
| 7 | `proposal_malformed`: the proposal tool refused the agent's proposal | medium | 1 | dev-0095.jsonl:31 | the proposal tool refused the agent's proposal; check the agent's prompt | not a client-facing error |
| 8 | `slm_fallback_template`: the SLM gave no passing reply; the fixed template was sent | low | 6 | dev-0000.jsonl:39, dev-0002.jsonl:22, dev-0005.jsonl:104, dev-0013.jsonl:49, dev-0015.jsonl:20 | the SLM gave no passing reply, the fixed template was sent; check the SLM service | not that the template reply was bad |

Evidence check: 19 of 19 evidence refs were re-read from the traces and matched (right file, right step, right value).

## 2. Rules and knowledge

**Internal consistency (checkable)**: 1 flag(s)
- stale_reference R-REF-02: agents cited R-REF-02 1 time(s); it is not in the policy file. Decision: check the agents' prompts / knowledge for an old rule id. False-positive risk: low for code/config refs (exact id match); for agent citations, one LLM slip can repeat in a batch — the support count is shown.

**Coverage: situations no rule covers (questions, not errors)**: 2 flag(s)
- knowledge_gap : no conditional rule covers: delivered, on time. Decision: decide what clients in this situation are owed and write it as a rule. False-positive risk: high: 'no rule' may be the intended policy (nothing is owed); it is a question, not a defect.
- knowledge_gap : no conditional rule covers: delivered, late. Decision: decide what clients in this situation are owed and write it as a rule. False-positive risk: high: 'no rule' may be the intended policy (nothing is owed); it is a question, not a defect.

**Governance**: 8 flag(s)
- 8 rules are AI-written with no review, version or date (R-DEL-01, R-DEL-02, R-REF-03, R-REF-05, R-RET-01, R-DMG-01, R-ESC-01, R-NOT-01). Decision: review them and add version + last_reviewed.

**Usage in these conversations**: 0 flag(s)

**Freshness (is each rule still true today?)**: NOT_CHECKABLE — no dated, authoritative source (law, carrier contract, signed company decision) exists for any rule, and the policy file has no version or date fields; 'outdated' cannot be shown. Needed: valid_from / valid_until / last_reviewed / owner fields per rule; a dated source reference per rule (document id + date); a change log of the policy file.

Predicted-satisfaction-per-rule check: SKIPPED: satisfaction score not validated for this domain; it must not create rule flags.

## 3. Satisfaction (predicted by a model, NOT reported by clients)

- Model: tfidf_ridge_tail256. Validity per conversation: {'withheld_language_not_validated': 2, 'indicative_out_of_domain': 4}. Languages: {'fr': 2, 'en': 4}.
- Scored 4 of 6; conversations in a language the model was never validated on get no score.
- Indicative mean 3.281 (SD 0.026) — scores are model predictions, not client ratings; not validated on CallVerse conversations.
- Comparisons by grade, rule or resolution: NOT SHOWN: the score is not validated on CallVerse conversations.
- What the model was measured on: USS = third-party annotator judgements of task-oriented dialogues (EN) and JDDC e-commerce service (ZH); not customer ratings, not CallVerse conversations; TEST n=1016, MAE 0.3919 (mean baseline 0.51), Spearman 0.596 [95% CI 0.55, 0.6381].

## 4. Feedback to Agent E

- **e_reward_allowed = false**; eligible conversations 0 / 6.
- Reasons: label_type: value human_annotation, needed genuine_customer_rating; domain: value task_oriented_dialogue, needed support_conversation; coverage: value 0.0, needed >= 0.95.
- E's safety rules (mask, budget, fallback cap, HIGH protections) never depend on this score.

