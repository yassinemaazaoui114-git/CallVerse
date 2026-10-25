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
