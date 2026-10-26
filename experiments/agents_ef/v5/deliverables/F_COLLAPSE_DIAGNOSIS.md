# F2 — Prediction collapse: why Agent F's scores stay near 3 (v5, building on v4)

**Worker F, v5, 2026-10-26.**
- Code: `v5/f/collapse.py`. Results: `v5/f/results/f2_collapse.json`.
- Figures: `v5/f/figures/f2_calibration.png`, `f2_pred_dist_by_sub.png`, `f2_truncation_and_loss.png`.
- v4 (`AGENT_F_DOMAIN_SHIFT_ANALYSIS.md`) already showed four things, not redone here:
  - inference is correct;
  - ShopNova texts are not truncated;
  - ShopNova's 2-turn shape carries almost no USS signal;
  - minimal-pair probes move the score in the right direction, but only a little.
- v5 adds what was missing, on USS, where labels exist.
- Data use:
  - selection-type analyses use **VAL** only;
  - the TEST predictions read here are the **V3 ones, already inspected** in V3 and V4. They are used for diagnosis only, never to choose anything.

## In plain words

- The models are not broken and not biased "on average". When a model says 3.6, the true average is about 3.6 (calibration).
- They stay close to the middle because the text explains only a small part of why one annotator panel gave 2 and another gave 4.
  - In English, the labels themselves hardly vary and the annotators disagree with each other.
  - A sensible model that is unsure says "about average", and that is exactly the behaviour seen.
- Changing the training loss (Huber, ordinal) does not fix this. Stretching the scores to look more varied makes the error much worse.
- Cutting the dialogue so that its end is kept is right. The end is where the client reacts. More text beyond the last ~256 tokens does not help.

## 1. Per-class error (true label rounded; USS TEST, V3 models)

| True class | n | Ridge V3: mean pred / signed error | e5 V3: mean pred / signed error |
|---|---|---|---|
| 1 | **1** | 3.13 / +1.80 | 3.17 / +1.84 |
| 2 | 48 | 3.36 / **+1.12** | 3.46 / **+1.22** |
| 3 | 481 | 3.26 / +0.23 | 3.30 / +0.27 |
| 4 | 457 | 3.63 / −0.29 | 3.67 / −0.25 |
| 5 | 29 | 4.01 / −0.89 | 3.95 / −0.94 |

- **Dissatisfied subset** (label ≤ 2.5, n = 62): MAE 1.03 (Ridge) and 1.12 (e5), against ~0.39 overall.
- Class 1 has a single TEST dialogue, so no conclusion is possible for it.

## 2. Calibration and regression to the mean

| | slope of prediction on label b(p\|y) | slope of label on prediction b(y\|p) | R² | pred SD / label SD |
|---|---|---|---|---|
| Ridge V3, TEST all | 0.335 | **1.07** | 0.36 | 0.35 / 0.63 |
| e5 V3, TEST all | 0.324 | **1.05** | 0.33 | 0.35 / 0.63 |
| Ridge, VAL all | 0.322 | **0.96** | 0.31 | 0.36 / 0.61 |
| Ridge, VAL EN only | 0.112 | 1.00 | **0.11** | 0.14 / 0.42 |
| Ridge, VAL ZH only | 0.105 | 0.89 | **0.09** | 0.22 / 0.64 |
| group_mean (corpus id only), TEST all | 0.235 | 1.02 | **0.24** | 0.30 / 0.63 |

**Reading the table**
- **b(y|p) ≈ 1:** the predictions are calibrated. In each TEST prediction decile the mean label is within ~0.1 of the mean prediction (`f2_calibration.png`, left).
- **For a calibrated predictor, b(p|y) equals R².** So a slope of ~0.33 is not a defect of the head. It is what an honest model must output when it explains about a third of the variance.
- **The real problem is the small R² within a language: 0.09–0.17.**
  - Most of the pooled R² comes from telling JDDC (mean 3.76) from the English corpora (≈ 3.1–3.2).
  - The corpus identity alone gives R² 0.24.
- Per sub-corpus, the prediction SD is 0.11–0.24 against a label SD of 0.35–0.67 (`f2_pred_dist_by_sub.png`).
- **Noise ceiling** (V3): annotator α is 0.20–0.28 for EN and 0.52 for ZH. A perfect model would still have MAE ≈ 0.23–0.25.

## 3. Does the head or the loss compress the outputs? Same data and features, VAL only

| Features | Loss / head | VAL MAE | Spearman | QWK | pred SD | b(y\|p) | MAE dissatisfied | MAE ≥ 4 |
|---|---|---|---|---|---|---|---|---|
| TF-IDF (V3 recipe) | Ridge (MSE) | 0.3954 | 0.565 | 0.437 | 0.356 | 0.96 | 0.991 | 0.488 |
| | SGD, squared (same solver as Huber) | 0.3954 | 0.566 | 0.445 | 0.359 | 0.95 | 0.994 | 0.486 |
| | SGD, **Huber** ε 0.5 | **0.3937** | 0.561 | 0.428 | 0.373 | 0.91 | 1.050 | 0.443 |
| | **ordinal** (Frank & Hall, cumulative logistic) | 0.4029 | 0.558 | 0.441 | 0.372 | 0.92 | **0.976** | 0.500 |
| frozen pretrained e5-small (mean pool, 256) | linear MSE | 0.4047 | 0.541 | 0.423 | 0.341 | 0.97 | 1.037 | 0.512 |
| | linear Huber | 0.4085 | 0.530 | 0.420 | 0.395 | 0.81 | 1.065 | 0.440 |
| | ordinal | 0.4108 | 0.531 | 0.451 | 0.355 | 0.93 | 1.003 | 0.535 |
| | 2-layer MLP, MSE (the fine-tuned head's shape) | 0.4067 | 0.535 | 0.431 | 0.447 | 0.73 | 1.025 | 0.412 |
| | 2-layer MLP, Huber | 0.4021 | 0.533 | 0.418 | 0.439 | 0.74 | 1.107 | 0.365 |

**Verdict: the loss is not the cause.**
- MSE and Huber differ by ≤ 0.005 MAE. Huber helps the 4–5 classes, because it moves predictions toward the conditional median, which is higher than the mean. It **hurts** the dissatisfied class (TF-IDF 0.99 → 1.05; MLP 1.03 → 1.11).
- The ordinal loss improves the dissatisfied class only slightly (−0.015 / −0.034) and costs overall MAE (+0.008).
- The MLP head spreads its predictions more (SD 0.45) but is less calibrated (b(y|p) 0.73) and no more accurate.

**Consequence (pre-registered rule, `NOTEBOOK.md`):** a Huber fine-tune of e5 was **not run**. The rule required a gain ≥ 0.003 on both feature types, or ≥ 0.05 on the dissatisfied class.

## 4. Inflating the variance (a demonstration, not used by any model)

- Stretching the Ridge VAL predictions around their mean so that their SD equals the label SD gives:
  - EN: MAE 0.307 → **0.376**;
  - ZH: MAE 0.490 → **0.602**.
- QWK rises (EN −0.01 → 0.19), because more predictions cross the rounding thresholds.
- "More spread" looks better on the class chart and on QWK, but it is less accurate. It was not done.

## 5. Truncation side and length (V3 Ridge recipe, VAL)

| Tokens kept | from the END (tail) | from the START (head) |
|---|---|---|
| 128 | 0.3994 | 0.4127 |
| 256 | **0.3954** | 0.4062 |
| 512 | 0.3973 | 0.3962 |
| full text | 0.3956 | |

**Reading the table**
- At equal length the end beats the start (−0.013 at 128 tokens, −0.011 at 256).
- At 512, most dialogues fit whole, so the two sides converge.
- Beyond 256 tail tokens there is no gain.
- This supports V3's left truncation. It is also why 384-token training was not run (F4).

## 6. What this means for Agent F

1. "Collapse" on USS = calibrated shrinkage under low within-language signal and noisy, narrow labels. It is not a modelling bug. No loss, head or rescaling trick gives real accuracy on the extremes.
2. The dissatisfied class (6% of TEST) is predicted ~1.1 points too high by every model. Agent F must **not** be used to detect individual unhappy clients. M7's deterministic flags are the right tool for that.
3. On ShopNova the compression is worse (v4: prediction SD 0.04–0.07) because the client's reaction is missing. Only data of the right shape and label can change that (`F_DOMAIN_VALIDATION.md`).
