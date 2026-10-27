# P11 — Fine-tuned agent model on the practice set (bake-off vs base Qwen3-4B)  ·  Dali's lane

## Why
Only if P10 said **GO**. P10 checks two hand-made cases; this task measures the fine-tuned model on the 24 practice
messages through the real pipeline (Intake → Queues → Agent A/B → Coordinator → SLM), next to the base model it was
trained from, so we know what the fine-tune adds. Default behaviour stays Groq. Background: `docs/m2_finetune_review.md`.

## Hard limits
- Start only if `tasks/P10_report.md` says GO.
- Build on the local switch of T13 (`CALLVERSE_AGENTS_SET=local`, `models.agents_local`): branch from
  `origin/feature/t13-test-model`, or from `main` if T13 is merged by then. **Do not re-invent the switch.**
- The default `models.agents` chain (gpt-oss-120b → gpt-oss-20b → gemini-3.5-flash) stays exactly the same.
- No change to prompts, agents, Coordinator, policies, SLM, Intake or `tests/data/*`.
  **Fix rule (as T13):** model errors are described, not fixed here; never prompt tricks for one model.
- Only `tests/dev/live_dev_messages.json`. No Groq / Gemini call (check traces: 0 groq/google `llm_call` lines).

## What to do
1. **Config.** In `models.agents_local` add, before the T13 entries:
   - `{provider: ollama, model: "callverse-m2-abcd", temperature: 0, seed: 42}`
   - `{provider: ollama, model: "cv-qwen3-4b-instruct", temperature: 0, seed: 42}` = the base model with
     `num_ctx 8192` (create it like T13: Modelfile `FROM qwen3:4b-instruct-2507-q4_K_M` + `PARAMETER num_ctx 8192`).
   Comment both lines (what, why, test stand-in only until P12).
   No `reasoning_effort`: the Instruct-2507 model has no thinking mode. Check it in the trace (short completions).
2. **Tests (offline).** Extend `tests/test_agents_set.py`: the local set lists `callverse-m2-abcd` first; forcing it
   keeps only it; default chain unchanged.
3. **Runs, one model at a time** (`ollama stop` between):
   `CALLVERSE_AGENTS_SET=local CALLVERSE_FORCE_AGENTS_MODEL=<model> python -m scripts.run_live_check --file tests/dev/live_dev_messages.json`
   for `callverse-m2-abcd` and `cv-qwen3-4b-instruct`. Note `ollama ps` and `nvidia-smi` once per run.
4. **Repeat** the winner once (repeatability).
5. **Action path count.** For d05, d17, d20, d24 (refunds) and d18 (subscription): did the agent call the proposal tool?
   (T13 showed a passive model can still score 24/24 there.)

## Checks (with numbers)
- Offline tests x/y, all pass.
- One row per model: practice x/24 · crashes · leaks · wrong writes · proposals made x/5 (d05, d17, d18, d20, d24) ·
  `search_policy` called before each proposal x/y · T10 retries (`agent_retry` lines) · avg / max s per message ·
  GPU memory · % CPU · tool errors (wrong tool, missing step, bad arguments).
- Reference (do not re-run): gpt-oss-120b 24/24 in T10 (avg 12.1 s); qwen3.5:4b 24/24 with 0/5 proposals in T13.
- For each FAIL: id, the problem as printed, cause in one line (model / pipeline / checker).
- **Choice rule (fixed in advance).** `callverse-m2-abcd` **passes** if: 0 crashes, 0 wrong writes, ≥ 20/24,
  **≥ 4/5 proposals made**, avg ≤ 30 s per message, and it is not worse than `cv-qwen3-4b-instruct` on score or
  proposals. Otherwise it fails; say which condition.
- 3 sentences: pass/fail and why, what the fine-tune changed vs the base, the main risk.

## Time box and stop rule
2.5 h. Stop and report on any Groq / Google call, a crash of the machine, or repeated out-of-memory.

## Git (needs approval)
Commit and push `feature/m2-finetuned` (config, tests, this task file, report). No merge into `main`.
Write `tasks/P11_report.md`, set `tasks/NEXT_PLATFORM.md` to WAITING FOR REVIEW.
