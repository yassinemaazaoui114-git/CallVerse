# F8 — Domain validation: can Agent F's score be trusted on CallVerse conversations?

**Worker F, v5, 2026-10-26.**
- Package: `v5/f/labelling/` (rubric, sampling plan, sheet template, import/evaluation script, dry run).
- Tests: `v5/f/tests/test_labelling.py` (5).
- It builds on `v4/f/ANNOTATION_PROTOCOL.md` (consent, PII, storage, sample size) and the v4 reviews contract (`v4/f/contracts/`). Both are reused, not changed.

## Verdict (target-domain trust)

**Not trustworthy yet: unvalidated.** No genuine rating of any CallVerse conversation exists, so Agent F's satisfaction score on CallVerse / ShopNova can only be called *indicative, out of domain*:
- English: indicative only;
- French: withheld (no number);
- the F→E gate: closed.

Every USS number in this round (`F_EVALUATION.md`) describes other dialogues, with other labels. The v4 analysis also showed that USS dialogues cut to the ShopNova shape carry almost no signal (`v4/deliverables/AGENT_F_DOMAIN_SHIFT_ANALYSIS.md`). Only the labelling below can change this verdict.

## 1. No genuine CallVerse ratings exist (checked again in v5)

| Where | What was searched | Result |
|---|---|---|
| ShopNova database (`callverse/data/shopnova.db` copies; schema) | a rating / feedback column | tables users, products, orders, refunds: **none** |
| Code, configs, data of the 4 local checkouts (CallVerse, -integration, -research, -voice), `experiments/` excluded | `rating`, `csat`, `satisfaction` | only `callverse/slm/dev_decisions.json` (AI-written SLM examples): no rating |
| Trace files (267 found under `/home/user` and `/tmp`) | closed conversations (`pipeline_done`) | only the 6 scripted demo copies in `v4/f/demo_traces/`. **No unscripted closed conversation** |
| Scripted M7 corpus (240) | — | scripted agents and planted defects. **Never usable as labels** |

## 2. The labelling package

| Item | Where | Key decisions |
|---|---|---|
| **Rubric 1–5, anchored** | `labelling/RUBRIC_AND_GUIDELINES.md` §2 | rate the **support interaction**, not the product. Correctness first; a correct refusal is 3–4; the wrong language caps the score at 2; tone moves the score by at most 1 point |
| **Guidelines** | same, §1, §3, §4 | annotators read only what the client saw. They are blind to the M7 flags, Agent F's score and the sampling stratum. "Cannot judge" is allowed, guessing is not. A pilot of 30 comes first, with stop rule α (ordinal) < 0.40 |
| **Disagreement → adjudication** | same, §5; `import_eval.py` | the queue holds ratings spread ≥ 2 **or** straddling the dissatisfied line (≤ 2 vs ≥ 3). One blind adjudicator, not an annotator. The original ratings are kept. Adjudicated labels go to a **separate** file (`label_source = adjudicated_human`). Two gold labels are reported: the mean (USS-comparable, read by the gate) and adjudicated-else-mean |
| **Sampling plan: 460 conversations** (30 pilot + 130 DEV + 300 TEST) | `labelling/README.md`, `sampling.py` | strata: language (FR 40%, EN 40%, AR/other 20%) × priority. P1 "likely dissatisfied" comes from **M7 flags / Intake sentiment, used as a prioritiser only, never as a label**. P1 is oversampled to 2× its share (between 30% and 50% of each language's quota). Each item stores its inclusion probability, and metrics are reported plain **and** IPW-weighted. Splits are fixed (seeded) before any prediction |
| **Sheet template** | `labelling/sheet_template.csv` | one sheet per annotator, own shuffled order; columns `rating_1to5`, `confidence`, `cannot_judge_reason`, `comment` |
| **Import / evaluation** | `labelling/import_eval.py` | checks the sheets (out-of-range ratings, unknown items, duplicates, empty ratings without a reason). It converts them to v4-contract **annotator** records (validated), computes agreement (Krippendorff α ordinal / interval, human leave-one-out MAE) and builds the adjudication queue. It then evaluates on TEST: MAE, Spearman, IPW MAE, recall of the dissatisfied class, per language, and conversations not scored. The output is the v4 card and gate |
| **Kept apart** | contract + separate file | customer-submitted ratings (`customer_submitted`), annotator ratings (`annotator`), adjudicated labels (own file) and AI predictions (`ai_predicted`) are never stored in the same field or file. **LLM ratings are never ground truth**: the package has no path that accepts them |

## 3. Dry run on the scripted corpus — SCRIPTED, NOT FOR METRICS

- Folder: `v5/f/labelling/dryrun_SCRIPTED_NOT_FOR_METRICS/`. Command: `python -m v5.f.labelling.dry_run`.
- The fill-in "ratings" are **pseudo-random integers from numpy (seed 0)**. They are not human, not model and not LLM ratings.

| Step | Outcome |
|---|---|
| Sampling | population 240 → 120 sampled. Allocation: en/P0 34, en/P1 34, fr/P1 52 |
| Sheets | 3 sheets × 120 items; 360 ratings imported; 0 sheet errors; all records valid against the v4 contract |
| Adjudication | queue of 77 items (with random ratings, most items disagree, as expected); filled automatically with the median for the dry run only |
| Evaluation | 81 TEST items; 35 not scored (French withheld, as designed); card written |
| Gate | **rejected**: label type `synthetic_fixture`, test_n 81 < 300 |

**Design findings from the dry run**
1. In the scripted corpus **every French conversation falls in P1**: all replies are English templates, so all French conversations get `reply_language_mismatch`. Until French templates exist, French P1 means just "French". The prioritiser becomes informative again once French replies exist.
2. The first version of the allocation could overshoot n by 1–2 through rounding. A unit test found it, and it is fixed.

## 4. What the team must decide (Brain / Yassine)

1. Run the labelling with volunteer testers. It needs the consent and data-protection steps of the v4 protocol §3–4.
2. Add a post-chat customer rating to the platform (the v4 contract). Only that label type can open E's reward.
3. Ask the authors of the Taobao Clothes/Makeup data (genuine customer ratings, ZH) for research permission (`F_DATA_PROVENANCE.md` §4).
