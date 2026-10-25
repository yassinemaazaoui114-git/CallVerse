# 05 — Agent F results (V3)

**Agent F** predicts **how satisfied a customer is with a support interaction once it has ended** (1–5).
It is not sentiment, emotion or intent. Agent F only *advises* (Agent E reward, owner reports, M7 review); it never acts.

All numbers come from files in `v3/f/results/`. CPU only, 2 threads, shared with another job. GPU = NOT VERIFIED.

## 1. Datasets and label types (never mixed)

| Dataset | Role | Label | Who labels | Unit | Split |
|---|---|---|---|---|---|
| **USS** (Sun et al. 2021): SGD, MWOZ, ReDial, CCPE (EN) + **JDDC (ZH, real e-commerce support)** | **primary** | dialogue-level satisfaction 1–5, mean of 3–7 annotators | third-party annotators | whole dialogue | 70/15/15 **by dialogue** (4,740 / 1,016 / 1,016) |
| Amazon Multilingual Reviews EN/FR | auxiliary | product stars 1–5 | the customer | one review | 1,200 / 400 / 399 (v2) |

- **Rejected or blocked datasets**
  - Saif7800/customer_qa_dataset: synthetic; CSAT is derived from a sentiment tag.
  - DialEval-2/DCH-2: a user agreement is required.
  - Flipkart CSAT mirror: no dialogue text.
  - Local CallVerse datasets: BLOCKED (no access).
  - Details: `DATASETS.md` and `data_provenance.json`.
- **USS label quality** (`results/uss_stats.json`, `results/noise_floor.json`)
  - English labels concentrate on 3 (std 0.35–0.45) and agree poorly: Krippendorff α 0.20–0.28.
  - JDDC labels spread more and agree better: α 0.52.
  - A *perfect* model would still have MAE ≈ 0.234 (EN) and 0.247 (ZH), because the target is a noisy mean of annotators.

## 2. Protocol (`PROTOCOL.md`)

- **Prediction time and input**: predict after the dialogue ends, from the full dialogue text only. OVERALL ratings, turn ratings, actions and explanations are removed.
- **Selection**
  - TRAIN fits the models.
  - VAL selects epoch, hyper-parameters and best seed.
  - TEST is scored once per run.
  - Fine-tuned models use 3 seeds and are reported as mean ± std.
- **Metrics**
  - MAE, RMSE, QWK, Spearman, exact accuracy, within-1 accuracy, 3-class macro-F1, per-class scores, confusion matrices, signed error per class.
  - On the English labels QWK is about 0 for every model, because nearly all labels and predictions round to 3. Read Spearman and MAE vs the floor instead.
- **CPU budget for the fine-tuned models**
  - The first try (256 tokens, full TRAIN, 5 epochs) needed more than 23 minutes without finishing one e5-small epoch, so it was stopped.
  - The CPU runs therefore use **50% of TRAIN (stratified), 3 epochs, 128 or 256 tokens** (left-truncated, so the end of the dialogue is kept).
  - The classic models use the full TRAIN.
  - For a fair comparison, `tfidf_ridge_frac0.5` is TF-IDF on the same 50% of TRAIN.

## 3. USS leaderboard

Source: `results/leaderboard_uss.csv` / `.json`. Rows are ranked by VAL MAE within each group. TEST is shown as mean ± std over seeds.

### All (EN + ZH, 1,016 TEST dialogues)

| VAL rank | Model | Params | VAL MAE | TEST MAE | Spearman | QWK | 3-class F1 |
|---|---|---|---|---|---|---|---|
| 1 | TF-IDF+Ridge, last 256 tokens | 0.19M | 0.395 | **0.392** | **0.596** | 0.439 | 0.491 |
| 2 | TF-IDF (word+char) + Ridge | 0.30M | 0.396 | 0.393 | 0.592 | 0.407 | 0.487 |
| 3 | e5-small vocab-trimmed, 12 layers, 128 tokens | 28.1M | 0.397 | 0.405 ± 0.003 | 0.570 | 0.379 | 0.488 |
| 4 | **e5-small vocab-trimmed, 6 layers, 256 tokens** | 17.4M | 0.398 | 0.399 ± 0.006 | 0.589 | 0.375 | 0.483 |
| 5 | e5-small trimmed, 6 layers, 128 tokens | 17.4M | 0.399 | 0.403 ± 0.007 | 0.567 | 0.379 | 0.488 |
| 6 | TF-IDF+Ridge, last 128 tokens (diagnostic) | 0.11M | 0.399 | 0.403 | 0.581 | 0.420 | 0.495 |
| 7 | TF-IDF + logistic regression (expected value) | 1.5M | 0.401 | 0.407 | 0.576 | 0.411 | 0.491 |
| 8 | HistGradientBoosting on 17 dialogue features | 200 trees | 0.401 | 0.404 | 0.572 | 0.421 | 0.487 |
| 9 | TF-IDF+Ridge on the same 50% TRAIN as the transformers | 0.17M | 0.403 | 0.401 | 0.570 | 0.398 | 0.486 |
| 10 | mMiniLMv2-L6 vocab-trimmed, 128 tokens | 17.4M | 0.408 | 0.420 ± 0.006 | 0.518 | 0.371 | 0.486 |
| floor | per-corpus TRAIN mean | 5 | 0.414 | 0.423 | 0.497 | 0.379 | 0.491 |
| floor | global TRAIN mean | 1 | 0.500 | 0.510 | — | 0 | 0.214 |

### EN (SGD+MWOZ+ReDial+CCPE, 525 TEST dialogues)

| VAL rank | Model | Params | VAL MAE | TEST MAE | Spearman |
|---|---|---|---|---|---|
| 1 | TinyBERT-4L, trained on EN only, 128 tokens | 14.4M | 0.305 | 0.305 ± 0.001 | 0.370 |
| 2 | e5-small trim L6, 128 tokens | 17.4M | 0.306 | 0.298 ± 0.002 | 0.391 |
| 3 | TF-IDF+Ridge, last 256 tokens | 0.19M | 0.307 | 0.301 | 0.383 |
| 4 | TF-IDF+Ridge | 0.30M | 0.307 | 0.300 | 0.378 |
| 5 | TF-IDF+Ridge, trained on EN only | 0.10M | 0.307 | 0.302 | 0.365 |
| 7 | **e5-small trim L6, 256 tokens** | 17.4M | 0.309 | **0.296 ± 0.001** | **0.408** |
| 9 | e5-small trim L12, 128 tokens | 28.1M | 0.311 | 0.311 ± 0.004 | 0.341 |
| 10 | mMiniLMv2-L6 trim, 128 tokens | 17.4M | 0.313 | 0.312 ± 0.011 | 0.363 |
| floor | per-corpus mean | 5 | 0.323 | 0.318 | 0.186 |

**Reading the EN table**
- Every EN model lies between 0.296 and 0.312.
- VAL differences between ranks 1 and 9 are at most 0.006, which is within seed noise.
- The noise limit is 0.234 and the floor is 0.318.

### ZH (JDDC, real e-commerce customer service, 491 TEST dialogues)

| VAL rank | Model | VAL MAE | TEST MAE | Spearman | QWK |
|---|---|---|---|---|---|
| 1 | e5-small trim L12, 128 tokens | 0.489 | 0.505 ± 0.003 | 0.343 | 0.029 |
| 2 | TF-IDF+Ridge, last 256 tokens | 0.490 | **0.489** | **0.407** | 0.252 |
| 3 | TF-IDF+Ridge | 0.490 | 0.493 | 0.392 | 0.150 |
| 5 | e5-small trim L6, 256 tokens | 0.494 | 0.509 ± 0.012 | 0.378 | 0.060 |
| 8 | HGB dialogue features | 0.497 | 0.506 | 0.352 | 0.209 |
| 9 | e5-small trim L6, 128 tokens | 0.498 | 0.515 ± 0.011 | 0.294 | 0.048 |
| 10 | mMiniLMv2-L6 trim, 128 tokens | 0.510 | 0.535 ± 0.000 | 0.093 | 0 (**collapsed to a constant**) |
| floor | per-corpus mean | 0.510 | 0.535 | — | 0 |

**Reading the ZH table**
- **VAL and TEST disagree for the 12-layer model**: it is best on VAL (0.489) but only 0.505 on TEST.
- This shows that VAL differences below about 0.01 are not meaningful at this data size.
- The fine-tuned transformers are weak in QWK on ZH (≤ 0.06 vs 0.25 for TF-IDF). Their predictions are too compressed to cross the rounding thresholds.

## 4. Cost

Sources:
- Latency, load time and RAM: `results/latency_cpu.json`. Each model was measured in its own process at 21:57Z, CPU load average 1.2–1.4.
- Accuracy: `results/quant_*.json`, `results/uss/*.json`.

| Model | Params | Disk fp32 | Disk int8 | CPU p50 / p95 batch 1, 2 threads | Load time | Peak RSS (inference process) | TEST MAE (best seed) fp32 → int8 → int8 + VAL offset | Train time / seed | Peak RSS (train) |
|---|---|---|---|---|---|---|---|---|---|
| **e5 trim L6, 256 tokens** | 17.4M | 71.8 MB | 39.5 MB | 58 / 79 ms (int8: 41 / 52 ms) | 10.6 s | 0.91 GB | 0.391 → 0.407 → **0.397** | 3,007 s | 4.1 GB |
| e5 trim L6, 128 tokens | 17.4M | 71.8 MB | 39.5 MB | 34 / 46 ms (int8: 26 / 31 ms) | 10.8 s | 0.91 GB | 0.397 → 0.417 → 0.404 | 907 s | 3.0 GB |
| e5 trim L12, 128 tokens | 28.1M | 114.4 MB | — | 62 / 82 ms | 10.7 s | 0.99 GB | (mean 0.405) | 2,871 s | 3.9 GB |
| mMiniLMv2-L6 trim, 128 tokens | 17.4M | 71.8 MB | — | 34 / 42 ms | 9.8 s | 0.91 GB | (mean 0.420) | 854 s | 2.3 GB |
| TinyBERT-4L EN, 128 tokens | 14.4M | 57.5 MB | — | 17 / 20 ms | 5.6 s | 0.52 GB | (EN mean 0.305) | 588 s | 1.3 GB |
| TF-IDF+Ridge | 0.30M | not measured | — | 6.5 / 10.2 ms (inside the benchmark, shared CPU) | — | — | 0.393 | 44 s (fit) | 0.7 GB |

**Notes on the cost table**
- **Training times**: CPU, 50% of TRAIN, 3 epochs, the CPU shared with another worker. They are upper bounds.
- **Peak RSS**: includes the PyTorch and transformers runtime (about 0.5 GB on its own).
- **What int8 does**
  - Method: dynamic int8 quantization of every `nn.Linear` layer (embeddings stay fp32).
  - It shrinks the model by 45% and cuts latency by 24–29% (`latency_cpu.json`).
  - **Systematic shift**: on USS it moves every prediction up by about 0.1. The mean absolute difference from fp32 is 0.111 (L6/256).
  - **Fix**: one offset fitted on VAL (+0.08) recovers most of the loss: +0.005 MAE instead of +0.016 compared with fp32. Spearman is unchanged (0.592 → 0.590).
  - **Amazon**: int8 costs more on the validated Amazon checkpoint: 0.631 → 0.676; with the VAL offset, 0.673. Spearman drops 0.829 → 0.809, so ranking quality is lost there, not only calibration.
- **GPU VRAM and latency: NOT VERIFIED.**

## 5. Auxiliary benchmark: Amazon EN/FR (product stars)

Sources:
- `results/leaderboard_amazon.json`: re-used v2 files, each with its SHA256.
- `results/amazon_rescore_e5small_trim_ft.json`: the validated checkpoint re-scored with the v3 metrics. SHA256 `6bae1f48…` confirmed; MAE 0.6309 reproduced.

| Model | Params | TEST MAE all | EN | FR |
|---|---|---|---|---|
| e5-small trimmed, fine-tuned (validated) | 27.8M | **0.630 ± 0.007** | 0.638 | 0.622 |
| mMiniLM-L12 full | 117.7M | 0.642 ± 0.015 | 0.692 | 0.592 |
| TinyBERT-4L | 14.4M | 0.743 ± 0.004 | 0.709 | 0.778 |
| mMiniLMv2-L6 trimmed | 17.2M | 0.804 ± 0.009 | 0.861 | 0.746 |
| TF-IDF+Ridge | 29k | 0.830 | 0.842 | 0.817 |
| Intake sentiment model, no training | 124.6M | 0.935 | 0.736 | 1.134 |
| mean | 1 | 1.205 | 1.202 | 1.208 |

- **New v3 metrics for the validated checkpoint**: QWK 0.803 (EN 0.798, FR 0.807), Spearman 0.829, exact accuracy 0.474.
- **On product reviews**: fine-tuned multilingual transformers beat TF-IDF by 0.2 MAE, and French works.

## 6. Selection

**Rule, written before looking at TEST**
- Among the models whose VAL MAE (all) is within one seed-std (about 0.006) of the best fine-tuned VAL MAE, take the smallest and fastest.
- VAL only; TEST is shown for information.

**On USS, TF-IDF competes closely and is in fact first on VAL.**
- TF-IDF+Ridge on the last 256 tokens has VAL 0.395 and TEST 0.392, with the best Spearman (0.596).
- It has 0.19M parameters and runs in milliseconds.
- The CPU-budget fine-tuned models are statistically tied with it on EN and worse on ZH: 0.505–0.515 vs 0.489 TEST.
- The honest reading: on noisy dialogue-level labels, with about 2,400 training dialogues, 3 epochs and CPU only, **fine-tuning does not beat a well-tuned TF-IDF**.

**Selected neural checkpoint: `e5small_trim_ft_L6_frac0.5_len256`, seed 1 (best seed by VAL).**
- Path (outside git, not durable): `/tmp/claude-0/-home-user/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/f_v3/ckpt/e5small_trim_ft_L6_frac0.5_len256_s1/`
  - `model.pt`: fp32
  - `model_int8.pt`: dynamic int8
  - `meta.json`
- SHA256 values: `checkpoints_manifest.json`.
- Load it with `f_predictor.SatisfactionPredictor.load(<path>)` (add `int8=True` for the int8 copy).

**Why this checkpoint**
- **It ties the best fine-tuned model on VAL**: 0.398 vs 0.397 for the 12-layer model, a 0.001 difference against a seed std of 0.003–0.007.
- **It is much cheaper than the 12-layer model**: 17.4M vs 28.1M parameters, 71.8 vs 114.4 MB, 58 vs 62 ms (41 ms int8).
- **It is lighter than the v2 Agent F** (27.8M).
- **It is multilingual** (trained on EN+ZH). TF-IDF cannot transfer to unseen vocabulary or languages, and on Amazon EN/FR the e5-trimmed family beats TF-IDF by 0.2 MAE.
- **Longer context helps**: 256 tokens beats 128 tokens, consistent with the truncation diagnostic.

**Why not the other candidates**
- **mMiniLMv2-L6** (same size): it collapsed to a constant on ZH.
- **TinyBERT**: English vocabulary only.
- **12-layer e5**: no measurable gain for 1.6× the parameters.

**Practical recommendation**
- Use **TF-IDF+Ridge (last 256 tokens) as the default Agent F scorer on USS-like text** (cheapest, best measured).
- Keep the selected e5-L6/256 checkpoint as the multilingual neural model, and re-train it on the RTX 4050 with the full protocol: 256–512 tokens, full TRAIN, 5 epochs.
- The headroom is on ZH (0.49 vs a noise limit of 0.25). On EN (0.296 vs 0.234) little is left.
- **This is a decision for the Brain.**

**Limits that apply to any choice**
- Strong regression to the mean: unsatisfied dialogues are over-predicted by about 1.2.
- Polite-but-unsatisfied dialogues are a blind spot: MAE 0.60 vs 0.29.
- Predictions are almost flat on ShopNova-style text (`ERROR_ANALYSIS.md` §8).
- Agent F's score should therefore be used as a **weak signal**, not an alarm, until it is validated on labelled ShopNova or DCH-2 dialogues.

## 7. NOT VERIFIED / BLOCKED

- **Not verified**
  - GPU VRAM, GPU latency, fp16 training: no GPU in this sandbox.
  - Full-protocol fine-tuning (full TRAIN, 5 epochs, 256+ tokens): CPU budget.
  - mMiniLM-L12 trimmed on USS: dropped for CPU budget. In v2 it was ≈ e5 on Amazon.
  - e5 L12 at 256 tokens: not run (CPU budget).
  - French dialogues: no labelled French support dialogue data; FR is validated only on product reviews.
  - Rows of the HF parquet mirror of USS: not parsed. The original GitHub TXT files were used instead.
- **Blocked**
  - Local CallVerse datasets: no access.
  - DCH-2: needs a signed agreement.
  - Kaggle datasets: need a login.

## 8. Files

- **Documents**: `DATASETS.md`, `data_provenance.json`, `PROTOCOL.md`, `ERROR_ANALYSIS.md`, `RUN_AND_RESUME_F.md`, `STATUS.json`, `checkpoints_manifest.json`
- **Results**: `results/leaderboard_uss.{json,csv}`, `results/leaderboard_amazon.json`, `results/uss/*.json`, `results/quant_*.json`, `results/amazon_rescore_e5small_trim_ft.json`, `results/error_analysis.json`, `results/noise_floor.json`, `results/uss_stats.json`
- **Figures** (`figures/`): `uss_leaderboard_mae_spearman.png`, `uss_params_latency_vs_mae.png`, `uss_confusion_best.png`, `amazon_language_breakdown.png`, `quantization_tradeoff.png`
- **Code**: `uss_data.py`, `bench_uss.py`, `run_queue.sh`, `run_queue2.sh`, `prune_ckpt.py`, `f_predictor.py`, `quantize_f.py`, `latency_bench.py`, `amazon_rescore.py`, `amazon_leaderboard.py`, `error_analysis.py`, `noise_floor.py`, `make_leaderboard.py`, `make_figures.py`, `make_manifest.py`, `make_provenance.py`, `infer_example.py`

## 8. M7 responsibilities beyond the score

Details: `10_AGENT_F_M7_SCOPE.md`.

**Quality review of closed conversations**
- Deterministic checks, about 1 ms per conversation.
- Held-out corpus: 120 conversations through the real prototype pipeline, with scripted agents.
- 16/16 planted defects that occurred were caught, with 0 false flags on 91 clean conversations.
- This checks wiring, not real-world prevalence.

**Outdated rules and knowledge, with verifiable evidence**
- No text/condition mismatches.
- No stale rule ids in code or config.
- A knowledge gap: a delivered, late order after the 14-day return window is covered by no rule.
- All 8 rules are AI-written and unreviewed.
- On the corpus, the planted missing rule id R-REF-02 was flagged.

**Owner report**: `v3/m7/results/test/owner_report.md` and `.json`.

**Feedback to Agent E**
- Gated. With the selected e5-L6/256 model, the gate passes test size, Spearman CI [0.545, 0.635], the baseline check and coverage.
- It **fails on label type and domain** (annotator labels, not ShopNova customer ratings).
- Result: the score is KPI only and never part of E's reward. It is also flat on ShopNova text (SD 0.04).
