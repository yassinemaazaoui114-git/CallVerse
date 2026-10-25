# Agent F — why satisfaction predictions are nearly constant on ShopNova (F1)

**Worker F, v4, 2026-10-26.**
- Code: `v4/f/diagnose_shift.py`. Results: `v4/f/results/f1_diagnosis.json`. Figures: `v4/f/figures/f1_*.png`.
- Also cited: `v4/f/f2_experiments.py` and `v4/f/results/f2_experiments.json`.
- CPU only, 2 threads.

## In plain words

- Agent F's satisfaction models give almost the same score (about 3.2–3.3 out of 5) to every ShopNova conversation.
- **The code is not the cause.** The saved models reproduce their measured test predictions to 4 decimals.
- **Truncation is not the cause.** ShopNova conversations are short, so the models see all of them.
- **There are two real causes:**
  1. The models learned from long, multi-turn dialogues whose English labels hardly vary (most are "3"). So on English text they always predict a narrow band.
  2. A ShopNova conversation is one client message plus one template reply, with no client reaction at the end. That reaction is the main clue the models use.
- When USS dialogues are cut to the ShopNova shape, the best model falls to the level of "always predict the average". So the information is simply not there.
- **What we cannot say without labelled ShopNova conversations:** whether ShopNova clients really differ in satisfaction, or whether the small differences the models show are in the right order.

## 1. Hypotheses and verdicts

| # | Hypothesis | Test | Result | Verdict |
|---|---|---|---|---|
| H1 | Inference bug (wrong checkpoint, wrong preprocessing) | Re-score 60 USS TEST items. Compare with `test_pred` stored in the V3 result JSON (best seed by VAL). Recompute the full TEST metrics. | max abs diff **5e-05** for all 3 scorers (= 4-decimal rounding). Full TEST: e5 MAE 0.3912 / Spearman 0.592; TF-IDF 0.3919 / 0.596; TinyBERT-EN 0.3048 / 0.369, same as V3 | **Rejected** |
| H2 | Left truncation hides the customer | Token counts with the models' own tokenizers | ShopNova: 49–111 e5 tokens (mean 80). **0% truncated** at 256 (TinyBERT: 0% at 128). USS TEST: mean 425, 81.5% truncated | **Rejected for ShopNova** |
| H3 | Input structure differs | Turns, speakers, who speaks last | See table 2 | **Supported** (main cause) |
| H4 | Regression to the mean inherited from the EN labels | Label distribution; prediction spread on USS EN | See table 3 | **Supported** |
| H5 | The models are blind on short text | Minimal pairs (synthetic probes) | Direction mostly right, effects small (table 5) | **Partly supported** |
| H6 | Signal exists in the ShopNova shape but is missed | Train and evaluate TF-IDF on USS cut to "first customer turn + last agent turn" (VAL only) | VAL MAE 0.413 ≈ per-corpus floor 0.414. ZH 0.515 is worse than its floor 0.510. EN Spearman 0.317 → 0.196 | **Rejected**: almost no USS-type signal in that shape |

## 2. Input structure (H2, H3)

Source: `results/f1_diagnosis.json` → `structure`.

| | USS TEST (all) | USS TEST (EN) | ShopNova corpus (dev + held-out, 240) |
|---|---|---|---|
| characters, mean | 1,098 | 1,522 | 291 |
| turns, mean (median) | 27.9 (25) | 23.4 (22) | **2.0 (2)**, always |
| customer turns, mean | 14.4 | 12.1 | **1**, always |
| the customer speaks last | 30.0% | 54.3% | **0%** (the template reply is always last) |
| e5 tokens, mean | 425 | 385 | 80 |
| share truncated (e5, 256) | 81.5% | 75.8% | **0%** |
| customer share of the text in the kept window | 38% | 45% | 22% |
| TinyBERT unknown-token rate on French ShopNova text | — | — | 0.0 (the word pieces exist, but the model never saw French in training) |

**Reading the structure table**
- A USS dialogue tells its satisfaction through what the customer does: repeats a request, says "no, not that", or says "great, thanks" at the end.
- A ShopNova conversation has none of this.
- About 78% of each conversation's characters are the template reply, with the order facts filled in ("Hello, here is the latest information about your order …").
- All 120 dev replies come from the SLM's fallback templates (`reply_source = template`). There are 101 distinct strings only because the slot values differ.

## 3. Labels and regression to the mean (H4)

| USS TRAIN labels | n | mean | SD | share in [2.5, 3.5) | share < 2.5 |
|---|---|---|---|---|---|
| EN | 2,450 | 3.16 | 0.40 | **72%** | 3.4% |
| ZH | 2,290 | 3.76 | 0.63 | 23% | 3.6% |

| Scorer | Pred. SD, USS TEST all | Pred. SD, USS TEST EN | Pred. SD, ShopNova | ShopNova SD / own USS-EN SD | Signed error, true class 1 | Signed error, true class 5 |
|---|---|---|---|---|---|---|
| e5 trim L6/256 (17.4M) | 0.347 | 0.154 | **0.042** | 0.27 | +1.84 | −0.94 |
| TinyBERT-EN (14.4M) | 0.186 (EN only) | 0.186 | **0.069** | 0.37 | +1.73 | −1.26 |
| TF-IDF+Ridge tail-256 (0.19M) | 0.351 | 0.138 | **0.050** | 0.36 | +1.80 | −0.89 |

**Reading the labels tables**
- Most of the overall USS spread is the difference between Chinese and English dialogues.
- On English text the models already predict 3.2 ± about 0.15 on USS. ShopNova removes most of the remaining cues.
- **Calibration**, `figures/f1_calibration_uss_test.png`:
  - "On average" the models are calibrated: in each USS TEST quintile the mean prediction is within 0.1 of the mean label.
  - Per true class they shrink strongly toward the mean: very unhappy dialogues are over-predicted by about 1.8.

## 4. Outputs on ShopNova by corpus metadata (not labels)

The corpus metadata are the scenario settings (tone, language, defect). They are **not** satisfaction labels.
They show only whether the scores move with anything at all.

| Mean predicted score | e5 | TinyBERT | TF-IDF |
|---|---|---|---|
| angry − calm client | −0.052 | −0.110 | −0.023 |
| French − English client | +0.063 | +0.070 | +0.058 |
| planted defect − clean | +0.002 | −0.005 | −0.017 |
| dev − held-out split | +0.004 | +0.006 | +0.007 |

- The scores do not see the defects at all.
- French conversations get **higher** scores from every model. Nothing in the data supports that, and none of the models was validated on French dialogues. It is one more reason M7 v4 **withholds** French scores.

## 5. Minimal-pair probes (H5)

- The probes are hand-written and synthetic (`probe_set()` in `diagnose_shift.py`). They reuse the prototype's real template wording.
- Each value is the difference from the first variant. Figure: `figures/f1_probes.png`.

| Probe (what changes) | e5 | TinyBERT | TF-IDF |
|---|---|---|---|
| refund reply, calm → angry customer | −0.040 | −0.077 | −0.058 |
| status reply, calm → angry customer | −0.010 | −0.033 | **+0.029** (wrong sign) |
| calm customer, refund approved → refused | −0.106 | −0.123 | −0.286 |
| angry customer, approved → refused | −0.116 | −0.074 | −0.260 |
| refund approved, + "Customer: Great, thank you so much" | +0.098 | +0.227 | +0.097 |
| escalated, + "thank you" | +0.169 | +0.254 | +0.140 |
| refund approved, + "This is useless" | −0.045 | −0.089 | −0.029 |
| USS-format positive vs negative dialogue (control) | 0.326 | 0.506 | 0.383 |

**Reading the probes**
- The models are not blind: refused < approved, and a thank-you raises the score.
- But a full swing from "refund approved" to "refused" moves the score by 0.1–0.3 on a 1–5 scale.
- The clearest cue (a closing turn by the client) does not exist in the prototype's single-turn conversations.

## 6. What can and cannot be concluded

**Can be concluded (evidence above)**
1. The flat output is **not** an implementation error and **not** truncation.
2. It is mostly **structural**: no client reaction, one turn, template text. It is made worse by **label compression** (English USS labels ≈ 3).
3. More model parameters would not help. In the ShopNova shape, a model trained on USS is at the floor (H6). The missing piece is **data of the right shape and label**.

**Cannot be concluded without ShopNova ground truth**
1. Whether real ShopNova satisfaction varies a lot or a little.
2. Whether the score ranking on ShopNova is right.
3. Anything about French or Arabic.

**Variance is not accuracy.** The F2 `roles` model spreads ShopNova scores more (SD 0.084 vs 0.050). It still gets the probe direction wrong in 3 of 7 groups (baseline: 1) (`results/f2_compare.json`).

## 7. Consequences applied in v4

- M7 v4 attaches validity to every score:
  - English ShopNova conversations: `indicative_out_of_domain`;
  - French: **withheld** (no number);
  - comparisons by grade, rule or resolution: **not shown**.
- The F→E gate stays closed with explicit reasons.
- The fix is data:
  - the annotation protocol (`v4/f/ANNOTATION_PROTOCOL.md`);
  - the reviews contract (`v4/f/contracts/`);
  - multi-turn conversations in the prototype, so a closing client turn exists. This is a prototype decision for the Brain.
