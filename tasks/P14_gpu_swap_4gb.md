# P14 — Agent model and SLM on a 4 GB GPU: measure and cut the swap time  ·  Dali's lane

## Why
On Dali's laptop (RTX 3050 Ti, 4 GB) a local agent model and the SLM (qwen2.5:3b) cannot stay loaded together:
Ollama unloads one to load the other, about **12 s per swap** (D4 summary, S1). One ticket has several agent ↔ SLM
switches, so a turn can reach ~45 s (T13 limit: 30 s average). Rough memory: agent GGUF 2.5 GB + KV cache at 8k context
~1.2 GB + SLM 1.9 GB > 4 GB. This task measures options and picks one with a rule fixed in advance.
Needs P10 (the model exists in Ollama). Yassine's PC (6 GB) may not need it: report both if you can.

## Hard limits
- Config and Ollama settings only (`config.yaml`, Ollama env vars / Modelfiles). No change to prompts, agents,
  Coordinator, SLM logic or `tests/data/*`. No new library.
- No Groq / Gemini call. Only `tests/dev/live_dev_messages.json`.
- Changing the SLM model (option C) is a **locked choice from T05b**: measure it, but switch only with Yassine's OK.

## What to do
Measure each option on the same 6 practice messages (2 status, 2 refund, 1 subscription, 1 other: list the ids),
with the agent model `callverse-m2-abcd` forced through the T13 local switch:
- **A. Today (baseline):** default Ollama settings.
- **B. Smaller KV cache:** `OLLAMA_FLASH_ATTENTION=1` + `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_MAX_LOADED_MODELS=2`,
  long `keep_alive`. Do both models now fit on the GPU?
- **C. Smaller SLM:** `qwen2.5:1.5b` (the T05b fallback, ~1 GB) with B's settings.
- **D. SLM on CPU:** SLM Modelfile copy with `PARAMETER num_gpu 0`; agent model alone on the GPU.
For each: `ollama ps` (both models? % GPU), `nvidia-smi` peak, swaps per message (count model loads in the Ollama log
or from `ollama ps` before/after), avg / max s per message, SLM reply check pass rate (`slm_check` in traces).

## Checks (with numbers)
- Table: option × (fits together yes/no, peak VRAM, avg s, max s, swaps per message, SLM check pass x/6, template
  fallbacks x/6).
- **Choice rule (fixed in advance):** the fastest option with avg ≤ 30 s, 0 out-of-memory errors, and SLM check pass
  rate not lower than baseline A. Ties → the option with fewer changes (A < B < D < C).
- Write the chosen settings in `docs/DEMO_RUNBOOK.md` (how to start Ollama with them on Windows) and, if it is config,
  in `config.yaml` with a comment.

## Time box and stop rule
90 minutes. Stop if the machine runs out of memory twice.

## Git (needs approval)
Commit on `feature/m2-finetuned` (or its own branch `feature/gpu-swap` from it). No merge into `main`.
Write `tasks/P14_report.md`, set `tasks/NEXT_PLATFORM.md` to WAITING FOR REVIEW.
