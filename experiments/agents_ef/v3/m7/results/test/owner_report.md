# Quality report for the owner — 2026-10-25T15:51:28.607 to 2026-10-25T15:52:28.307

Prepared by Agent F (M7). F only reports; nothing was changed. Corpus: TEST (held out, scripted agents, real pipeline; code e9367c5).

## 1. Conversations

| Item | Value |
|---|---|
| Closed conversations | 120 |
| Resolved | 105 (87.5%) |
| Waiting on the client / finance | 9 / 0 |
| Escalated to a human | 6 |
| Grade fail / review / ok | 8 / 20 / 92 |
| Reply from the SLM / template | 0 / 120 |

## 2. Satisfaction (PREDICTED by a model, not reported by clients)

- Model: f:/tmp/claude-0/-home-user/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/f_v3/ckpt/tinybert_ft_en_frac0.5_len128_s1. Scored 120 / 120 conversations.
- Mean predicted score 3.11 (1-5), spread (SD) 0.07; share below 2.5: 0.0%.
- By quality grade: fail 3.15, ok_minor 3.10, review 3.17
- By resolution: escalated 3.16, resolved 3.11, waiting_on_client 3.09
- Validation of the model: tinybert_ft_en_frac0.5_len128 (seed 1) on human_annotation (task_oriented_dialogue), test n=525: MAE 0.3048 vs mean baseline 0.3332, Spearman 0.3686 [95% CI 0.2906, 0.444]

## 3. Flags in conversations (deterministic checks, evidence in quality_reviews.jsonl)

| Flag | Severity | Count |
|---|---|---|
| claim_contradicts_data | high | 7 |
| sent_back | high | 4 |
| missed_entitlement | high | 2 |
| pipeline_error | high | 2 |
| reply_language_mismatch | medium | 23 |
| escalated | medium | 6 |
| cited_missing_rule | medium | 1 |
| proposal_malformed | medium | 1 |
| slm_fallback_template | low | 120 |
| agent_answered_without_tools | low | 6 |
| rule_not_searched | low | 2 |

Worst conversations (first 10):

- `test-0008` order 5017, escalate: claim_contradicts_data — agent claimed days_late=8, the data says 0; claim_contradicts_data — agent claimed delivered=False, the data says True; sent_back — the Coordinator sent the proposal back 2 time(s); escalated — case escalated to a human; reply_language_mismatch — client wrote in French, the reply is not in French
- `test-0030` order 5066, ask_user: missed_entitlement — client asked for a refund the data show is due (R-REF-03), but none was approved
- `test-0031` order 5023, info: cited_missing_rule — agent cited rule R-REF-02, which does not exist; proposal_malformed — the proposal tool refused the agent's proposal; missed_entitlement — client asked for a refund the data show is due (R-REF-03), but none was approved
- `test-0052` order 4505, escalate: claim_contradicts_data — agent claimed days_late=8, the data says 0; claim_contradicts_data — agent claimed delivered=False, the data says True; sent_back — the Coordinator sent the proposal back 2 time(s); escalated — case escalated to a human; reply_language_mismatch — client wrote in French, the reply is not in French
- `test-0073` order 5008, escalate: pipeline_error — the agents failed; the client was told the case needs an extra check; escalated — case escalated to a human
- `test-0095` order 5026, escalate: pipeline_error — the agents failed; the client was told the case needs an extra check; escalated — case escalated to a human
- `test-0100` order 5045, escalate: claim_contradicts_data — agent claimed days_late=8, the data says 0; claim_contradicts_data — agent claimed delivered=False, the data says True; sent_back — the Coordinator sent the proposal back 2 time(s); escalated — case escalated to a human
- `test-0114` order 5100, escalate: claim_contradicts_data — agent claimed days_late=8, the data says 4; sent_back — the Coordinator sent the proposal back 2 time(s); escalated — case escalated to a human; reply_language_mismatch — client wrote in French, the reply is not in French
- `test-0006` order 5056, info: reply_language_mismatch — client wrote in French, the reply is not in French
- `test-0017` order 5038, info: reply_language_mismatch — client wrote in French, the reply is not in French

## 4. Rules and knowledge that may be outdated

| Kind | Rule | Severity | What | Owner decision |
|---|---|---|---|---|
| knowledge_gap | — | low | no conditional rule covers: delivered, on time | decide what clients in this situation are owed and write it as a rule |
| knowledge_gap | — | medium | no conditional rule covers: delivered, late | decide what clients in this situation are owed and write it as a rule |
| stale_reference | R-REF-02 | medium | agents cited R-REF-02 1 time(s); it is not in the policy file | check the agents' prompts / knowledge for an old rule id |
| usage_signal | R-REF-03 | medium | condition false in 12/23 checks: agents often apply it where it does not hold | check whether the wording still matches how cases look |
| usage_signal | R-DEL-01 | low | never cited or retrieved in 120 conversations | check whether the rule is still needed |
| usage_signal | R-RET-01 | low | never cited or retrieved in 120 conversations | check whether the rule is still needed |
| unreviewed | 8 rules | low | AI-written wording, no review/version/date | review and add version + last_reviewed |

## 5. Feedback to Agent E

- Satisfaction enters E's reward: **NO (KPI only)**.
- Gate checks: label_type FAIL (human_annotation); domain FAIL (task_oriented_dialogue); test_n pass (525); spearman_ci_low FAIL (0.2906); beats_mean_baseline pass ([0.3048, 0.3332]); coverage pass (1.0)
- E's safety rules (mask, budget, fallback cap, no fallback for HIGH) never depend on this score.

