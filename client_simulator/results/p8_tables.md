## Final comparison (writer on the same 30 role cards; scorer on the same 1,000 real Flipkart CSAT test rows)

| Setup | GPU memory alone | GPU memory with qwen2.5:3b | Seconds per turn | Realism distance (lower = better) | Realism (0-6) | Stays in role (0-6) | Score MAE [95% CI] | Score QWK [95% CI] | Distance to real score distribution |
|---|---|---|---|---|---|---|---|---|---|
| **Before:** phi4-mini:3.8b writer + phi4-mini LLM scoring (main calibration) | 2510 MiB | 4534 MiB | 0.71 s | 0.177 (no examples) / 0.204 (5 examples) | 5 | 5 | 0.92 [0.84, 1.00] | 0.31 [0.24, 0.38] | 0.33 |
| **After:** gemma3:1b writer + MiniLM int8 CPU scorer (quantile setting) | 828 MiB (+0 GPU for the scorer) | 2854 MiB | 0.47 s + 9.88 ms per score (CPU) | 0.150 | 6 | 5 | 0.80 [0.72, 0.87] | 0.40 [0.33, 0.47] | 0.06 |

Seconds per turn and memory: same prompt, Ollama with KV q8_0 + flash attention, num_ctx 1024, requests to 127.0.0.1 (with 'localhost' Windows adds about 2 s per request; all earlier phases include that overhead). Memory with qwen2.5:3b = nvidia-smi increase with both models loaded.

## Writer candidates (Test 2: 30 role cards x 3 turns; Test 1 judged blind by Claude Code)

| Writer | Licence | Prompt | Realism distance | Breaks role | Empty replies | Realism (0-6) | Role (0-6) | VRAM alone | s/message (default server) |
|---|---|---|---|---|---|---|---|---|---|
| gemma3:1b | Gemma Terms of Use | rp1-ex5 | 0.150 | 0.0% | 8.9% | 6 | 5 | 841 MiB | 2.58 |
| granite4:350m | Apache 2.0 | rp1-ex5 | 0.153 | 33.3% | 0.0% | 2 | 2 | 804 MiB | 2.34 |
| callverse-sim-writer | Gemma Terms of Use (fine-tune of gemma-3-1b-it) | rp1-ft | 0.171 | 0.0% | 0.0% | 4 | 4 | n/a MiB | n/a |
| phi4-mini:3.8b | MIT | rp1-noex | 0.177 | 0.0% | 0.0% | 5 | 5 | n/a MiB | n/a |
| llama3.2:1b | Llama 3.2 Community | rp1-ex5 | 0.196 | 1.1% | 0.0% | 6 | 6 | 1448 MiB | 2.45 |
| gemma3:270m | Gemma Terms of Use | rp1-ex5 | 0.198 | 8.9% | 1.1% | 0 | 0 | 309 MiB | 2.52 |
| phi4-mini:3.8b | MIT | rp1-ex5 | 0.204 | 0.0% | 0.0% | n/a | n/a | n/a MiB | n/a |
| smollm2:1.7b | Apache 2.0 | rp1-ex5 | 0.225 | 5.6% | 0.0% | 1 | 3 | 2570 MiB | 2.61 |

## Scorers on held-out REAL test sets (95% bootstrap CI)

| Test set (n, who scored) | Scorer | MAE | QWK | +-1 acc | Distance to real distribution |
|---|---|---|---|---|---|
| Flipkart CSAT (customer) (n=1000) | phi4-mini LLM (before) | 0.92 [0.84, 1.00] | 0.31 [0.24, 0.38] | 0.76 | 0.33 |
| Flipkart CSAT (customer) (n=1000) | classic CPU (TF-IDF / GBM) | 0.82 [0.77, 0.88] | 0.39 [0.32, 0.45] | 0.86 | 0.60 |
| Flipkart CSAT (customer) (n=1000) | MiniLM fine-tuned, int8, isotonic (plain option) | 0.79 [0.72, 0.85] | 0.43 [0.36, 0.49] | 0.87 | 0.55 |
| Flipkart CSAT (customer) (n=1000) | MiniLM fine-tuned, int8, quantile (**default**) | 0.80 [0.72, 0.87] | 0.40 [0.33, 0.47] | 0.80 | 0.06 |
| Olist (customer, PT) (n=500) | phi4-mini LLM (before) | 1.13 [1.01, 1.26] | 0.09 [0.00, 0.20] | 0.69 | 0.40 |
| Olist (customer, PT) (n=500) | classic CPU (TF-IDF / GBM) | 0.54 [0.46, 0.61] | 0.70 [0.63, 0.76] | 0.89 | 0.27 |
| Olist (customer, PT) (n=500) | MiniLM fine-tuned, int8, isotonic (plain option) | 0.54 [0.47, 0.62] | 0.70 [0.61, 0.76] | 0.89 | 0.25 |
| Olist (customer, PT) (n=500) | MiniLM fine-tuned, int8, quantile (**default**) | 0.65 [0.57, 0.73] | 0.68 [0.59, 0.74] | 0.88 | 0.14 |
| TripAdvisor (customer) (n=500) | classic CPU (TF-IDF / GBM) | 0.37 [0.32, 0.41] | 0.87 [0.84, 0.89] | 0.98 | 0.06 |
| TripAdvisor (customer) (n=500) | MiniLM fine-tuned, int8, isotonic (plain option) | 0.35 [0.31, 0.40] | 0.88 [0.85, 0.90] | 0.98 | 0.03 |
| TripAdvisor (customer) (n=500) | MiniLM fine-tuned, int8, quantile (**default**) | 0.35 [0.31, 0.40] | 0.88 [0.85, 0.90] | 0.98 | 0.03 |
| USS travel dialogues (annotators) (n=186) | phi4-mini LLM (before) | 0.33 [0.26, 0.40] | 0.17 [0.03, 0.30] | 0.99 | 0.05 |
| USS travel dialogues (annotators) (n=186) | classic CPU (TF-IDF / GBM) | 0.26 [0.20, 0.33] | 0.09 [-0.01, 0.20] | 0.99 | 0.22 |
| USS travel dialogues (annotators) (n=186) | MiniLM fine-tuned, int8, isotonic (plain option) | 0.47 [0.39, 0.55] | 0.01 [-0.14, 0.17] | 0.98 | 0.08 |
| USS travel dialogues (annotators) (n=186) | MiniLM fine-tuned, int8, quantile (**default**) | 0.47 [0.39, 0.55] | 0.01 [-0.14, 0.17] | 0.98 | 0.08 |

Classic CPU choice per source (dev): csat: tfidf_lr | per-source | isotonic; olist: tfidf_lr | per-source | none; tripadvisor: tfidf_lr | per-source | isotonic; uss: gbm_feats_svd | all sources | none
MiniLM: 32.4 MB int8 (127.5 MB fp32), 9.88 ms per score on CPU; classic: TF-IDF+LR 0.94 ms, GBM 46.94 ms per score.

**Mean score per waiting time bucket, Flipkart CSAT (customer) test (real vs scorer, 95% CI)**

| Bucket | n | real | phi4-mini (before) | MiniLM quantile (after) |
|---|---|---|---|---|
| 0-5 min | 444 | 4.35 [4.23, 4.47] | 4.74 [4.66, 4.82] | 4.78 [4.69, 4.86] |
| 5-30 min | 247 | 4.27 [4.10, 4.42] | 4.67 [4.54, 4.79] | 4.53 [4.39, 4.66] |
| 30 min-2 h | 103 | 4.11 [3.82, 4.38] | 2.92 [2.65, 3.19] | 3.90 [3.66, 4.10] |
| 2-8 h | 82 | 4.09 [3.76, 4.39] | 4.38 [4.09, 4.63] | 3.05 [2.76, 3.34] |
| 8 h+ | 89 | 3.51 [3.12, 3.85] | 1.94 [1.80, 2.11] | 2.28 [2.00, 2.58] |
| size-weighted gap | | | 0.58 [0.49, 0.68] | 0.49 [0.41, 0.58] |

**Mean score per delivery lateness bucket, Olist (customer, PT) test (real vs scorer, 95% CI)**

| Bucket | n | real | phi4-mini (before) | MiniLM quantile (after) |
|---|---|---|---|---|
| on time or early | 448 | 4.34 [4.24, 4.45] | 4.38 [4.27, 4.50] | 4.28 [4.19, 4.38] |
| 1-3 days late | 9 | 3.44 [2.44, 4.33] | 5.00 [5.00, 5.00] | 2.77 [2.09, 3.44] |
| 4-7 days late | 11 | 2.91 [1.91, 3.91] | 5.00 [5.00, 5.00] | 1.27 [1.00, 1.55] |
| 8+ days late | 17 | 2.24 [1.53, 3.06] | 3.94 [3.24, 4.65] | 1.24 [1.00, 1.71] |
| never delivered | 15 | 1.40 [1.00, 2.07] | 2.00 [2.00, 2.00] | 1.12 [1.00, 1.37] |
| size-weighted gap | | | 0.19 [0.12, 0.34] | 0.14 [0.07, 0.24] |
