# F9 — M7 (Agent F "Quality & Knowledge") re-audit, v5

**Worker F, v5, 2026-10-26.**
- Code: `v5/f/m7/quality_v5.py` (imports v4 `quality_v4`, unchanged) and `v5/f/m7/run_m7_v5.py`.
- Tests: `v5/f/tests/test_m7_v5.py`, 15 tests.
- Results: `v5/f/results/m7_v5.json` and `v5/f/results/m7_v5_owner_report.md`.
- Corpus: the SCRIPTED M7 corpus. It has 240 conversations (120 dev + 120 held-out), runs the real prototype pipeline with fake agents, and the SLM was offline.
- `callverse/`, `v3/` and `v4/` were not modified. **The F→E gate stays CLOSED.**

## In plain words

- I checked M7's quality checks against the user's list of failures. Four kinds of failure were not covered:
  - promises of a refund or a delivery date that nothing backs up;
  - numbers in the reply that come from nowhere;
  - leaked instructions;
  - promised follow-ups that nothing will deliver.
- One business rule (the refund limit) was also only checked before the fact. It is now checked after the fact too.
- I added 7 fixed (rule-based) checks. Each has positive and negative tests.
- On the 240 scripted conversations the new checks raise **no false alarm**.
- When one defect of each kind is injected into those conversations, every injected defect is found. This injection test also exposed a bug in my first version, which is now fixed.
- None of this measures real-world accuracy: there are still no real closed conversations.

## 1. The user's list against M7

| Failure to detect | Before v5 (v4) | v5 | How (deterministic, on the trace) |
|---|---|---|---|
| contradicts tool facts | `claim_false` | unchanged | structured facts the agent claimed vs tool results / the Coordinator's re-read |
| unconfirmed **refund** promise | not checked (the prototype's SLM check blocks it before sending, English only) | **`reply_refund_promise_unbacked`** (high) | `callverse/slm/check.REFUND_PROMISE` (imported) + a French pattern; allowed only if the decision is approve+refund **and** a `create_refund` db_write exists |
| unconfirmed **delivery** promise | not checked | **`reply_delivery_promise_unsupported`** (medium) | "will arrive tomorrow / within 3 days / sera livrée demain…". No tool gives an arrival time, so allowed only if the same sentence repeats `promised_date` / `delivered_date` from the data |
| unsupported answers | `claim_unsupported`, `agent_answered_without_tools` | + **`reply_number_unsupported`** (medium) | numbers in the final reply that are not in the approved decision (facts, order id, next_step, must_say) or the client's own message |
| leaked instructions | `reply_leak` (internal words) | + **`reply_instruction_leak`** (high) | prompt / tool-format words: "my instructions", "as an AI", `facts_used`, `get_order`, `{"`… |
| wrong language | `reply_language_mismatch` (French client, non-French reply) | + **`reply_language_unexpected`** (medium) | the reverse case: English client, French reply |
| unresolved promised follow-ups | not checked | **`followup_promise_unbacked`** (medium) | "you will get a message…" needs a `create_subscription` write (rule R-NOT-01: "Promise a notification only after the subscription is recorded"); "a colleague will contact you…" needs outcome escalate / layer3 or a handover |
| business-rule violations | `missed_entitlement`, `cited_missing_rule`, `sent_back` | + **`refund_exceeds_balance`** (high) | executed `create_refund` amount > paid − refunded_total from the Coordinator's re-read (rule R-REF-05) |

**Why M7 re-checks what the SLM check already blocks**
- The SLM check runs **before** sending. It trusts the decision, and its refund pattern is English only.
- M7 runs **after** the conversation, against what was **executed** (the db_write lines), and in French too.
- This catches template or writer regressions and bypasses. It is defence in depth, not duplication.
- The English pattern is imported from `callverse/slm/check.py`, so both checks share one definition.

**Not checkable deterministically (stated, not faked)**
- promises paraphrased outside the patterns;
- claims inside the agent's free text;
- languages other than EN and FR;
- replacement promises (the platform has no replacement action).

## 2. Evidence

| Measure | DEV (120) | HELD-OUT (120) | Source |
|---|---|---|---|
| New-code flags on the corpus (no such defect exists there) | **0** | **0** | `m7_v5.json` → `new_code_flags` |
| v4 flags unchanged by v5 (same counts per code) | yes | yes | `flags_v4` vs `flags_v5` |
| v4 evidence refs re-read and matched | 196/196 | 184/184 | `evidence_refs_v4_ok` |
| v5 review time per conversation | 0.28 ms | 0.47 ms | `ms_per_conversation_v5_review` |

**Mutation test.** One defect of each new kind is injected into copies of the 240 real-format conversations (`mutation_recall_new_checks`).

| Injected defect | Eligible conversations | Detected | Other new codes fired |
|---|---|---|---|
| refund promise in a non-refund case ("We will refund you.") | 220 | 220 | none |
| delivery-time promise ("will arrive tomorrow") | 240 | 240 (**99 before the fix**) | none |
| unsupported number ("777.77 TND") | 240 | 240 | none |
| instruction leak | 240 | 240 | none |
| French reply to an English client | 137 | 137 | none |
| subscription write removed | 43 | 43 | none |
| executed refund +50 TND over the balance | 20 | 20 | none |

**Bug found by the mutation test**
- The first version excused a delivery promise whenever a data date appeared **anywhere** in the reply.
- The templates always say "the promised delivery date was …", so only 99 of 240 were caught.
- The exemption now looks only at the promise's own sentence. A regression test was added.
- Because the mutation set was then used to fix the check, its 100% is a development figure, not an independent recall estimate.
- The defects are visible by construction. This shows the checks' wiring and definitions, not real-world precision or recall.

## 3. Rule audit

Source: v4 `audit_v4` on the v5 reviews (`m7_v5.json` → `rule_audit_flags`), plus my reading of `callverse/kb/policies_shopnova.json` and `config.yaml`.

| Category | Finding | Evidence | Owner action |
|---|---|---|---|
| missing rule (stale reference) | agents cite **R-REF-02**, which does not exist | 2 citations, 1 conversation per split | remove the old id from the agent prompts |
| uncovered cases | no conditional rule covers "delivered, late" (medium) or "delivered, on time" past the return window (low) | fact-grid audit | decide whether nothing is owed (this may be intended policy) |
| **contradiction: rule text vs behaviour (new, v5)** | R-REF-03 says "the order is then **cancelled**". The platform sets the status to **`refunded`** after a refund | 20 `set_order_status` db_writes with `new_status = refunded` in the corpus | align the rule text or the status |
| **contradiction: rule vs platform capability (new, v5)** | R-DMG-01 allows "a replacement or a refund", but the Coordinator knows only the actions `refund` and `subscribe`. A replacement cannot be executed | `coordinator_check action_known`: "allowed actions: ['refund', 'subscribe']" | add a replacement action, or remove it from the rule |
| condition narrower than the text (new, v5) | R-RET-01's condition checks only `delivered and days_since_delivery <= 14`. The text also needs "unused and in its original packaging" and "after ShopNova receives the returned item"; no fact or action exists for either | policy file | add the facts, or mark the rule "human check needed" |
| consistent (checked) | R-DEL-02 (1–5 days) / R-REF-03 (> 5 days) have no gap and no overlap at the boundary. R-ESC-01's 300 TND matches the single threshold in `config.yaml` (priority "paid over"); the Layer 3 stub approves up to 500 | policy file, `config.yaml` | — |
| usage | R-REF-03's condition is false in 24/50 checks (driven by the planted false claims); R-DEL-01 and R-RET-01 are never used | usage audit | depends on the case mix (medium/high false-positive risk) |
| **missing provenance / version / review date** | all **8/8** rules are AI-written, with no `reviewed_by`, `version`, `valid_from` or `last_reviewed` | governance flags | add these fields; a human reviews each rule once |
| **freshness** | **NOT CHECKABLE** for all 8 rules: no dated, authoritative source exists, and the policy file has no dates | `freshness.status` | add a source reference and date per rule, plus a change log |

## 4. Owner report: trends, reliability, repeated failures

Source: `results/m7_v5_owner_report.md`. Rates are per 120 conversations with Wilson 95% CIs.

| Flag | DEV | Held-out | Difference credible? | Suggested human action |
|---|---|---|---|---|
| slm_fallback_template | 120 | 120 | no | the SLM was offline in this corpus; in real use, check why replies fall back |
| reply_language_mismatch | 29 [17–33%] | 23 [13–27%] | no (CIs overlap) | add French reply templates. This is the largest repeated failure after the fallback |
| escalated | 9 | 6 | no | read the reasons (agent errors vs real edge cases) |
| sent_back | 7 | 4 | no | repeated send-backs mean an agent misreads a rule |
| claim_false | 4 conv. (7 flags) | 4 conv. (7 flags) | no | read the cases |
| agent_answered_without_tools | 5 | 6 | no | prompt / tool forcing |
| pipeline_error | 5 | 2 | no | LLM provider and error handling |

**Reliability caveats, printed with the report**
1. **No time trend exists.** All conversations carry the same simulated date (2026-10-09). Dev vs held-out is a difference between batches, and no difference is credible.
2. **The rates describe the scripted mix,** whose defects were planted. They are not real operating rates.
3. A "repeated failure" means the same code in ≥ 3 conversations; every row above qualifies.
4. Each row carries up to 4 evidence refs (`file:line`) in the JSON.

## 5. F→E gate

**Unchanged and CLOSED.** It needs:
- genuine customer ratings;
- the support-conversation domain;
- TEST n ≥ 300;
- a Spearman CI lower bound ≥ 0.30.

None exists. Nothing in v5 changes this.
