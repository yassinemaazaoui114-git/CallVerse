# S2 - Local LLM for the Client Simulator (M1), tested against real data

**Judging note.** Realism and stays-in-role scores (0-6) were judged by Claude Code (Test 1 blind: anonymous codes, shuffled order) and were **not hand-verified** by a person. The outputs are in JUDGE_SPOTCHECK.md and JUDGE_SPOTCHECK_FINAL.md for review.

Owner: Client Simulator. Hardware: RTX 3060 Laptop, 6 GB. All models run in Ollama 0.40.11, Q4_K_M quantization.
S1_FAMILY (the agents' model family) is still unknown, so the top pick and runner-up come from different families.
Scripts: `scripts/p3_*.py`; results: `results/p3_*.json|csv`; LLM cache: `data/cache/` (git-ignored).

## Candidates and how they were run

7 models from 6 families: llama3.2:3b (Llama), phi4-mini:3.8b (Phi), gemma3:4b (Gemma), granite4:3b (Granite),
mistral:7b (Mistral), qwen3.5:4b (Qwen), and **Microsoft UserLM-8b**, a model trained to simulate users (GGUF
Q4_K_M from bartowski; it is fine-tuned from Llama-3.1-8B, so it is Llama family). Gemma 4 (e2b/e4b) was skipped:
7.5 / 9.5 GB in the Ollama library, over the 6 GB limit.

- **Speed and memory** (`p3_speed_memory.py`): 5 role-play messages + 2 scoring calls per model, VRAM from
  `ollama ps` and `nvidia-smi`, then qwen2.5:3b and the candidate loaded together (num_ctx 4096): "fits" means both
  stay 100% in VRAM.
- **Sample sizes** (chosen after the speed test so that everything fits in MAX_LLM_HOURS = 4): Test 1: 3 cards x 2
  turns. Test 2: 30 cards x 3 turns x 2 conditions = 180 messages per model. Test 3: CONV calibration 60 (train) /
  dev 60 / test 120; CSAT calibration 100 (train) / dev 100 / test 200; v1 run on dev only (plus test when dev
  chose it). Fixed seed 42. 4 requests in parallel (3.2x throughput, measured). **Total LLM time: about 2.9 h**
  (`logs/llm_runs.log`: 10,105 s logged + about 6 min of first probes), including one CSAT run discarded because of
  a bug (see SCORE_CALIBRATION.md).

## Table 1 - the team's table

Realism and stays-in-role are from Test 1, **judged by Claude Code**, blind (anonymous codes, shuffled), with
automatic checks shown next to each output; reasoning per output in `results/p3_test1_judgement.json`, 10 of them in
`JUDGE_SPOTCHECK.md` for a human re-check. Seconds per message: mean wall time of 5 role-play messages
(up to 120 tokens) with nothing else running.

| Model | Family | Size | Quantization | GPU memory | Realism (0-6) | Stays in role (0-6) | Seconds per message | Licence | Link |
|---|---|---|---|---|---|---|---|---|---|
| llama3.2:3b | Llama (Meta) | 3.2B | Q4_K_M | 2442 MiB alone; with qwen2.5:3b: fits (4529 MiB used) | 5 | 4 | 2.85 | Llama 3.2 Community License | https://ollama.com/library/llama3.2 |
| phi4-mini:3.8b | Phi (Microsoft) | 3.8B | Q4_K_M | 2957 MiB alone; with qwen2.5:3b: fits (5043 MiB used) | 5 | 5 | 3.18 | MIT | https://ollama.com/library/phi4-mini |
| gemma3:4b | Gemma (Google) | 3.9B | Q4_K_M | 2772 MiB alone; with qwen2.5:3b: fits (5751 MiB used) | 6 | 5 | 3.01 | Gemma Terms of Use | https://ollama.com/library/gemma3 |
| granite4:3b | Granite (IBM) | 3.4B | Q4_K_M | 2391 MiB alone; with qwen2.5:3b: fits (4477 MiB used) | 5 | 4 | 3.25 | Apache 2.0 | https://ollama.com/library/granite4 |
| mistral:7b | Mistral | 7.2B | Q4_K_M | 4148 MiB alone; with qwen2.5:3b: does NOT fit (5225 MiB used) | 3 | 5 | 3.68 | Apache 2.0 | https://ollama.com/library/mistral |
| qwen3.5:4b | Qwen (Alibaba) | 4.2B | Q4_K_M | 3000 MiB alone; with qwen2.5:3b: fits (5733 MiB used) | 6 | 5 | 3.06 | Apache 2.0 | https://ollama.com/library/qwen3.5 |
| userlm-8b | Llama (Microsoft UserLM, fine-tuned from Llama-3.1-8B) | 8.03B | unknown | 4187 MiB alone; with qwen2.5:3b: does NOT fit (5278 MiB used) | 2 | 3 | 5.01 | MIT (model card); Llama 3.1 base terms: to verify | https://huggingface.co/microsoft/UserLM-8b (GGUF: bartowski/microsoft_UserLM-8b-GGUF) |

## Table 2 - against real data

- Realism distance (Test 2): mean of the first-message and later-turn distances between the model's realism
  profile (same metrics as D5) and the real Twitter profile; each component is a share gap in [0, 1]; 0 = identical.
- Test 3 numbers are on the **test** samples with the version chosen on **dev** (highest dev QWK). CSAT = real
  customer CSAT (Flipkart), CONV = annotator ratings of real travel dialogues (USS).
- Invalid JSON, strict: the whole answer is not a JSON object (most failures are markdown fences around valid JSON,
  so the score is still recoverable: see "unparseable"). The kit uses Ollama structured output, which gave 100%
  valid JSON in the Phase 4 check.

| Model | Realism distance, no examples | Realism distance, 5 real examples | CSAT version | CSAT MAE | CSAT Spearman | CSAT QWK | CONV version | CONV MAE | CONV Spearman | CONV QWK | invalid-JSON rate, strict (v2) | score unparseable (v2) | breaks-role rate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| llama3.2:3b | 0.218 | 0.214 | v2 | 0.99 | 0.28 | 0.30 | v3-quantile | 0.31 | 0.10 | 0.07 | 0.000 | 0.000 | 0.000 |
| phi4-mini:3.8b | 0.177 | 0.204 | v3-quantile | 0.93 | 0.24 | 0.27 | v3-quantile | 0.36 | 0.17 | 0.17 | 0.000 | 0.000 | 0.000 |
| gemma3:4b | 0.248 | 0.240 | v2 | 1.11 | 0.27 | 0.26 | v2 | 1.19 | 0.32 | 0.15 | 0.671 | 0.000 | 0.000 |
| granite4:3b | 0.187 | 0.134 | v2 | 1.11 | 0.24 | 0.30 | v3-quantile | 0.38 | 0.12 | 0.13 | 0.001 | 0.000 | 0.006 |
| mistral:7b | 0.284 | 0.272 | v3-median | 0.64 | 0.31 | 0.35 | v2 | 0.71 | 0.22 | 0.19 | 0.000 | 0.000 | 0.008 |
| qwen3.5:4b | 0.164 | 0.155 | v3-quantile | 0.80 | 0.30 | 0.33 | v3-quantile | 0.40 | 0.18 | 0.18 | 0.000 | 0.000 | 0.000 |
| userlm-8b | 0.309 | 0.289 | v3-median | 0.63 | 0.29 | 0.28 | v1 | 0.56 | 0.15 | 0.08 | 0.104 | 0.102 | 0.064 |

Baselines on the same test samples:

| Set | Baseline | n | MAE | Spearman | QWK | exact | +-1 | macro-F1 | Wasserstein |
|---|---|---|---|---|---|---|---|---|---|
| CSAT | majority | 200 | 0.68 | n/a | 0.00 | 0.70 | 0.85 | 0.16 | 0.68 |
| CSAT | tfidf_lr | 200 | 0.55 | 0.36 | 0.42 | 0.73 | 0.89 | 0.27 | 0.44 |
| CONV | majority | 120 | 0.30 | n/a | 0.00 | 0.71 | 0.99 | 0.17 | 0.30 |
| CONV | tfidf_lr | 120 | 0.36 | -0.00 | 0.01 | 0.65 | 0.99 | 0.18 | 0.19 |

**Uncertainty (paired bootstrap, 2,000 resamples of the same test items, `results/p3_bootstrap.json`):** no model is
significantly better than another on score match. Test QWK 95% intervals: qwen3.5:4b CSAT 0.16-0.49, CONV 0.02-0.33;
mistral:7b CSAT 0.16-0.52, CONV 0.02-0.34; phi4-mini CSAT 0.11-0.43, CONV 0.01-0.32. Mistral beats qwen3.5 in only
61% (CSAT) and 55% (CONV) of resamples.

**Strict invalid-JSON rate of the plain prompt (v1, dev):** phi4-mini 95% (CONV) / 45% (CSAT), gemma3 98% / 100%;
all others 0%. The v2 prompt (few-shot) fixes phi4-mini but not gemma3's fences.

## Pick

**Top pick: `qwen3.5:4b` (Qwen, Apache 2.0). Runner-up: `phi4-mini:3.8b` (Phi, MIT).** Different families, as required.

Why, in the required order:
1. **Score match to real data.** Mean test QWK over CSAT and CONV: mistral 0.272, **qwen3.5 0.253**, **phi4-mini
   0.222**, granite4 0.213, gemma3 0.204, llama3.2 0.184, userlm 0.182. CSAT MAE: userlm 0.63, mistral 0.64,
   **qwen3.5 0.80**, phi4-mini 0.93, llama 0.99, gemma/granite 1.11 (majority baseline 0.68). Mistral is nominally
   first but statistically tied with qwen3.5 (above), and it **does not fit next to qwen2.5:3b** on a 6 GB GPU
   (not even fully on GPU alone: 4,148 of 4,512 MiB), so the team could not run the simulator next to the agents'
   writer model. UserLM-8b has the same problem (5,278 MiB used together, not all on GPU).
2. **Realism.** qwen3.5 has the second-lowest distance to real messages (0.164 without examples, 0.155 with 5 real
   examples); only granite4 is lower with examples (0.134). Mistral (0.284 / 0.272) and UserLM (0.309 / 0.289) are
   the least realistic; UserLM also broke role in 16% / 10% of Test 2 messages (assistant phrases).
3. **Staying in role.** Test 1: qwen3.5 and gemma3 6/6 realism, 5/6 role; phi4-mini 5/5; llama and granite 5/4;
   mistral 3/5; UserLM 2/3 (one first message was written in the agent's voice).
4. **Speed.** All 3-4B models take 2.9-3.3 s per message (qwen3.5 3.06 s, phi4-mini 3.18 s); mistral 3.68 s, UserLM 5.01 s.
5. **Memory.** qwen3.5 3,000 MiB alone, 5,733 MiB next to qwen2.5:3b (fits 6 GB); phi4-mini 2,957 / 5,043 MiB.
   For the 4 GB teammate (not tested on a 4 GB card): the 3-4B models used 2,402-3,676 MiB alone by nvidia-smi,
   so they should fit alone; every pair with qwen2.5:3b used 4,477 MiB or more, so none fits next to it in 4 GB.
6. **Licence.** qwen3.5 Apache 2.0, phi4-mini MIT: both allow academic use (confirmed on the Ollama library pages).

**Why phi4-mini as runner-up and not granite4:** it is ahead on score match (mean QWK 0.222 vs 0.213, CSAT MAE 0.93
vs 1.11) and Test 1 (5/5 vs 5/4); granite4 is the better choice if realism matters most (0.134 with examples) or
for the 4 GB GPU (2,391 MiB, the smallest).

**Main risk: family overlap with the agents.** CallVerse already uses qwen2.5:3b (Qwen) to write the agents' replies.
If S1 turns out to be Qwen, or the team counts the reply writer as "the agents' model", switch to **phi4-mini** by
changing one line in `simulator/config.yaml` (its calibration map is already in `calibration.json`). Second risk:
the score match itself is modest (test QWK about 0.3 on CSAT, about 0.2 on CONV) - below a supervised TF-IDF model on
the same CSAT rows (QWK 0.42), and no model beats "always 3" on CONV MAE. See SCORE_CALIBRATION.md.

## TASK3: lean simulator (small writer + CPU scorer), 2026-10-25

S1 uses Qwen, so no Qwen model is used for the simulator. New architecture: a small LLM **writer** plays the customer, and a
small **CPU scorer** gives the 1-5 score. Every evaluation is on held-out REAL data. Details: FINETUNING.md, DATA_SOURCES.md,
`results/p8_tables.md`.

**Final setup: `gemma3:1b` writer + fine-tuned MiniLM scorer with the quantile setting (CPU).** The writer needs 828 MiB (0.83 GB) of GPU memory; together with the agents' qwen2.5:3b both used 2,854 MiB on our 6 GB card, so the pair should fit a 4 GB laptop GPU (not tested on a 4 GB card). The scorer needs no GPU (about 10 ms per score).

**Chosen writer: `gemma3:1b`** (Gemma Terms of Use), prompted with the full role card + 5 real example messages.
**Chosen scorer: fine-tuned MiniLM (all-MiniLM-L12-v2), ONNX int8, CPU** (32 MB, about 10 ms per score), quantile setting by default.
Runner-up writer: `llama3.2:1b` (best Test 1: 6/6, but realism distance 0.196 vs 0.150 and 1,448 vs 841 MiB).
The fine-tuned writer (gemma-3-1b LoRA) was less realistic than the prompted base model, and could not be
exported to Ollama (BLOCKERS.md B13).

### Final comparison (writer on the same 30 role cards; scorer on the same 1,000 real Flipkart CSAT test rows)

| Setup | GPU memory alone | GPU memory with qwen2.5:3b | Seconds per turn | Realism distance (lower = better) | Realism (0-6) | Stays in role (0-6) | Score MAE [95% CI] | Score QWK [95% CI] | Distance to real score distribution |
|---|---|---|---|---|---|---|---|---|---|
| **Before:** phi4-mini:3.8b writer + phi4-mini LLM scoring (main calibration) | 2510 MiB | 4534 MiB | 0.71 s | 0.177 (no examples) / 0.204 (5 examples) | 5 | 5 | 0.92 [0.84, 1.00] | 0.31 [0.24, 0.38] | 0.33 |
| **After:** gemma3:1b writer + MiniLM int8 CPU scorer (quantile setting) | 828 MiB (+0 GPU for the scorer) | 2854 MiB | 0.47 s + 9.88 ms per score (CPU) | 0.150 | 6 | 5 | 0.80 [0.72, 0.87] | 0.40 [0.33, 0.47] | 0.06 |

Seconds per turn and memory: same prompt, Ollama with KV q8_0 + flash attention, num_ctx 1024, requests to 127.0.0.1 (with 'localhost' Windows adds about 2 s per request; all earlier phases include that overhead). Memory with qwen2.5:3b = nvidia-smi increase with both models loaded.

### Writer candidates (Test 2: 30 role cards x 3 turns; Test 1 judged blind by Claude Code)

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