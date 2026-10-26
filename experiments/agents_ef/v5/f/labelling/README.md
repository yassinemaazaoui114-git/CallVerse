# F8 labelling package (v5) — how to get human labels for CallVerse conversations

There are **no genuine satisfaction ratings of CallVerse conversations** today. A search found no rating field
in the ShopNova database schema (users, products, orders, refunds), the code or the trace format, and no closed
unscripted conversation (`v5/deliverables/F_DOMAIN_VALIDATION.md` §1). This package lets the team collect them.

| File | What it is |
|---|---|
| `RUBRIC_AND_GUIDELINES.md` | the question, the anchored 1–5 rubric, decision rules, procedure, adjudication |
| `sheet_template.csv` | the columns of one annotator's rating sheet (sampling.py writes the filled-in item list) |
| `sampling.py` | sampling plan: strata language × priority, oversampling of likely-dissatisfied conversations (M7 flags / Intake sentiment as a prioritiser only), inclusion probabilities, pilot/dev/test split, one shuffled sheet per annotator |
| `import_eval.py` | imports the filled sheets → contract records (v4) → agreement → adjudication queue → adjudicated labels (separate file) → evaluation of Agent F (plain and IPW-weighted, per language, dissatisfied recall) → card for the F→E gate |
| `dry_run.py` | end-to-end run on the SCRIPTED M7 corpus with pseudo-random fill-in ratings |
| `dryrun_SCRIPTED_NOT_FOR_METRICS/` | its outputs. **Nothing in it is a result.** |

## Sampling plan (genuine tester conversations)

- **Size:** 460 = 30 pilot + 130 DEV + 300 TEST (inside the requested 300–500; TEST ≥ 300 is the gate minimum).
- **Language strata:** French 40%, English 40%, Arabic/other 20% (unfilled quota moves to the other languages).
- **Priority strata (prioritiser, NOT a label):** P1 "likely dissatisfied" = any high-severity M7 v5 flag, or
  escalated / sent back / reply-language mismatch / unbacked refund or follow-up promise / missed entitlement /
  pipeline error / false claim, or Intake negative sentiment with anger/sadness/fear. P0 = the rest.
  Inside each language P1 is sampled at twice its population share (at least 30%, at most 50% of the language
  quota). Why: unhappy clients are rare in a demo channel, yet they are the class Agent F misses most.
- **Weights:** every item stores `inclusion_prob = n_h / N_h`. Population estimates use weights 1 / inclusion_prob;
  model metrics are reported on the sample **and** IPW-weighted.
- **Blinding:** annotators never see the stratum, the flags or the model score; each has an own shuffled order.
- **Splits:** pilot / dev / test fixed by `sampling.py` (seeded, stratified) **before** any prediction is read.

## Commands

```bash
cd experiments/agents_ef
python -m v5.f.labelling.sampling --traces <closed tester traces> --out <plan dir> --corpus-kind genuine
#   (annotators fill sheet_ANN-*.csv; a redaction checker has removed PII first — v4 protocol §4)
python -m v4.f.eval_m7_v4 ... or AgentF.process(...)   # predictions file (agent_f_results.jsonl)
python -m v5.f.labelling.import_eval --plan <plan dir> --sheets <sheet_ANN-1.csv> <...> \
       --predictions <agent_f_results.jsonl> --out <eval dir>
#   adjudicator fills <eval dir>/adjudication_queue.csv, then re-run with --adjudication <that file>
```

## Dry-run result (SCRIPTED — NOT FOR METRICS)

The pipeline ran end to end on 240 scripted conversations: 120 sampled, 360 pseudo-random ratings imported
as valid contract records, adjudication queue built and filled, card written and **rejected by the F→E gate**
(label type `synthetic_fixture`). One design finding: in the scripted corpus **every** French conversation is
P1, because all replies are English templates (`reply_language_mismatch`). With French templates fixed, the
prioritiser becomes informative again; until then French P1 ≈ "French".
