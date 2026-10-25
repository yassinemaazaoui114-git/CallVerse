# 05 — Agent F results (v3 draft, 2026-10-25)

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

### All (EN + ZH)

| VAL rank | Model | Params | TEST MAE | Spearman | QWK | 3-class F1 |
|---|---|---|---|---|---|---|
| 1 | TF-IDF+Ridge, last 256 tokens | 0.19M | **0.392** | **0.596** | 0.439 | 0.491 |
| 2 | TF-IDF (word+char) + Ridge | 0.30M | 0.393 | 0.592 | 0.407 | 0.487 |
| 3 | **e5-small vocab-trimmed, 6 layers, 256 tokens** (fine-tuned) | 17.4M | 0.399 ± 0.006 | 0.589 | 0.375 | 0.483 |
| 4 | e5-small trimmed, 6 layers, 128 tokens | 17.4M | 0.403 ± 0.007 | 0.567 | 0.379 | 0.488 |
| 5 | TF-IDF+Ridge, last 128 tokens (diagnostic) | 0.11M | 0.403 | 0.581 | 0.420 | 0.495 |
| 6 | TF-IDF + logistic regression (expected value) | 1.5M | 0.407 | 0.576 | 0.411 | 0.491 |
| 7 | HistGradientBoosting on 17 dialogue features | 200 trees | 0.404 | 0.572 | 0.421 | 0.487 |
| 8 | TF-IDF+Ridge on 50% TRAIN | 0.17M | 0.401 | 0.570 | 0.398 | 0.486 |
| 9 | mMiniLMv2-L6 vocab-trimmed, 128 tokens | 17.4M | 0.420 ± 0.006 | 0.518 | 0.371 | 0.486 |
| — | e5-small trimmed, **12 layers**, 128 tokens | (pending) | see §3.4 | | | |
| floor | per-corpus TRAIN mean | 5 | 0.423 | 0.497 | 0.379 | 0.491 |
| floor | global TRAIN mean | 1 | 0.510 | — | 0 | 0.214 |

### EN (SGD+MWOZ+ReDial+CCPE, 525 TEST dialogues)

| VAL rank | Model | Params | TEST MAE | Spearman |
|---|---|---|---|---|
| 1 | TinyBERT-4L, trained on EN only, 128 tokens | 14.4M | 0.305 ± 0.001 | 0.370 |
| 2 | e5-small trim L6, 128 tokens | 17.4M | 0.298 ± 0.002 | 0.391 |
| 3 | TF-IDF+Ridge, last 256 tokens | 0.19M | 0.301 | 0.383 |
| 4 | TF-IDF+Ridge | 0.30M | 0.300 | 0.378 |
| 5 | TF-IDF+Ridge, trained on EN only | 0.10M | 0.302 | 0.365 |
| 7 | **e5-small trim L6, 256 tokens** | 17.4M | **0.296 ± 0.001** | **0.408** |
| 9 | mMiniLMv2-L6 trim, 128 tokens | 17.4M | 0.312 ± 0.011 | 0.363 |
| floor | per-corpus mean | 5 | 0.318 | 0.186 |

**Reading the EN table**
- Every EN model lies between 0.296 and 0.312.
- VAL MAE differences are at most 0.008, which is within seed noise.
- The noise limit is 0.234 and the floor is 0.318.

### ZH (JDDC, real e-commerce customer service, 491 TEST dialogues)

| VAL rank | Model | TEST MAE | Spearman | QWK |
|---|---|---|---|---|
| 1 | TF-IDF+Ridge, last 256 tokens | **0.489** | **0.407** | 0.252 |
| 2 | TF-IDF+Ridge | 0.493 | 0.392 | 0.150 |
| 4 | e5-small trim L6, 256 tokens | 0.509 ± 0.012 | 0.378 | 0.060 |
| 7 | HGB dialogue features | 0.506 | 0.352 | 0.209 |
| 8 | e5-small trim L6, 128 tokens | 0.515 ± 0.011 | 0.294 | 0.048 |
| 9 | mMiniLMv2-L6 trim, 128 tokens | 0.535 ± 0.000 | 0.093 | 0 (**collapsed to a constant**) |
| floor | per-corpus mean | 0.535 | — | 0 |

### 3.4 Pending

- e5-small trimmed with all **12 layers** (128 tokens) is still training (`logs/e5small_trim_ft_frac0.5_len128.log`).
- It is not in these tables yet. See `STATUS.json`.

## 4. Cost

Sources: `results/quant_*.json`, `results/uss/*.json`, `results/latency_cpu.json` (when present).

| Model | Params | Disk fp32 | Disk int8 | TEST MAE (best seed) fp32 → int8 → int8 + VAL offset | Train time / seed (CPU) | Peak RAM (train) |
|---|---|---|---|---|---|---|
| e5 trim L6, 256 tokens | 17.4M | 71.8 MB | 39.5 MB | 0.391 → 0.407 → **0.397** | 3,007 s | 4.1 GB |
| e5 trim L6, 128 tokens | 17.4M | 71.8 MB | 39.5 MB | 0.397 → 0.417 → 0.404 | 907 s | 3.0 GB |
| TinyBERT-4L EN | 14.4M | 57.5 MB | — | (EN 0.305 mean) | 588 s | 1.3 GB |
| TF-IDF+Ridge | 0.30M | not measured | — | 0.393 | 44 s | 0.7 GB |

**What int8 does**
- **Method**: dynamic int8 quantization of every `nn.Linear` layer (embeddings stay fp32).
- **Size**: the model shrinks by 45%.
- **Systematic shift**: on USS it moves every prediction up by about 0.1. The mean absolute difference from fp32 is 0.111 (L6/256).
- **Fix**: subtracting one offset fitted on VAL (+0.08) recovers most of the loss: +0.005 MAE instead of +0.016 compared with fp32.
- **Amazon**
  - int8 costs more on the validated Amazon checkpoint: 0.631 → 0.676; with the VAL offset, 0.673.
  - Spearman drops 0.829 → 0.809, so ranking quality is lost, not only calibration.

**Latency**
- Latency at batch 1 (2 threads) was measured while 4–6 processes shared 4 cores (load average 4.5–7). The numbers are **upper bounds**.
  - e5 L6/128: 37 ms p50 inside the benchmark.
  - Same checkpoint: 75 ms (fp32) and 58 ms (int8) in `quant_*.json`.
  - L6/256: 220 ms inside the benchmark, but 980 ms under load 6.4.
  - TF-IDF: 6 ms.
- `results/latency_cpu.json` re-measures every checkpoint in its own process at the end of the run.
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

**On USS, TF-IDF competes closely and wins on VAL.**
- TF-IDF+Ridge (last 256 tokens) has the best VAL MAE (0.395), the best TEST MAE (0.392) and the best Spearman.
- It has 0.19M parameters and runs in milliseconds.
- The CPU-budget fine-tuned models are statistically tied with it on EN and worse on ZH (0.509 vs 0.489).
- The honest reading: on dialogue-level satisfaction with noisy labels, about 2,400 training dialogues, 3 epochs and CPU only, **fine-tuning does not yet beat a well-tuned TF-IDF**.

**Selected neural checkpoint**: `e5small_trim_ft_L6_frac0.5_len256`, seed 1.
- Path: `/tmp/claude-0/-home-user/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/f_v3/ckpt/e5small_trim_ft_L6_frac0.5_len256_s1`.
- int8 copy: `model_int8.pt` in the same folder.
- SHA256 values: `checkpoints_manifest.json`.

**Why this checkpoint**
- It is the smallest *reliable* transformer: 17.4M parameters, 71.8 MB fp32, 39.5 MB int8. It is lighter than the v2 Agent F (27.8M).
- It has the best fine-tuned VAL MAE on USS and the best EN TEST (0.296, Spearman 0.408).
- It is multilingual (trained on EN+ZH). TF-IDF cannot transfer to unseen vocabulary or languages; on Amazon EN/FR the e5-trimmed family beats TF-IDF by 0.2 MAE.
- Layer truncation (12 → 6 layers) halves the encoder cost.

**Why not the other candidates**
- **mMiniLMv2-L6**: collapsed on ZH.
- **TinyBERT**: English vocabulary only.

**Practical recommendation**
- Run **TF-IDF+Ridge as the default Agent F scorer on USS-like text** (cheap, best measured).
- Keep e5-L6/256 as the multilingual neural model and re-train it on the RTX 4050 with the full protocol: 256–512 tokens, full TRAIN, 5 epochs. That is where the headroom is (ZH is 0.49 vs a noise limit of 0.25).
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
