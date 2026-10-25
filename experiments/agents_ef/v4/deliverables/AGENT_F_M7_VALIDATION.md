# Agent F (M7 "Quality & Knowledge") v4 — validation of the five responsibilities (F3–F6)

**Worker F, v4, 2026-10-26.**
- Code: `v4/f/m7/` (it imports frozen `v3/m7`, which is unchanged), `v4/f/agent_f.py`, `v4/f/demo_agent_f.py`.
- Evaluation: `v4/f/eval_m7_v4.py`, `v4/f/m7_stress.py`. Results: `v4/f/results/m7/`.
- Tests: `v4/f/tests/`, **62 passed**. `v3/m7/tests` still pass: **17 passed**.
- Prototype code (`callverse/`) and `v3/` were not modified.

## In plain words

- Agent F now reads each closed conversation and does five things:
  1. scores satisfaction, with a label saying how far the score can be trusted;
  2. runs 14 fixed quality checks, each with links to the exact trace lines;
  3. checks the rules for contradictions and gaps, and says openly that "is this rule out of date?" cannot be checked;
  4. writes an owner report where every item has evidence and a decision;
  5. tells Agent E clearly "no, you may not use this score as a reward yet", with the reasons.
- On 240 scripted conversations (120 for building, 120 held out), it raised **no false alarm on clean conversations**. Every evidence link pointed to the right line.
- A stress test found one real weakness: numbers written as text. It is fixed.
- These are **wiring checks on scripted conversations**. They do not tell how well F works on real clients. No real closed conversation exists yet.

## 1. Responsibility (a) — satisfaction for every closed conversation, with validity

- Code: `m7/satisfaction_v4.py`. Default model: TF-IDF tail-256 (`AGENT_F_MODEL_IMPROVEMENTS.md`).
- Every record carries:
  - `model_id` and `model_sha256`;
  - `label_type` (human annotation of USS dialogues);
  - the detected `language`;
  - `language_validated` and `domain_validated`;
  - `validity`, `usable_for` and `reasons`.

| Held-out corpus (120) | Count | Score given? |
|---|---|---|
| `indicative_out_of_domain` (English) | 97 | yes, labelled "indicative, not validated" |
| `withheld_language_not_validated` (French) | 23 | **no**: French is never silently scored |
| `validated` | 0 | — (needs labelled CallVerse conversations) |

- **Language detector** (rule-based; FR / AR / EN / ZH): 120/120 correct on dev and 120/120 on held-out, against the corpus language field.
- **"Learns from real reviews":** `AgentF.learn_from_reviews(records, results)` fits V3's `ReviewCalibrator` (isotonic, 5-fold CV, at least 50 reviews, kept only if it beats the raw score) and computes `review_bias`, from records in the proposed reviews contract.
  - Only measured, consented, non-synthetic ratings are used.
  - **Tested only on a SYNTHETIC fixture** (mechanism check). There are no real reviews.
- **Owner report:** satisfaction comparisons by grade, rule or resolution are **not shown** while the score is not validated. V3 showed them; that was an unsupported claim.

## 2. Responsibility (b) — quality review (14 deterministic checks)

- Code: `m7/quality_v4.py`. It is V3's `quality.review` plus these changes.

| Change | Why | Evidence |
|---|---|---|
| `claim_contradicts_data` split into **`claim_false`** (contradicts the tool data or the Coordinator's re-read; high) and **`claim_unsupported`** (that agent run never received the fact from a tool before the claim; medium) | A lucky guess and a wrong fact are different failures | tests: positive, negative, float / boolean boundaries, "result after the claim", "fact from an earlier run (send-back)" |
| Agent runs are read from `agent_start` lines; Agent B's facts from A count via the `ask_agent` result | Grounding is per agent run | tests |
| `missed_entitlement` not raised when the refund **was offered** and the client was asked to confirm (`ask_user`) | **False positive found on DEV** (2 of 2 dev flags) | test; dev / held-out counts below |
| v4.1: numbers / booleans written as strings (`"8"`, `"false"`) are compared as values | **Stress test on DEV**: 16/120 false `claim_false` before the fix | `results/m7_stress_dev_v4_0.json` → `_v4_1.json` |
| Tried and **reverted**: a word-boundary leak pattern | My premise was wrong: V3's pattern does not match "agency" | test kept as a boundary case |
| `verify_refs()`: every evidence ref is re-read. It must be in the same file and in the conversation's span, with the expected step, and (for claims) the claimed / data value on that line | Evidence must be checkable | tests incl. tampered refs |

**Tests per check** (`tests/test_m7_v4.py`). Every one of the 14 codes has a positive, a negative and at least one boundary case:

| Check | Boundary cases tested |
|---|---|
| pipeline_error | error in the 2nd ticket of the same file does not flag the 1st |
| claim_false | 59.905 vs 59.90 same; 59.92 differs; 0 vs False differs; "8" vs 8 same |
| claim_unsupported | fact arrives after the claim; fact from an earlier run |
| cited_missing_rule | id in a refused proposal; no id at all |
| sent_back | 1 → medium, 2 → high |
| escalated | layer3 is not an escalation |
| missed_entitlement | 5 days → no, 6 → yes; fully refunded; cancelled; ask_user |
| reply_leak | "agency", tracking ids → no; "reagent" → yes (known substring risk) |
| reply_language_mismatch | 3 French words → flag; 2 → none |
| proposal_malformed | 2 refusals → 2 flags |
| rule_not_searched, agent_answered_without_tools, handover_ignored, slm_fallback_template | present / absent |

**Corpus results.** The corpus runs the real prototype pipeline; only the agents' LLM is scripted, and the SLM is offline.
- Code hashes were frozen after the dev run (`results/m7/frozen_code_sha256.json`).
- The held-out run was done **once** on the frozen code (`results/m7/test/`).
- The v4.1 fix came after it. It was re-checked separately (`results/m7/test_v4_1/`) with identical results.

| | DEV (120) | HELD-OUT (120) |
|---|---|---|
| Planted defects that occurred → caught by the expected flag (**wiring check only**) | 21 / 21 | 16 / 16 |
| Planted but did not occur (order already refunded earlier) | 9 | 13 |
| False positives on clean conversations (flags other than the 3 verified observations) | **0 / 90** | **0 / 91** |
| Verified observations on clean conversations: `slm_fallback_template` (reply_source = template) | 90 | 91 |
| Verified observations on clean conversations: `reply_language_mismatch` (corpus language = fr) | 26 | 16 |
| `reply_language_mismatch` vs corpus language, all conversations | 29 / 29 FR flagged, 0 / 91 EN | 23 / 23 FR flagged, 0 / 97 EN |
| `missed_entitlement`: V3 → v4 | 2 → 0 (both were ask_user) | 2 → 1 (test-0030 ask_user removed; test-0031 kept: a due refund that ended as `info` after a refused proposal) |
| `claim_unsupported` raised | 0 | 0 (the scripted agents always read facts: **validated by unit tests only**) |
| Evidence refs re-read and matched | 196 / 196 | 184 / 184 |
| Processing time per conversation (incl. TF-IDF scoring) | 4.1 ms | 7.0 ms |

**Benign-mutation stress test (DEV only, `m7_stress.py`).** Each mutation keeps what happened; the flags must not change.

| Mutation | v4.0: conversations whose flags changed | v4.1 |
|---|---|---|
| numbers as strings in `facts_used` | **16 / 120** | 0 / 120 |
| float noise (59.9 → 59.9000000001) | 0 | 0 |
| unrelated trace lines after every tool call | 0 | 0 |
| one garbled (half-written) line | 0 | 0 |
| 5 conversations in one batch file | 0 | 0 |

**Honest reading.** The defects are visible in the traces by construction, so recall = 1.0 shows correct wiring, **not** real-world accuracy. Zero false positives on scripted clean conversations is a necessary condition, not proof. No unscripted closed conversation exists: 13 real trace files were found, with 0 `pipeline_done` lines.

## 3. Responsibility (c) — rules and knowledge

- Code: `m7/rule_audit_v4.py`. It reuses V3's static and usage checks.
- It reports them in **separate categories**, each flag with a `false_positive_risk` text. F never edits a rule.

| Category | Held-out flags | What they are | False-positive risk |
|---|---|---|---|
| internal_consistency | 1 | agents cited R-REF-02 (not in the policy file), 1 conversation, planted | low (exact id) |
| coverage | 2 | no conditional rule covers "delivered, late" (medium) or "delivered, on time" past 14 days (low) | **high**: owing nothing may be the intended policy, so this is a question, not a defect |
| governance | 8 | all 8 rules AI-written with no review / version / date; date-based `expired` / `review_overdue` flags exist but cannot fire (no dates) | none for the fact itself |
| usage | 3 | R-REF-03 condition false in 12/27 checks (caused by the planted false claims); R-DEL-01 and R-RET-01 never used (corpus mix: no returns) | medium / high: depends on the case mix |
| **freshness** | — | **NOT_CHECKABLE for all 8 rules**: no dated, authoritative source and no version / date fields. F does not claim any rule is "outdated" | — |
| predicted-satisfaction-per-rule (V3 U5) | — | **SKIPPED**: an unvalidated score must not create rule flags (tested) | — |

- Per-conversation warnings (`AgentF.process`): the rule flags for the rules this conversation used, cited missing rules, and "this order's situation is in a coverage gap" (31 held-out conversations, e.g. delivered orders past 14 days).
- Global governance facts are reported once, not per conversation. Dev showed 71 repeated warnings before this change.

## 4. Responsibility (d) — owner report

- Code: `m7/report_v4.py`. Examples: `results/m7/test/owner_report.md`, `results/demo/owner_report.md`.
- **Actions table:** finding, severity, number of conversations, up to 5 evidence refs (`file:line`), the owner's decision, and **what the item does not show**.
- **Evidence integrity line:** "184 of 184 evidence refs were re-read from the traces and matched".
- **Rules section:** split by category; freshness NOT CHECKABLE with what would make it checkable.
- **Satisfaction section:** validity counts; indicative mean only; no comparisons.
- **E section:** `e_reward_allowed` with reasons.

## 5. Responsibility (e) — F → E feedback

- Code: `m7/feedback_v4.py`.
- The V3 gate and its thresholds are **unchanged**: genuine customer ratings, support-conversation domain, test n ≥ 300, Spearman CI low ≥ 0.30, beats the mean baseline, coverage ≥ 0.95.
- **Held-out:** `e_reward_allowed = false`; 0 / 120 conversations eligible. Reasons, as written by the code:
  - "label_type: value human_annotation, needed genuine_customer_rating";
  - "domain: value task_oriented_dialogue, needed support_conversation";
  - "coverage: value 0.0, needed >= 0.95".
- Each conversation row has `e_reward_eligible` + `reasons` + the shortfall in EnvV3 units (kpi_only).
- **Correction to V3:** DCH-2 cannot open this gate either. Its satisfaction labels are by student annotators (`v4/f/DATASETS_RECHECK.md`).

## 6. Interface (F6), contract (F5), annotation pipeline (F3)

- **`AgentF.load(config)`** takes a dict or a JSON / YAML path with keys `scorer`, `card`, `sim_today`, `score_unvalidated_languages`, `policies`.
- **`.process(trace_path | record)`** returns, per conversation: `predicted_satisfaction`, `satisfaction_validity`, `quality_flags` (with refs), `evidence_check`, `rule_knowledge_warnings`, `e_reward_eligible` {eligible, reasons}.
- **Other methods:** `.owner_report(list)`, `.learn_from_reviews(records, results)`.
- **Demo:** `python -m v4.f.demo_agent_f` runs offline in 3.3 s, including model load, on the 6 demo traces (`v4/f/demo_traces/`, copied from the scripted dev corpus).
- **Reviews contract (proposal only):**
  - Files: `v4/f/contracts/reviews_contract.md`, `reviews.schema.json`, `validate_reviews.py` (no new library).
  - It enforces measured rating ≠ AI-predicted score, consent and PII rules.
  - 19 contract and annotation tests (`v4/f/tests/test_contract_annotation.py`); 43 M7 / AgentF tests (`test_m7_v4.py`).
- **Annotation:**
  - `v4/f/ANNOTATION_PROTOCOL.md`: about 460 conversations, 3 blind annotators, ordinal Krippendorff α, splits fixed before predictions.
  - `v4/f/annotation/eval_labels.py`: agreement, metrics, card, gate.
  - Tested only on `annotation/fixture_SYNTHETIC/`. No number from that fixture may be reported.

## 7. NOT VERIFIED / BLOCKED

- **NOT VERIFIED:**
  - real-world precision and recall of all checks (no unscripted closed conversations);
  - `claim_unsupported` on real agents;
  - French and Arabic satisfaction;
  - the satisfaction model's accuracy on CallVerse.
- **BLOCKED:**
  - DCH-2: the user agreement was not accepted. It needs Yassine / the supervisor;
  - rule freshness: no dated sources exist.
- **Gate:** closed by design until genuine CallVerse ratings exist.

## 8. Questions for the Brain

1. Adopt the reviews contract (platform table) and the post-chat rating question?
2. Run the annotation protocol with volunteer testers?
3. Should annotator labels on CallVerse ever open E's reward? Today: no.
4. Multi-turn conversations in the prototype, so a client reaction exists: this is a prototype decision, and the main lever for satisfaction prediction (`AGENT_F_DOMAIN_SHIFT_ANALYSIS.md`).
5. French reply templates: 23–29 of 120 conversations per corpus are affected.
6. Add `valid_from` / `last_reviewed` / `source` fields to the policy file, so freshness becomes checkable?
