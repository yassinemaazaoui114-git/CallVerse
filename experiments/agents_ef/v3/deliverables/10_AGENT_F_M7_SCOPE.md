# 10 — Agent F = M7: scope alignment (Quality & Knowledge)

**Official requirement (authoritative):**
> F – Quality & Knowledge (agent, satisfaction predictor): users rarely leave reviews, but E's reward and the quality
> reports need a satisfaction score for every conversation. M7 learns from real reviews to predict that score. F also
> reviews closed conversations, flags outdated rules and reports to the owner.

Before this step, the V3 Agent F benchmark (`v3/f/`, Worker F) covered only the satisfaction predictor. This document records:
- the audit of what existed;
- the parts that were added (`v3/m7/`);
- the evidence that they work.

Completed experiments were not restarted. Agent E and Worker F kept running throughout.

## 1. Audit: what existed, and what was missing

| M7 responsibility | Before (evidence) | Gap | Now |
|---|---|---|---|
| 1. Satisfaction for closed conversations, tiny model | `v3/f/` benchmark: USS / Amazon models, `v3/f/f_predictor.py`; v2 `integration/agent_f_predictor.py` | No link to the prototype's closed conversations; no "learn from the few reviews" step | `m7/satisfaction.py`: scores every closed conversation (client message + final reply) with the F model; `ReviewCalibrator` (isotonic, cross-validated) for when real reviews exist; `review_bias` (reviewed vs all) |
| 2. Review closed-conversation quality | Nothing. The prototype traces every step (`callverse/trace.py`), but nothing read the traces back | Everything | `m7/conversations.py` (trace → closed-conversation record, with file:line refs); `m7/quality.py` (deterministic checks) |
| 3. Flag outdated rules / knowledge | Nothing. The policy file has checkable `condition` fields (`callverse/kb/policies.py`) | Everything | `m7/rule_audit.py`: static checks (policy file, config, code, fact grid) and usage checks (from closed conversations) |
| 4. Structured owner reports | Nothing | Everything | `m7/report.py`: `owner_report.json` and `.md`, `quality_reviews.jsonl`, `rule_flags.json` |
| 5. Validated satisfaction feedback to E | v2 `agent_f/f_reward.py` (Olist-isotonic proxy, judged not valid); E v3 has a synthetic SIM-CSAT term (`w_csat`) | No validity rule deciding when F may feed E's reward | `m7/feedback_e.py`: a validation **gate**, per-conversation records, per-step sums in EnvV3 units ((5 − s)/4) |

**Platform gap.** The ShopNova platform has **no reviews table** (`callverse/data/seed.py`: users, products, orders, refunds, subscriptions, events). So "learns from real reviews" has no in-platform source yet. The calibrator and the bias check are written and unit-tested, and they are ready the day reviews exist.

## 2. Design: lightweight by choice

```
 closed conversation trace (traces/<run>.jsonl, written by the prototype)
        │
        ▼
 conversations.py ── record per conversation (ticket, tool results, proposals, Coordinator checks, reply) + refs
        │
        ├──► quality.py ─────── deterministic checks → grade + flags with evidence
        ├──► satisfaction.py ── tiny F model (14.4M params, CPU) → predicted 1–5 score
        │          └── ReviewCalibrator (isotonic, uses real reviews when they exist)
        ├──► rule_audit.py ──── static + usage checks → rule / knowledge flags with evidence
        └──► feedback_e.py ──── gate(validation card) → reward or kpi_only → per-step shortfall for E
                       │
                       ▼
               report.py → owner_report.md / .json (F only reports; it changes nothing)
```

**Why rules, not a model, for review and audit.** Each check has an exact definition taken from the prototype itself:
- the Coordinator's checks;
- the policy conditions;
- the SLM leak pattern;
- the tool results recorded in the trace.

A model would add cost, latency and errors without making those definitions any more exact. The only learned part is the satisfaction score, because that is the one quantity that cannot be computed.

**Review cost (measured):** 0.8–1.2 ms per conversation for parsing and review. Scoring 120 conversations with TinyBERT took 10.7–11.2 s on CPU, model load included.

### Quality checks (`quality.py`)

| Flag | Severity | Definition |
|---|---|---|
| pipeline_error | high | the agents' LLM failed; the client got the "extra check" reply |
| claim_contradicts_data | high | a fact in the agent's proposal (days_late, delivered, paid, refunded_total) ≠ the tool result in the same trace |
| missed_entitlement | high | the client asked for a refund, R-REF-03 holds on the recorded facts, money is left, and no refund was approved or escalated |
| reply_leak | high | internal words in the final reply (prototype T08 pattern) |
| sent_back | medium / high | the Coordinator sent the proposal back (1 time / 2 or more times) |
| cited_missing_rule | medium | the agent cited a rule id that is not in the policy file (in a Coordinator check or in a refused proposal) |
| proposal_malformed | medium | the proposal tool refused the agent's proposal |
| reply_language_mismatch | medium | the client wrote in French; the reply has no French |
| escalated | medium | the case went to a human |
| rule_not_searched / agent_answered_without_tools / slm_fallback_template / handover_ignored | low | process slips the prototype already traces |

### Rule and knowledge checks (`rule_audit.py`)

- **Static:**
  - numbers in a rule's condition missing from its text;
  - condition facts the Coordinator cannot read (fact names parsed from `coordinator._read_facts`);
  - rule ids used in code or config but absent from the policy file;
  - fact-grid knowledge gaps;
  - AI-written rules with no review, version or date.
- **Usage** (minimum 5 conversations per flag):
  - rule ids cited by agents but absent from the policy file;
  - conditions often false when cited (rate ≥ 0.3);
  - policy search ranking another rule first;
  - rules never used;
  - lower **predicted** satisfaction for a rule (bootstrap 95% CI; n ≥ 20; association only).

### Gate for E's reward (`feedback_e.py`)

The thresholds were fixed before any evaluation. All of these must hold:
- labels = genuine customer ratings;
- domain = support conversations;
- test n ≥ 300;
- the Spearman 95% CI lower bound ≥ 0.30;
- MAE below the mean baseline;
- coverage ≥ 95%.

Otherwise every record is `kpi_only`. E's mask, budget, fallback cap and HIGH protections never depend on F.

## 3. Evidence

**Test data: a corpus on the real prototype pipeline.** `m7/make_corpus.py` runs `callverse/pipeline.py` unchanged:
- real parts: Intake with its local models, the router, the Coordinator, policy search (bge-small), the platform writes on a temporary DB, and the SLM writer, which falls back to its template because the SLM is offline;
- scripted part: only the agents' LLM, since there is no API key;
- some behaviours plant a known defect;
- the client messages were written for this corpus (EN/FR, calm/angry), so there is no customer data.

| Split | n | Use | Trace hashes |
|---|---|---|---|
| dev (seed 11) | 120 | building and fixing the checks | `m7/results/corpus_traces.sha256` |
| test (seed 22) | 120 | **held out**; run once on frozen code `e9367c5` | same file |

**Defect detection** (`m7/results/<split>/detection_eval.json`)

| Split | Planted defects that occurred | Caught | Flags on clean conversations | Planted but did not occur* |
|---|---|---|---|---|
| dev | 21 | 21 | 0 / 90 | 9 |
| test | 16 | 16 | 0 / 91 | 13 |

\* The order had already been refunded by an earlier conversation, so no proposal was made.

The dev run found two wiring faults in the checks, both fixed before the code was frozen:
- a missing rule id inside a *refused* proposal was not caught;
- rules that are always checked were wrongly reported as "never used".

**Honest reading.** The defects are visible in the traces by construction. This shows the checks are wired correctly to the real trace format. It is **not** an estimate of how many defects real conversations contain.

**Findings about the prototype itself** (not planted; same on dev and test):
1. **Replies to French clients come back in English** whenever the reply falls back to the template: 29 / 120 dev and 23 / 120 test. Every corpus reply was a template, because the SLM was offline. With the SLM running: NOT VERIFIED.
2. **Knowledge gap:** no rule covers a **delivered, late** order once the 14-day return window has passed (90 grid cases). Also, a delivered on-time order after 14 days is owed nothing (low severity).
3. **All 8 rules** are AI-written and have no review, version or validity date.
4. **R-DEL-01 and R-RET-01** were never cited or retrieved in 120 conversations. This is a corpus artefact: there were no return requests.

**Satisfaction model on these conversations**
- Worker F's USS-EN TinyBERT, seed 1, 14.4M params: test MAE 0.305 vs mean baseline 0.333; Spearman 0.369, 95% CI [0.291, 0.444]. These are annotator labels on task-oriented dialogues.
- On ShopNova conversations its predictions are almost constant: mean 3.11–3.12, **SD 0.07**. They show no difference between failed and ok conversations (3.15 vs 3.10 on test).
- Domain transfer from multi-turn USS dialogues to single-turn ShopNova template replies does **not** work.
- **Gate verdict: blocked (KPI only)** on label type, domain and Spearman CI.
- **Re-run with Worker F's final selection** (`e5small_trim_ft_L6_frac0.5_len256`, seed 1, 17.4M params; chosen on VAL by Worker F; `m7/results/test_finalF/`). Defect detection is unchanged (deterministic).
  - Validation card: USS TEST n = 1,016; MAE 0.391 vs 0.51 for the pooled train-mean baseline. The per-corpus mean floor is 0.423 (Worker F). Spearman 0.592, 95% CI [0.545, 0.635].
  - The gate now **passes** test size, Spearman CI, baseline and coverage. It **fails only on label type** (annotator judgements, not customer ratings) **and domain** (task dialogues + JDDC e-commerce service, not ShopNova).
  - On ShopNova conversations it is still flat: mean 3.25, SD 0.04.
  - Verdict unchanged: KPI only. The missing piece is data (real ShopNova reviews or DCH-2), not a bigger model.
- So E's main results use **no F reward**, which matches the E protocol. The E+F experiment uses only the synthetic SIM-CSAT term.

## 4. Tests

`python -m pytest v3/m7/tests -q`: **17 passed**. They cover:
- parser and refs; open conversations excluded;
- each high and medium check, including the no-false-flag case;
- inputs not modified;
- static audit on the real and on mutated policy files;
- usage stale-reference;
- gate pass/fail cases;
- feedback units against EnvV3;
- calibrator (synthetic check of the mechanism only).

The prototype code was not modified.

## 5. Questions for the Brain

1. **Reviews in the platform.** Add a `reviews` table (conversation / ticket id, rating 1–5, comment, time) to `docs/platform_contract.md`? Without it, M7 cannot "learn from real reviews" inside CallVerse.
2. **Route → E queue mapping.** E's simulator has 4 queues; the prototype routes to Agent A / B. The feedback is keyed by route and priority. Which mapping is official?
3. **French replies.** Should the SLM template have French versions? This is the prototype's lane, not F's.
4. **Next dataset.** Can DCH-2 (real helpdesk dialogues with customer satisfaction labels) be requested? It needs the user agreement. It is the only reachable candidate that could pass the gate.

## 6. Run

```bash
cd experiments/agents_ef
python -m v3.m7.make_corpus --split dev --n 120 --out $C ; python -m v3.m7.make_corpus --split test --n 120 --out $C
python -m v3.m7.report --traces $C/test/traces --out $C/report_test --scorer f:$FV3/ckpt/tinybert_ft_en_frac0.5_len128_s1 \
   --card-result v3/f/results/uss/tinybert_ft_en_frac0.5_len128.json --card-data $FV3/data_uss/test.jsonl \
   --ground-truth $C/test/ground_truth.json
# on real prototype traces: --traces <repo>/traces  (no --ground-truth)
```
