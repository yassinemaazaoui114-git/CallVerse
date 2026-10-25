# Agent F v3 — error analysis (USS TEST, dialogue-level satisfaction)

## Sources and setup

- **Sources**
  - `results/error_analysis.json`, made by `error_analysis.py` from the stored TEST predictions.
  - `results/noise_floor.json`
  - `results/uss/*.json`
- **Models**: each model's **best seed by VAL**.
  - selected neural model: `e5small_trim_ft_L6_frac0.5_len256` (seed 1)
  - TF-IDF+Ridge
  - e5 L6 /128
  - TinyBERT EN
  - per-corpus mean floor
- **TEST size**: 1,016 dialogues (EN 525, ZH 491).
- **Label**: the mean of the annotators' OVERALL ratings.
- **Snippets**
  - At most 160 characters, from the **public** USS data, last customer turn only.

## 1. The ceiling: how much can be predicted at all?

| | EN (SGD+MWOZ+ReDial+CCPE) | ZH (JDDC) |
|---|---|---|
| Expected MAE of a *perfect* predictor of the latent satisfaction (annotator noise only) | **0.234** | **0.247** |
| Per-corpus mean floor (TEST MAE) | 0.318 | 0.535 |
| Best model TEST MAE (best seed) | 0.295 (e5 L6/256 seed 1) | 0.494 (e5 L6/256 seed 1), 0.493 (TF-IDF) |
| Share of target variance that is annotator noise | 51% | 21% |
| One annotator vs the mean of the others (MAE, same TEST) | 0.50 (EN+ZH pooled) | |

**English**
- There is little headroom: only 0.08 MAE between the floor and the noise limit.
- Half of the variance of the English target is annotator noise.
- The models capture about a quarter of the remaining headroom (0.318 → 0.295).

**Chinese (JDDC)**
- JDDC is real e-commerce support and has much more learnable signal.
- Yet every model is still far from the limit (0.49 vs 0.25). This is where more data, longer context and GPU fine-tuning should pay off.

## 2. Per true class: regression to the mean

| True class (rounded) | n | e5 L6/256: MAE (signed error) | TF-IDF: MAE (signed) | per-corpus mean: MAE |
|---|---|---|---|---|
| 1 | 1 | 1.84 (+1.84) | 1.80 (+1.80) | 1.89 |
| 2 | 48 | 1.22 (+1.22) | 1.13 (+1.13) | 1.29 |
| 3 | 481 | 0.33 (+0.27) | 0.32 (+0.23) | 0.34 |
| 4 | 457 | 0.33 (−0.25) | 0.36 (−0.28) | 0.37 |
| 5 | 29 | 0.94 (−0.94) | 0.95 (−0.95) | 1.18 |

- **Every model compresses predictions toward 3–4.**
  - Unsatisfied dialogues (class 1–2, 49 cases) are over-predicted by about 1.2 points. This is the worst failure for Agent F, whose job includes flagging unhappy customers.
  - The fine-tuned model is not better than TF-IDF here.
  - Low-satisfaction recall must be improved before Agent F's score is trusted as an alarm. Options are a class-weighted or ordinal loss, or a threshold tuned on VAL.
- **Confusion matrix**: `figures/uss_confusion_best.png`.

## 3. By sub-dataset and language

| Sub | n | e5 L6/256 | e5 L6/128 | TF-IDF | per-corpus mean |
|---|---|---|---|---|---|
| SGD | 150 | 0.288 | 0.291 | 0.304 | 0.327 |
| MWOZ | 150 | 0.266 | 0.273 | 0.282 | 0.302 |
| ReDial | 150 | 0.345 | 0.342 | 0.333 | 0.352 |
| CCPE | 75 | 0.265 | 0.262 | 0.260 | 0.264 |
| JDDC (ZH) | 491 | 0.494 | 0.504 | 0.493 | 0.535 |

- **CCPE**: no model beats the per-corpus mean.
- **Context length**: going from 128 to 256 tokens helps JDDC most (0.504 → 0.494).
  - JDDC dialogues are long: median 419 e5 tokens on VAL.
  - The last-turn rating correlates only 0.31 with OVERALL on JDDC, against 0.53–0.67 on EN.
  - So the end of a JDDC dialogue alone says little about overall satisfaction.
  - TF-IDF limited to the last 128 tokens loses 0.018 on JDDC (0.511 vs 0.493), which confirms that truncation costs accuracy.

## 4. Long vs short dialogues

Split at the median length per language (`long_vs_short`).

- **EN**
  - The error is lower on long dialogues: e5 L6/256 gives 0.273 (long) vs 0.316 (short).
  - Short EN dialogues are over-predicted more (signed +0.087 vs +0.005).
- **ZH**: no difference (0.493 vs 0.496).
- Long dialogues do not hurt even though they are truncated. The end-of-dialogue context seems to be enough for EN.

## 5. Polite-but-unsatisfied and negative-words-but-satisfied

These cases are found with simple cue words checked against the **label**.

| Case | n | e5 L6/256 MAE (signed) | TF-IDF | TinyBERT EN (EN only) |
|---|---|---|---|---|
| Last customer turn is polite ("thanks", 谢谢…) **and** true < 3 | 65 | **0.60 (+0.60)** | 0.55 | 0.45 (n=57) |
| Polite and true ≥ 3 | 423 | 0.29 (−0.09) | 0.31 | 0.24 |
| ≥ 2 negative cue words **and** true ≥ 4 | 194 | 0.46 (−0.45) | 0.50 | 0.73 (n=10) |
| < 2 negative cue words and true ≥ 4 | 63 | 0.46 (−0.45) | 0.48 | 0.66 (n=6) |

- **Polite-but-unsatisfied is a real blind spot.**
  - A closing "thank you" pulls the prediction up.
  - The error is twice that of other polite dialogues (0.60 vs 0.29).
  - Example (public USS, ZH): `JDDC-1078`, last turn `谢谢`. All three annotators rated it 2; the model predicted 3.88.
- **"Negative words but satisfied" shows no specific effect.**
  - Its error is the same as for other satisfied dialogues (0.46 vs 0.46).
  - The cue list fires mostly on Chinese 不/没, which also appear in neutral questions, so this cue is not discriminative.
- Satisfied dialogues (≥ 4) are under-predicted by about 0.45 whatever the wording (regression to the mean, §2).

## 6. Annotator disagreement vs error

| Annotator std | n | e5 L6/256 MAE | TF-IDF MAE |
|---|---|---|---|
| 0 (all agree) | 263 | 0.439 | 0.422 |
| 0 < sd ≤ 0.5 | 686 | 0.374 | 0.382 |
| > 0.5 | 67 | 0.381 | 0.396 |

- **Counter-intuitive result: the error is highest when all annotators agree.**
  - Unanimous dialogues are often unanimous **extremes** (all 2s or all 4s/5s), and the models compress those (§2).
  - Spearman(|error|, annotator std): EN +0.17, ZH −0.21.
  - So disagreement explains little of the error. Regression to the mean explains more.

## 7. Worst errors (public USS snippets, last customer turn)

| id | true (annotators) | e5 L6/256 | last customer turn |
|---|---|---|---|
| ReDial-716 | 1.33 [2,1,1] | 3.17 | "You're not really helping." |
| ReDial-80 | 4.75 [5,5,4,5] | 3.33 | "bye!!" |
| SGD-142 | 1.6 [1,1,4,1,1] | 2.99 | "No, you've made quite a mess of things as it is." |
| JDDC-1958 | 2.0 [2,2,2] | 3.94 | `#E-s[数字x]#E-s[数字x]#E-s[数字x]` (emoji placeholders) |
| JDDC-1078 | 2.0 [2,2,2] | 3.88 | `谢谢` |

- Explicit complaints in the last turn ("not really helping", "made quite a mess") are still predicted near 3. The model has not learned strong negative cues from about 50 low-rated training dialogues.

## 8. Domain transfer to ShopNova-style text

These checks are small and are **not validated** with labels.

- **`infer_example.py`, selected checkpoint (measured)**
  - Three invented ShopNova dialogues score: EN resolved 3.45, FR polite-but-unresolved 3.32, EN unresolved 3.17.
  - With int8 + no offset: 3.32 / 3.19 / 3.09.
  - The order is plausible, but the range is only about 0.3: predictions are almost flat outside USS.
- **Reported by the M7 integration (not measured by Worker F)**
  - With the earlier `tinybert_ft_en_frac0.5_len128_s1` scorer, predictions on ShopNova-style single-turn conversations were nearly flat (SD 0.07).
- **Conclusion**
  - USS-trained Agent F should be treated as a **weak, uncalibrated signal on ShopNova text** until it is validated on labelled ShopNova or DCH-2 dialogues.
  - French is not in the USS training data at all.
