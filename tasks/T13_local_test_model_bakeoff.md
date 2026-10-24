# T13 — Local test-model bake-off (choose the daily test model for the agents)

## Why
Every end-to-end run on Groq uses the free quota (≈ 200,000 tokens per model per day), so we wait between tests.
We want a **local quantized model** for daily testing of the agents: unlimited, offline and repeatable.
It is a **test stand-in only**, not the final M2 (job brief S1 benchmarks the final choice). Groq gpt-oss-120b stays
for milestone runs. Yassine's PC: RTX 4050, 6 GB VRAM. The SLM (qwen2.5:3b, ~2 GB) shares the GPU.
Candidates (approved by Yassine, 2026-10-24): **qwen3.5:4b** and **phi4-mini**. (qwen3:8b dropped by Yassine.)

## Hard limits
- **No Groq or Gemini call at all** in this task (zero quota). Check the traces at the end: 0 `llm_call` lines with
  provider groq or google.
- The **default** behaviour stays exactly the same: without the new switch, the agents chain is still
  gpt-oss-120b → gpt-oss-20b → gemini-3.5-flash.
- No change to prompts, agents, Coordinator, policies, SLM, Intake or `tests/data/*`.
- **Fix rule (Confirmed 2026-10-24):** if a model makes errors, **describe** them in the report; do not fix them here.
  Fixes come later, in code (checks, defaults, structure), never as prompt tricks for one model.
- Use only the practice set `tests/dev/live_dev_messages.json`. Never run `tests/data/*` (held-out).
- Never read or stage `.env`.

## What to do
1. **Git.** `git fetch`; create `feature/t13-test-model` from `origin/feature/t12-heldout` (it carries the T11/T12
   files). Commit this task file and the current `tasks/NEXT.md` first.
2. **Pull the models.** `ollama pull qwen3.5:4b` and `ollama pull phi4-mini`. If a tag does not exist, use the nearest
   official tag of the same model and size, and say which one you used.
3. **Local settings (important):**
   - **Context ≥ 8,192 tokens.** One agent turn uses ~6,000 tokens; Ollama's default context is smaller and cuts the
     prompt silently. Set it (e.g. a Modelfile with `PARAMETER num_ctx 8192` → models such as `cv-qwen3.5-4b`,
     `cv-phi4-mini`, or the server setting `OLLAMA_CONTEXT_LENGTH`). Say what you used and prove it (e.g. `ollama show`).
   - **Thinking mode off** for qwen3.5 (it adds hidden tokens and time). Use the way Ollama documents for the
     OpenAI-compatible endpoint; check in the trace that answers are not long reasoning texts. Say what worked.
   - temperature 0 + seed 42 for both candidates (repeatable runs).
4. **A switch for the local set (small code change).**
   - In `config.yaml`, add the two candidates as a **separate list** (e.g. `models.agents_local`), not inside the
     normal `models.agents` chain.
   - One env var (e.g. `CALLVERSE_AGENTS_SET=local`) makes every `"agents"` call use that list. The existing
     force variable (or an equivalent) runs **one candidate alone**. Default (no env var) = unchanged.
   - When the local set is on, the quota guard in `scripts/run_live_check.py` / `scripts/quota_check.py` must check
     **only the local models** (no API ping).
   - Note in the report which other parts use the `"agents"` role (e.g. the Intake LLM fallback) and confirm they
     also stay local when the switch is on.
   - Tests: default chain unchanged; switch on → only local models; force picks one model. All offline.
5. **Warm-up + smoke test (per model).** Load the model once (first load can take > 60 s; do not count it).
   Then one refund message (e.g. "Order 4512 is 6 days late, I want my money back.") up to 3 times:
   does the agent call the tools (`get_order`, `get_refunds`, `ask_agent`, `search_policy`, `propose_refund`)?
   A model that never makes a valid tool call in 3 tries is **dropped** (report it) and the other one continues.
6. **Main run (per model, one model at a time).**
   `python -m scripts.run_live_check --file tests/dev/live_dev_messages.json` with the switch on and the model forced.
   While it runs, note `ollama ps` (size, % GPU / % CPU) and `nvidia-smi` (memory used) once or twice.
   Unload the model after its run (`ollama stop <model>`), then do the next one.
7. **Repeatability:** run the **winner** a second time. Report whether the score is the same.

## Checks (with numbers)
- Offline tests x/y (all pass).
- Per model, one table row:
  | Model (tag) | Smoke test (valid tool calls x/3) | Practice set x/24 | Crashes | Leaks | Wrong writes | Avg s / msg | Max s | GPU memory (agent + SLM) | % on CPU | Tool errors (wrong tool, missing step, bad arguments) | Notes |
- Reference (do not re-run): gpt-oss-120b scored **24/24** on the same practice set in T10.
- For each FAIL: id, the problem as printed, and the cause in one line (model / pipeline / checker). Diagnosis only.
- 0 groq/google `llm_call` lines in this task's traces.
- **Choice rule (fixed in advance):** the winner is the model with **0 crashes, 0 wrong writes, ≥ 18/24 and
  ≤ 30 s average per message**; if both pass, the higher score wins (tie → faster). If none passes: no winner;
  report why and stop.
- 3 sentences at the end: the pick and why, the runner-up and why not, the main risk.

## Time box and stop rule
2.5 h. Stop and report if: any Groq/Google call happens, both models fail the smoke test, or a run crashes the
machine / runs out of GPU memory repeatedly.

## Git (approved by Yassine, 2026-10-24)
Commit and push `feature/t13-test-model` (config, the small switch + tests, this task file, the report, NEXT.md).
`out/` stays git-ignored. **No merge into `main`.** Write `tasks/T13_report.md` (In plain words · Done · Evidence ·
Problems · Questions for the Brain · Next step) and set `tasks/NEXT.md` to WAITING FOR REVIEW.
