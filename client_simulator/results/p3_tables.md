## Table 1 (team format)
| Model | Family | Size | Quantization | GPU memory | Realism (0-6) | Stays in role (0-6) | Seconds per message | Licence | Link |
|---|---|---|---|---|---|---|---|---|---|
| llama3.2:3b | Llama (Meta) | 3.2B | Q4_K_M | 2442 MiB alone; with qwen2.5:3b: fits (4529 MiB used) | 5 | 4 | 2.85 | Llama 3.2 Community License | https://ollama.com/library/llama3.2 |
| phi4-mini:3.8b | Phi (Microsoft) | 3.8B | Q4_K_M | 2957 MiB alone; with qwen2.5:3b: fits (5043 MiB used) | 5 | 5 | 3.18 | MIT | https://ollama.com/library/phi4-mini |
| gemma3:4b | Gemma (Google) | 3.9B | Q4_K_M | 2772 MiB alone; with qwen2.5:3b: fits (5751 MiB used) | 6 | 5 | 3.01 | Gemma Terms of Use | https://ollama.com/library/gemma3 |
| granite4:3b | Granite (IBM) | 3.4B | Q4_K_M | 2391 MiB alone; with qwen2.5:3b: fits (4477 MiB used) | 5 | 4 | 3.25 | Apache 2.0 | https://ollama.com/library/granite4 |
| mistral:7b | Mistral | 7.2B | Q4_K_M | 4148 MiB alone; with qwen2.5:3b: does NOT fit (5225 MiB used) | 3 | 5 | 3.68 | Apache 2.0 | https://ollama.com/library/mistral |
| qwen3.5:4b | Qwen (Alibaba) | 4.2B | Q4_K_M | 3000 MiB alone; with qwen2.5:3b: fits (5733 MiB used) | 6 | 5 | 3.06 | Apache 2.0 | https://ollama.com/library/qwen3.5 |
| userlm-8b | Llama (Microsoft UserLM, fine-tuned from Llama-3.1-8B) | 8.03B | unknown | 4187 MiB alone; with qwen2.5:3b: does NOT fit (5278 MiB used) | 2 | 3 | 5.01 | MIT (model card); Llama 3.1 base terms: to verify | https://huggingface.co/microsoft/UserLM-8b (GGUF: bartowski/microsoft_UserLM-8b-GGUF) |

## Table 2 (against real data; Test 3 numbers on the test samples, version chosen on dev)
| Model | Realism distance, no examples | Realism distance, 5 real examples | CSAT version | CSAT MAE | CSAT Spearman | CSAT QWK | CONV version | CONV MAE | CONV Spearman | CONV QWK | invalid-JSON rate, strict (v2) | score unparseable (v2) | breaks-role rate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| llama3.2:3b | 0.218 | 0.214 | v2 | 0.99 | 0.28 | 0.30 | v3-quantile | 0.31 | 0.10 | 0.07 | 0.000 | 0.000 | 0.000 |
| phi4-mini:3.8b | 0.177 | 0.204 | v3-quantile | 0.93 | 0.24 | 0.27 | v3-quantile | 0.36 | 0.17 | 0.17 | 0.000 | 0.000 | 0.000 |
| gemma3:4b | 0.248 | 0.240 | v2 | 1.11 | 0.27 | 0.26 | v2 | 1.19 | 0.32 | 0.15 | 0.671 | 0.000 | 0.000 |
| granite4:3b | 0.187 | 0.134 | v2 | 1.11 | 0.24 | 0.30 | v3-quantile | 0.38 | 0.12 | 0.13 | 0.001 | 0.000 | 0.006 |
| mistral:7b | 0.284 | 0.272 | v3-median | 0.64 | 0.31 | 0.35 | v2 | 0.71 | 0.22 | 0.19 | 0.000 | 0.000 | 0.008 |
| qwen3.5:4b | 0.164 | 0.155 | v3-quantile | 0.80 | 0.30 | 0.33 | v3-quantile | 0.40 | 0.18 | 0.18 | 0.000 | 0.000 | 0.000 |
| userlm-8b | 0.309 | 0.289 | v3-median | 0.63 | 0.29 | 0.28 | v1 | 0.56 | 0.15 | 0.08 | 0.104 | 0.102 | 0.064 |

## Baselines on the same test samples
| Set | Baseline | n | MAE | Spearman | QWK | exact | +-1 | macro-F1 | Wasserstein |
|---|---|---|---|---|---|---|---|---|---|
| CSAT | majority | 200 | 0.68 | n/a | 0.00 | 0.70 | 0.85 | 0.16 | 0.68 |
| CSAT | tfidf_lr | 200 | 0.55 | 0.36 | 0.42 | 0.73 | 0.89 | 0.27 | 0.44 |
| CONV | majority | 120 | 0.30 | n/a | 0.00 | 0.71 | 0.99 | 0.17 | 0.30 |
| CONV | tfidf_lr | 120 | 0.36 | -0.00 | 0.01 | 0.65 | 0.99 | 0.18 | 0.19 |