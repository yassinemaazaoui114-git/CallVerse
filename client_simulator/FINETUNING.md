# Fine-tuning (TASK3) - what was trained, on what, and did it help?

Two models were trained on Kaggle (free T4 GPU, private dataset `callverse-memberb-train` with **train + dev rows only**).
Scripts: `kaggle/writer/writer_lora.py`, `kaggle/scorer/scorer_ft.py`; data prep `scripts/p8_data.py`;
evaluation `scripts/p8_*.py`; results `results/p8_*.json`, tables `results/p8_tables.md`. No weights are in git.

## 1. Writer (plays the customer): LoRA on gemma-3-1b-it

- **Base model**: `unsloth/gemma-3-1b-it` (ungated mirror of Google's gemma-3-1b-it; Gemma Terms of Use). Not Qwen (S1 is Qwen).
- **Data**: 5,000 anonymised REAL customer messages: 2,400 first tweets and 1,600 follow-up tweets from Customer
  Support on Twitter, 1,000 tweets from Twitter US Airline Sentiment. Each example = a short role card (company type,
  contact reason mapped to our labels, mood and typo level derived by rules from the message itself) + the
  conversation so far (for follow-ups: the customer's first tweet and the brand's real reply) -> the real customer
  message. Split **by thread**: 10% of threads held out by hash (0 overlap with training).
- **Settings**: LoRA rank 16, alpha 32, dropout 0.05 on all attention and MLP projections; 1 epoch (312 steps,
  batch 16), learning rate 2e-4, max 384 tokens, loss only on the customer message, fp32. 29 min on a T4.
- **Training loss**: 3.96 (step 25) -> 3.86 (step 300) (single-batch values, noisy). Real tweets are hard to predict, so
  the loss barely moved.
- **Export**: merged to fp16. **GGUF Q4_K_M export failed** (Kaggle converter: vocab size check; Ollama 0.40 cannot
  import Gemma 3 safetensors; the local llama.cpp converter was blocked by the permission check). See BLOCKERS.md B13.
  The fine-tuned writer was therefore evaluated with `transformers` on CPU (fp32), not in Ollama. Because it scored
  below gemma3:1b, the GGUF export was **not pursued** (team decision; BLOCKERS.md B13 closed).

**Before / after (same 30 role cards x 3 turns with real brand replies; same 3 Test-1 cards, judged blind by Claude Code)**

| Writer | Prompt | Realism distance to real messages (lower = better) | Test 1 realism (0-6) | Test 1 role (0-6) | Breaks role | Empty replies |
|---|---|---|---|---|---|---|
| gemma3:1b, not fine-tuned (Ollama Q4_K_M) | full role card + 5 real example messages | **0.150** | **6** | **5** | 0% | 8.9% |
| callverse-sim-writer (fine-tuned) | short role card, no examples | 0.171 | 4 | 4 | 0% | 0% |

**Result: prompting a small model with real examples beat LoRA here.** Fine-tuning did not beat simply prompting the base model with 5 real messages. It removed empty replies.
But it learned Twitter habits that do not fit a support chat ("Will send my contact details in the private
message", `<HANDLE>` placeholders) and sometimes ignored the card's facts. The "before" row uses a different prompt
(examples) than the fine-tuned one (short card), because each is the prompt that model is meant to run with.

## 2. Scorer (gives the 1-5 score): all-MiniLM-L12-v2 regression

- **Base model**: `sentence-transformers/all-MiniLM-L12-v2` (33M parameters, Apache 2.0).
- **Data**: REAL train splits of 4 sources, each row = `[source] reason: .. | wait/lateness: .. | turns: .. | text`:
  Flipkart CSAT 40,000 (customer CSAT + remark; licence to verify), Olist 40,000 (customer score + Portuguese comment),
  TripAdvisor 14,343 (customer rating + review), USS 864 x 5 (annotator rating + dialogue). 98,663 rows.
- **Settings**: regression on (score - 3) / 2 with MSE, 2 epochs, batch 64, learning rate 5e-5, max 256 tokens,
  fp16 mixed precision. 16 min on a T4. Exported to ONNX and int8 (dynamic quantization): 32.4 MB.
- **Calibration**: per source, none / isotonic / quantile map fitted on dev half A, chosen on dev half B by QWK.
- **Dev MAE (Kaggle, rounded raw scores)**: CSAT 0.741, Olist 0.527, TripAdvisor 0.37, USS 0.276.

**Before / after on held-out REAL test sets (95% bootstrap CI; full table in `results/p8_tables.md`)**

| Test set (n) | phi4-mini LLM + calibration (before) | classic CPU (TF-IDF/GBM) | **MiniLM fine-tuned int8 (after)** |
|---|---|---|---|
| Flipkart CSAT (1,000), QWK / MAE | 0.31 / 0.92 | 0.39 / 0.82 | **0.43 / 0.79** |
| Olist (500), QWK / MAE | 0.09 / 1.13 (fallback map) | 0.70 / 0.54 | 0.70 / 0.54 |
| TripAdvisor (500), QWK / MAE | not run | 0.87 / 0.37 | **0.88 / 0.35** |
| USS (186, annotators), QWK / MAE | 0.17 / 0.33 | 0.09 / 0.26 | 0.01 / 0.47 |

**Verdict: the fine-tuned scorer is the best on customer scores** (CSAT, TripAdvisor) and as good as the classic
model on Olist. It runs on CPU at about 10 ms per score, with no GPU and no LLM call. It does not work on USS annotator
ratings (no scorer does; USS ratings are almost all 3s).

## Removed in the cleanup (2026-10-25)

The LoRA writer outputs were deleted locally: the merged fp16 weights (1.9 GB, already removed after evaluation) and the
Kaggle log + `train_info.json` (`kaggle_out/writer/`); the numbers above were copied from them. To recreate: push
`kaggle/writer/` again (`kaggle kernels push -p kaggle/writer`, dataset `callverse-memberb-train` rebuilt with
`scripts/p8_data.py` and `kaggle datasets version`), or download the last run with
`kaggle kernels output <kaggle-user>/callverse-writer-lora -p kaggle_out/writer`. The scorer's ONNX int8 file and
tokenizer stay in `models/scorer/` (not in git).
