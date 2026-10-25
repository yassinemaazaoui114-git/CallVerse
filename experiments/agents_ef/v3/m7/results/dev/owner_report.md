# Quality report for the owner — 2026-10-25T15:50:13.585 to 2026-10-25T15:51:25.429

Prepared by Agent F (M7). F only reports; nothing was changed. Corpus: dev (scripted agents, real pipeline).

## 1. Conversations

| Item | Value |
|---|---|
| Closed conversations | 120 |
| Resolved | 99 (82.5%) |
| Waiting on the client / finance | 12 / 0 |
| Escalated to a human | 9 |
| Grade fail / review / ok | 11 / 32 / 77 |
| Reply from the SLM / template | 0 / 120 |

## 2. Satisfaction (PREDICTED by a model, not reported by clients)

- Model: f:/tmp/claude-0/-home-user/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/f_v3/ckpt/tinybert_ft_en_frac0.5_len128_s1. Scored 120 / 120 conversations.
- Mean predicted score 3.12 (1-5), spread (SD) 0.07; share below 2.5: 0.0%.
- By quality grade: fail 3.11, ok_minor 3.10, review 3.16
- By resolution: escalated 3.12, resolved 3.12, waiting_on_client 3.08
- Validation of the model: tinybert_ft_en_frac0.5_len128 (seed 1) on human_annotation (task_oriented_dialogue), test n=525: MAE 0.3048 vs mean baseline 0.3332, Spearman 0.3686 [95% CI 0.2906, 0.444]

## 3. Flags in conversations (deterministic checks, evidence in quality_reviews.jsonl)

| Flag | Severity | Count |
|---|---|---|
| claim_contradicts_data | high | 7 |
| sent_back | high | 7 |
| pipeline_error | high | 5 |
| missed_entitlement | high | 2 |
| reply_language_mismatch | medium | 29 |
| escalated | medium | 9 |
| cited_missing_rule | medium | 1 |
| proposal_malformed | medium | 1 |
| slm_fallback_template | low | 120 |
| agent_answered_without_tools | low | 5 |
| rule_not_searched | low | 1 |

Worst conversations (first 10):

- `dev-0005` order 5089, escalate: claim_contradicts_data — agent claimed days_late=8, the data says 0; claim_contradicts_data — agent claimed delivered=False, the data says True; sent_back — the Coordinator sent the proposal back 2 time(s); escalated — case escalated to a human
- `dev-0013` order 5110, ask_user: missed_entitlement — client asked for a refund the data show is due (R-REF-03), but none was approved
- `dev-0015` order 5057, escalate: pipeline_error — the agents failed; the client was told the case needs an extra check; escalated — case escalated to a human
- `dev-0022` order 5095, escalate: pipeline_error — the agents failed; the client was told the case needs an extra check; escalated — case escalated to a human
- `dev-0042` order 4512, escalate: pipeline_error — the agents failed; the client was told the case needs an extra check; escalated — case escalated to a human
- `dev-0050` order 5018, escalate: pipeline_error — the agents failed; the client was told the case needs an extra check; escalated — case escalated to a human
- `dev-0055` order 5116, escalate: claim_contradicts_data — agent claimed days_late=8, the data says 0; claim_contradicts_data — agent claimed delivered=False, the data says True; sent_back — the Coordinator sent the proposal back 2 time(s); escalated — case escalated to a human
- `dev-0062` order 5034, escalate: claim_contradicts_data — agent claimed days_late=8, the data says 2; claim_contradicts_data — agent claimed delivered=False, the data says True; sent_back — the Coordinator sent the proposal back 2 time(s); escalated — case escalated to a human
- `dev-0080` order 5094, escalate: pipeline_error — the agents failed; the client was told the case needs an extra check; escalated — case escalated to a human
- `dev-0102` order 4515, ask_user: missed_entitlement — client asked for a refund the data show is due (R-REF-03), but none was approved

## 4. Rules and knowledge that may be outdated

| Kind | Rule | Severity | What | Owner decision |
|---|---|---|---|---|
| knowledge_gap | — | low | no conditional rule covers: delivered, on time | decide what clients in this situation are owed and write it as a rule |
| knowledge_gap | — | medium | no conditional rule covers: delivered, late | decide what clients in this situation are owed and write it as a rule |
| stale_reference | R-REF-02 | medium | agents cited R-REF-02 1 time(s); it is not in the policy file | check the agents' prompts / knowledge for an old rule id |
| usage_signal | R-REF-03 | medium | condition false in 12/27 checks: agents often apply it where it does not hold | check whether the wording still matches how cases look |
| usage_signal | R-DEL-01 | low | never cited or retrieved in 120 conversations | check whether the rule is still needed |
| usage_signal | R-RET-01 | low | never cited or retrieved in 120 conversations | check whether the rule is still needed |
| unreviewed | 8 rules | low | AI-written wording, no review/version/date | review and add version + last_reviewed |

## 5. Feedback to Agent E

- Satisfaction enters E's reward: **NO (KPI only)**.
- Gate checks: label_type FAIL (human_annotation); domain FAIL (task_oriented_dialogue); test_n pass (525); spearman_ci_low FAIL (0.2906); beats_mean_baseline pass ([0.3048, 0.3332]); coverage pass (1.0)
- E's safety rules (mask, budget, fallback cap, no fallback for HIGH) never depend on this score.

