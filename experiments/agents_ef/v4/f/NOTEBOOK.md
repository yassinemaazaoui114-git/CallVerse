# Agent F v4 — research notebook (Worker F, overnight session 2026-10-25/26)

Format: hypothesis -> experiment -> result -> conclusion. Failures are kept. Every number points to a file.
Environment: CPU only, <= 2 threads, nice 10, shared with Workers D and E (`env.sh`).

## N1 — Re-fit and save the V3 TF-IDF+Ridge (last 256 tokens) scorer (F2, first step)
- Hypothesis: the V3 recipe in `v3/f/bench_uss.py` is deterministic, so a re-fit reproduces V3 exactly.
- Experiment: `python -m v4.f.tfidf_predictor` (log `logs/tfidf_refit.log`), same data, same alpha grid on VAL,
  final fit on TRAIN only, TEST scored once only to compare with V3.
- Result (`results/tfidf_ridge_tail256_reproduction.json`): alpha 3 (V3: 3); VAL MAE 0.39542 (V3 0.39542);
  TEST MAE 0.39187 (V3 0.39187); all 1,016 TEST predictions equal to V3 at 4 decimals (max diff 0.0);
  193,429 parameters; fit 25.8 s on 2 threads. Saved at `$FV3/ckpt/tfidf_ridge_tail256/model.joblib`
  (3.08 MB, SHA256 `1c2018532cf6b50631eca9e150e66b94f2ac8c1cdfead1d620e44b7088a75261`, checked on load).
- Conclusion: reproduced exactly. It is now a loadable predictor with the SatisfactionPredictor interface.

## N2 — F1: why are predictions flat on ShopNova? (`diagnose_shift.py`, `results/f1_diagnosis.json`)
- H1 (implementation bug): the loaded checkpoints are not the ones that were measured.
  Test: re-score the first 60 USS TEST ids, compare with `test_pred` stored in the V3 result JSON (best seed by VAL).
  Result: max |diff| 5e-05 for e5-L6/256, TinyBERT-EN and TF-IDF (= the 4-decimal rounding of the stored values).
  Full USS TEST recomputed: e5 MAE 0.3912 / Spearman 0.592; TF-IDF 0.3919 / 0.596; TinyBERT-EN 0.3048 / 0.369.
  Conclusion: REJECTED. Inference code = measured code.
- H2 (left truncation hides the customer): ShopNova texts are 49-111 e5 tokens (mean 80), 0% truncated
  (USS TEST: mean 425 tokens, 81.5% truncated at 256). The whole customer message is always seen.
  Conclusion: REJECTED for ShopNova (truncation matters for USS, not for ShopNova).
- H3 (structure mismatch): USS TEST = 27.9 turns (14.4 customer turns), the customer speaks last in 30% (EN 54%);
  ShopNova = exactly 2 turns, 1 customer turn, the agent (template) ALWAYS speaks last; customer share of the
  text 22% vs 38%. The cues that move USS predictions (customer's reaction at the end, repeated asks) do not exist
  in a single-turn conversation. Probe: appending "Customer: Great, thank you so much" moves e5 by +0.10/+0.17,
  TinyBERT +0.23/+0.25, TF-IDF +0.10/+0.14. Conclusion: SUPPORTED (main cause, with H4).
- H4 (regression to the mean inherited from EN labels): USS TRAIN EN labels mean 3.16, SD 0.40, 72% in [2.5, 3.5),
  3.4% below 2.5. On USS TEST EN the models already predict a narrow band: SD e5 0.154, TF-IDF 0.138,
  TinyBERT 0.186 (label SD 0.41). Signed error for true class 1: +1.84 (e5), +1.80 (TF-IDF), +1.73 (TinyBERT).
  ShopNova SD: e5 0.042, TinyBERT 0.069, TF-IDF 0.050 = 27% / 37% / 36% of each model's own USS-EN SD.
  Conclusion: SUPPORTED. On English text these models are "about 3.2 ± a little" by construction.
- H5 (models are blind on short text): minimal pairs (synthetic, `probe_set()`): the direction is mostly right but
  the effects are small. Resolved -> refused: e5 -0.11/-0.12, TinyBERT -0.12/-0.07, TF-IDF -0.29/-0.26.
  Calm -> angry: e5 -0.04/-0.01, TinyBERT -0.08/-0.03, TF-IDF -0.06/+0.03 (wrong sign on the status pair).
  USS-format positive vs negative control: e5 0.33, TinyBERT 0.51, TF-IDF 0.38. Conclusion: PARTLY SUPPORTED —
  not blind, but the per-pair effect is below the noise one would need for a per-conversation signal.
- Calibration on USS TEST (quintiles): mean prediction ≈ mean label in every quintile (within 0.1), i.e. calibrated
  "on average", while per true class the error is strongly signed (regression to the mean).
- What cannot be concluded: whether ShopNova satisfaction really varies, or whether the small differences
  are in the right order on real ShopNova clients. No ShopNova ground truth exists. Variance is not accuracy:
  a wider spread would not prove anything without labels.

## N3 — F2: targeted TF-IDF experiments about the domain mismatch (`f2_experiments.py`, `results/f2_experiments.json`)
Selection on VAL only (rule fixed in the script: lowest VAL MAE; within 0.002 prefer fewer parameters).

| Variant (question) | Params | VAL MAE | VAL EN | VAL ZH | VAL Spearman EN | pred SD EN |
|---|---|---|---|---|---|---|
| baseline (V3 tail 256) | 193k | 0.3954 | 0.3070 | 0.4900 | 0.317 | 0.140 |
| two_turn: first customer + last agent turn (ShopNova shape) | 33k | 0.4130 | 0.3174 | 0.5152 | 0.196 | 0.097 |
| customer_only | 121k | 0.3928 | 0.2996 | 0.4924 | 0.367 | 0.147 |
| roles: full + customer-only + last customer turn blocks | 325k | **0.3880** | 0.2957 | 0.4866 | 0.386 | 0.181 |
| lang_split (one Ridge per language) | 194k | 0.3962 | 0.3066 | 0.4919 | 0.314 | 0.138 |
| roles_lang_split | 326k | 0.3882 | 0.2948 | 0.4881 | 0.381 | 0.180 |

- Finding A (two_turn): when USS dialogues are cut to the ShopNova shape, VAL MAE 0.413 ≈ the per-corpus floor
  (V3 VAL floor 0.414); ZH 0.515 is WORSE than its floor 0.510; EN Spearman falls 0.317 -> 0.196.
  Conclusion: in a one-message + one-reply conversation there is almost no learnable satisfaction signal of the
  USS kind. This explains the flat ShopNova scores better than any model defect. A bigger model would not fix it.
- Finding B (customer_only > baseline on VAL): the customer's words carry most of the signal.
- Finding C (lang_split): no gain; the pooled model already handles the language difference.
- Selected on VAL: `roles`. TEST scored once (`results/f2_test_roles.json`): MAE 0.3906 vs baseline 0.3919;
  EN 0.3011 vs 0.3012; ZH 0.4864 vs 0.4888; Spearman 0.597 vs 0.596.
  Paired bootstrap on TEST (`results/f2_compare.json`): diff -0.0012, 95% CI [-0.0080, +0.0063]. NOT significant:
  the VAL gain (-0.0075) did not transfer. (Failure of the hypothesis "role separation helps", kept here.)
- `roles` on ShopNova: SD 0.084 vs 0.050 (baseline) — but more spread is not more accuracy: on the probes it gets
  the wrong sign in 3 of 7 probe groups (status calm -> angry +0.17; complaint closing turn > no closing turn in both closing groups, +0.03/+0.04); baseline: 1 group (+0.03).
- Saved anyway for traceability: `$FV3/ckpt/tfidf_roles_tail256/` (SHA256 318bbbf2…, 5.15 MB; first save pickled
  `__main__.BlockModel`, re-saved as plain parts without re-fitting, see meta.json `note`).
- Decision: keep the V3 TF-IDF tail-256 (now saved) as the recommended scorer: same TEST accuracy, fewer
  parameters, fewer wrong-direction probe responses. Quantization: not useful (3 MB, ~3-6 ms); not done.

## N4 — F4: M7 v4 (`m7/`, `agent_f.py`, `eval_m7_v4.py`; results `results/m7/{dev,test}/`)
- Built on DEV only. Code hashes frozen in `results/m7/frozen_code_sha256.json` after the dev run; the held-out
  run refuses to start if any of the 9 source files changed, and refuses a second run.
- Changes vs V3, each justified by a test or a dev finding:
  1. claim_contradicts_data -> claim_false (contradicts data) + claim_unsupported (agent run never received the fact).
  2. missed_entitlement no longer fires when the refund was offered and the client is asked to confirm
     (outcome ask_user): FOUND ON DEV (2 of 2 dev flags were this case; V3 counted them as missed).
  3. FAILED IDEA, reverted: a word-boundary leak pattern. I believed V3 matched "agency"; the boundary test showed
     it does not ("agency" has no "agent" substring). Kept V3's check; documented the remaining substring risk
     ("reagent" is flagged).
  4. Per-conversation rule warnings: global facts (8 unreviewed rules) removed from each conversation (dev showed
     71 repeated warnings = noise); they stay once in the owner report.
- DEV (120): wiring recall 21/21 planted defects that occurred; 0 false positives on 90 clean conversations;
  evidence refs 196/196 re-read and matched; language detector 120/120 vs corpus language.
- HELD-OUT TEST (120, run once): wiring 16/16; 0 false positives on 91 clean; refs 184/184; reply_language_mismatch
  flagged 23/23 French and 0/97 English conversations; missed_entitlement V3 2 -> v4 1 (test-0030 = ask_user case
  removed; test-0031 = real: a refund due after a refused proposal ended as info). claim_unsupported occurred 0
  times in both corpora (scripted agents always read their facts): it is validated only by unit tests.
- Satisfaction (TF-IDF tail-256): EN conversations get indicative scores (97 test / 91 dev); French ones get NO
  score (23 / 29, validity withheld_language_not_validated). e_reward_allowed = false (label_type, domain, coverage).
- Honest reading: the corpus is scripted; recall is a wiring check, not real-world accuracy.

## N5 — F4 robustness: benign-mutation stress test on DEV (`m7_stress.py`)
- Hypothesis: the clean scripted corpus hides false positives that real logs would trigger.
- Experiment: 5 meaning-preserving mutations of the 120 DEV traces; every flag must stay the same.
- Result v4.0 (`results/m7_stress_dev_v4_0.json`): numbers written as strings in facts_used ("8", "59.9")
  changed the flags of **16/120** conversations (new false claim_false). Float noise, noise lines, a garbled line,
  and 5-conversation batch files: 0/120 changed, refs all valid.
- Fix v4.1: compare numeric / boolean strings as numbers / booleans (`quality_v4.norm`), unit-tested.
  Result v4.1 (`results/m7_stress_dev_v4_1.json`): 0/120 changed for all 5 mutations.
- The fix came AFTER the held-out run. A documented post-freeze re-check (`results/m7/test_v4_1/`, mode
  `--post-freeze-tag`) gives identical held-out flags, recall and evidence numbers (the held-out traces contain
  no string-typed claims). The first held-out run is kept unchanged in `results/m7/test/`.

## N6 — F3 dataset recheck (`DATASETS_RECHECK.md`)
- DCH-2's S-score is satisfaction judged by 19 student annotators, not by customers: even with the agreement,
  DCH-2 would fail the gate's label-type check. V3's "only candidate that could pass the gate" was wrong.
- Access: Google-form user agreement, non-commercial research / education. NOT accepted (not my decision).
- No accessible dataset of support dialogues with genuine customer ratings was found (HF API search, web).
- No real prototype trace with a closed conversation exists (13 files, 0 pipeline_done).

## N7 — "learns from real reviews" wired into AgentF (`AgentF.learn_from_reviews`)
- V3's ReviewCalibrator (isotonic, 5-fold CV, >= 50 reviews, kept only if it helps) + review_bias, fed by
  contract records. Only measured, consented, non-synthetic ratings are used. Tested only on the SYNTHETIC
  fixture (mechanism check). There are no real reviews, so no real number exists.
