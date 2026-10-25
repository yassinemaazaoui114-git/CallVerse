# Agent F v3 — prediction protocol

Agent F predicts **how satisfied the customer is with a support interaction, once the interaction has ended**.
It is not sentiment, emotion or intent classification. Its output is advice (for Agent E's reward and for
reporting). Agent F never acts.

## 1. Targets, one per dataset (never mixed)

| Dataset | Unit (one example) | Target | Who gave the label | Prediction time | Input |
|---|---|---|---|---|---|
| **USS** (primary) | one whole dialogue | mean of the annotators' OVERALL (dialogue-level) rating, 1–5 | 3–7 third-party annotators per dialogue | after the dialogue ends | all USER/SYSTEM turns as text (`Customer: …` / `Agent: …`, `客户/客服` for JDDC). The OVERALL line, turn ratings, action tags and JDDC explanations are **removed**. |
| **Amazon EN/FR** (auxiliary) | one product review | star rating 1–5 | the customer (self-reported) | after the review is written | the review text |

- The USS target is a **mean of annotators**, so it can be 3.33 or 3.67.
- Ordinal metrics turn the mean into a class by rounding half up: 3.5 becomes 4.
- **USS turn-level ratings are not targets here.**
  - They are used only in the error analysis, as a label-versus-label correlation.
  - A model must never see them as input, because they are labels.
- **No future information.**
  - The input is exactly what exists when the dialogue has ended.
  - Nothing written after the dialogue is used: no survey text and no annotator explanation.

## 2. Splits

- **USS**
  - One row per dialogue. Split 70/15/15 **by dialogue**, stratified per sub-dataset, fixed seed 13 (`uss_data.py`).
  - A dialogue's turns are never in two splits. The code asserts that the id sets do not overlap.
  - Exact duplicate dialogues were dropped (28 in JDDC).
  - Split SHA256 values are in `results/uss_stats.json`.
- **Amazon**: the v2 subset is reused unchanged.
  - TRAIN/VAL come from the official validation split.
  - TEST comes from the official test split.
  - Sizes: 1,200 / 400 / 399.
- **What each split is for**
  - TRAIN fits the models.
  - VAL chooses the epoch, alpha, C, tree depth and best seed.
  - **TEST is scored once per run and is never used to choose anything.**
- **Vocabulary trimming** uses the TRAIN+VAL dialogue texts (no labels), never TEST.

## 3. Groups reported

- **USS**
  - `all`
  - `lang:en` (SGD+MWOZ+ReDial+CCPE) and `lang:zh` (JDDC)
  - each sub-dataset separately
  - English and Chinese are always shown separately.
- **Amazon**: `all`, `en`, `fr`.
- **Floors**
  - `mean` predicts the overall TRAIN mean.
  - `group_mean` predicts the TRAIN mean of the dialogue's sub-dataset.
  - A model that only beats `mean` may have learned only "which corpus is this". That is why each sub-dataset is also compared with `group_mean`.

## 4. Metrics (`bench_uss.py: metrics()`)

- **MAE, RMSE**: on the continuous 1–5 scale. Predictions are clipped to [1, 5].
- **Quadratic weighted kappa (QWK)**: on rounded classes 1–5.
  - Because the English labels are mostly 3, any model that predicts about 3.2 rounds everything to 3 and gets QWK ≈ 0.
  - So QWK must be read together with Spearman.
- **Spearman**: rank correlation of prediction and target. It measures ranking ability and is not affected by rounding.
- **Accuracy**: exact accuracy and within-1 accuracy, on rounded classes.
- **3-class macro-F1**: low (< 2.5) / mid / high (≥ 3.5). Per-class precision, recall, F1 and support are also reported.
- **Confusion matrices**: 5×5 and 3×3.
- **Calibration of the error**: the mean signed error (prediction − truth) per true class. This shows regression to the mean (low classes over-predicted, high classes under-predicted).
- **Spread**: the standard deviation of predictions versus targets.
- **Seeds**
  - Fine-tuned models: 3 seeds (0, 1, 2). Tables report mean ± std over seeds.
  - The deployable checkpoint is the **best seed by VAL MAE**.
- **Cost**
  - Parameters; disk size (fp32 state dict, plus int8 for the quantized model).
  - CPU latency p50/p95 at batch 1 with 2 threads, on real TEST dialogues truncated to 256 tokens.
  - Load time; peak RSS; training time.
  - **GPU VRAM = NOT VERIFIED** (no GPU in this sandbox).

## 5. Inputs to transformer models

- **Truncation**
  - The text is truncated **from the left** to 256 tokens, so the end of the dialogue (the resolution) is kept.
  - The share of TEST dialogues that are truncated is reported per run (`test_share_truncated`).
- **e5 prefix**: e5 models get the prefix `query: `. For long dialogues the prefix is cut together with the left part.
- **Architecture**: mean pooling, then a 2-layer regression head (+3.0 bias). Trained with MSE loss.
- **Training settings**: AdamW lr 4e-5, batch 16, 5 epochs; the best epoch is chosen on VAL.

## 6. Honesty rules

- **Traceability**: every number comes from a JSON file in `results/`. Nothing is copied from memory.
- **Not comparable across datasets**: Amazon and USS numbers measure different label types and are never averaged or ranked together.
- **USS labels are third-party judgements.**
  - They come from annotators, not from the customers themselves.
  - English agreement is low (Krippendorff α ≈ 0.2–0.28).
  - This limits what any model can reach.

## 7. Deviations actually applied (CPU budget), and the selection rule

- **CPU settings for the fine-tuned models**
  - The first full-protocol run (full TRAIN, 256 tokens, 5 epochs) was stopped. e5-small 12 layers did not finish one epoch in 23 minutes on the shared CPU (15 s per batch of 16 measured).
  - All fine-tuned models were then trained on a **stratified 50% of TRAIN** (`--train-frac 0.5`, the same dialogues for every model), with **3 epochs** and **128 or 256 tokens**.
  - Classic models use the full TRAIN. `tfidf_ridge_frac0.5` is the matched comparison.
- **Truncation diagnostic**: `--tail-tokens N` keeps about the last N e5 tokens for classic models, using chars/token measured on VAL (EN 3.97, ZH 1.39).
- **Selection rule (VAL only)**: among models whose VAL MAE (all) is within about one seed-std of the best fine-tuned VAL MAE, take the smallest and fastest.
- **int8**: the optional offset is one number fitted on VAL (mean label − mean int8 prediction), never on TEST.
