# T13 report — Local test-model bake-off (daily test model for the agents)

## 1. In plain words
We tried two small models that run on Yassine's PC as a free stand-in for the agents' big online model.
phi4-mini could not use the tools at all, so it was dropped. qwen3.5:4b used the read tools correctly,
passed all 24 practice messages twice with exactly the same answers, and never touched the internet.
**Important limit:** qwen3.5:4b never *makes* a refund or a subscription. It says "I can propose a refund"
in words, but never presses the button, so the safe rules give a plain information reply instead.
It is good for daily tests of reading, routing and replies, not for testing the refund path.

## 2. Done
- Git: `feature/t13-test-model` from `origin/feature/t12-heldout`; committed the task file and `tasks/NEXT.md` first (`ddbade7`).
- Pulled `qwen3.5:4b` (3.3 GB) and `phi4-mini` (2.5 GB). Both official tags existed; no substitute needed.
- Made two Ollama copies with an 8,192-token context: `cv-qwen3.5-4b`, `cv-phi4-mini` (Modelfile
  `FROM <model>` + `PARAMETER num_ctx 8192`).
- `config.yaml`: new separate list `models.agents_local` (both copies, temperature 0, seed 42; qwen with
  `options: {reasoning_effort: none}`). The normal `models.agents` chain is unchanged.
- `callverse/llm.py`: new `model_set()`; `models_for()` uses `models.<role>_local` when
  `CALLVERSE_<ROLE>_SET=local` (here `CALLVERSE_AGENTS_SET=local`). `CALLVERSE_FORCE_AGENTS_MODEL` still keeps one model.
- `scripts/quota_check.py`: with the local set on, it checks only the local models (only the forced one if
  set): no API ping. Default set: unchanged (all 3 API models).
  **Small bug fix needed for the switch:** `check_models()` used to delete `CALLVERSE_FORCE_AGENTS_MODEL`
  after the check, so a forced `run_live_check` silently ran the full chain. It now restores the caller's value.
- New tests `tests/test_agents_set.py` (7, offline): default chain unchanged; switch on → only Ollama models;
  force picks one; forcing an API model in the local set fails; other roles not switched; quota guard
  checks only local models and keeps the forced one; default quota guard unchanged.
- Smoke test (3 tries each), main run per model, repeat run of the winner.
- No change to prompts, agents, Coordinator, policies, SLM, Intake or `tests/data/*`. No held-out file run. `.env` not read.

**Other users of the `"agents"` role:** Agent A and Agent B (`callverse/agents/base_agent.py`, including the
`ask_agent` sub-call) and the **Intake LLM fallback** (`callverse/intake/llm_fallback.py`). All go through
`llm.chat("agents")` → `models_for()`, so they all stay local with the switch on (proof: 2 `intake_llm_fallback`
steps in each run and 0 API calls). Not switched: `slm` (already local) and `simulator` (Gemini, M1; not used
by `run_live_check`).

## 3. Evidence
- **Offline tests: 307/307 passed** (300 before + 7 new).
- **Context 8,192:** `ollama show cv-qwen3.5-4b` and `ollama show cv-phi4-mini` → `num_ctx 8192`;
  `ollama ps` during the run → `CONTEXT 8192`.
- **Thinking off (qwen3.5):** one-off local test on `/v1/chat/completions`, question "17 + 25":
  | Way | Completion tokens | Reasoning text | Time |
  |---|---|---|---|
  | no option | 254 | 797 chars | 60.3 s (incl. first load) |
  | `reasoning_effort: "none"` | **3** | **0** | 0.3 s |
  | `extra_body: {think: false}` | 254 | 797 chars | 5.3 s (ignored on this endpoint) |
  → `reasoning_effort: none` works and is in config. In the runs the largest agent completion was 133 tokens
  (no long reasoning texts). phi4-mini has no thinking mode.
- **Warm-up load (not counted):** cv-qwen3.5-4b 7.9 s, cv-phi4-mini 22.1 s.
- **Smoke test** ("Order 4512 is 6 days late, I want my money back.", 3 tries):
  - cv-qwen3.5-4b: valid tool calls **3/3** (each try `get_order`, `get_refunds`, `ask_agent` → A `get_tracking`,
    `search_policy`); **no `propose_refund`**; outcome `info`; 35–37 s; identical all 3 times.
  - cv-phi4-mini: valid tool calls **0/3**. It writes the tool *schema* back as plain text
    (`[{"type":"function","function":{"name":"get_order","description":...}}]`), no structured call, no
    arguments. **Dropped** (rule: no valid tool call in 3 tries). Trace `traces/run_20261024_222631_711413.jsonl`.
- **Main run** `python -m scripts.run_live_check --file tests/dev/live_dev_messages.json` with
  `CALLVERSE_AGENTS_SET=local`, `CALLVERSE_FORCE_AGENTS_MODEL=cv-qwen3.5-4b`:
  `SUMMARY: 24/24 passed · crashes 0 · leaks 0 · wrong writes 0 · avg 27.2 s · max 42.3 s`
  (trace `traces/run_20261024_222932_715828.jsonl`). No warm-up `Warning:` line. Quota guard line in the trace:
  only `cv-qwen3.5-4b: ok`.
- **Repeat run:** `SUMMARY: 24/24 passed · crashes 0 · leaks 0 · wrong writes 0 · avg 26.9 s · max 42.5 s`
  (trace `traces/run_20261024_224238_046191.jsonl`). All 24 route / outcome / reply lines identical to run 1;
  same agent tokens (103,907). **Repeatable: yes.**
- **GPU (RTX 4050 Laptop, 6,141 MiB):** `ollama ps` showed **one model at a time**: cv-qwen3.5-4b 3.4 GB,
  100% GPU, or qwen2.5:3b 2.2 GB, 100% GPU. `nvidia-smi` during the run: 2.5–4.6 GB used (peak 4,621 MiB with the
  agent model loaded). Ollama swaps agent and SLM between steps (not both in memory) — part of the 27 s.
- **Models / tokens per main run:** cv-qwen3.5-4b 78 calls, 103,907 tokens (avg 5.9 s, max 13.8 s per call);
  qwen2.5:3b (SLM) 28 calls, 15,856 tokens.
- **API calls:** 0 `llm_call` lines with provider groq or google in this task's 4 traces
  (cv-qwen3.5-4b 171, qwen2.5:3b 64, cv-phi4-mini 6).

| Model (tag) | Smoke test (valid tool calls x/3) | Practice set x/24 | Crashes | Leaks | Wrong writes | Avg s / msg | Max s | GPU memory (agent + SLM) | % on CPU | Tool errors (wrong tool, missing step, bad arguments) | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3.5:4b (`cv-qwen3.5-4b`, Q4_K_M, ctx 8192, thinking off) | 3/3 | **24/24** (repeat 24/24, identical) | 0 | 0 | 0 | 27.2 (26.9) | 42.3 (42.5) | 3.4 GB + 2.2 GB, not loaded together; peak 4.6 GB used | 0% | wrong tool 0 · **missing step: 0 `propose_refund` / 0 `propose_subscription`** (gpt-oss in T10: 4 + 1) · bad arguments 0 (2 "order 9999 not found" = correct lookups of an unknown order) | Never proposes an action; writes "I can propose ... sent for checking" as text instead |
| phi4-mini (`cv-phi4-mini`, Q4_K_M, ctx 8192) | **0/3** | not run (dropped) | – | – | – | – | – | 3.6 GB alone | 0% | no structured tool call at all; echoes the tool schema as text | Dropped by the smoke-test rule |

Reference (not re-run): gpt-oss-120b 24/24 on the same set in T10 (avg 12.1 s).

- **FAILs:** none in either run.
- **Not a FAIL, but important (diagnosis only):** the 5 practice messages where gpt-oss made a write
  (d05, d17, d20, d24 refunds; d18 subscription) all ended as `info` with qwen3.5. Cause: **model** — Agent B
  reads, cites the right rule (e.g. R-REF-03, 59.9 TND) and then answers in text ("I can propose a full refund
  under rule R-REF-03 ... This proposal is sent for checking") without calling `propose_refund`. The
  Coordinator correctly ignores a text-only claim, so nothing wrong is written. They pass only because the
  **checker** allows "no write" there (`refund_rows_max: 1`, `*_if_any`, `subscriptions_max: 1`).

## 4. Problems
- **The 24/24 overstates qwen3.5:4b.** It never exercises the action path (proposal → Coordinator approve →
  write). Tests of refunds, subscriptions, finance escalation and Layer 3 still need gpt-oss on Groq.
- **Average 27 s is close to the 30 s limit**, partly because Ollama unloads one model to load the other on
  each agent ↔ SLM step.
- qwen3.5:4b's own defaults include `presence_penalty 1.5` and `top_k 20` (from its Modelfile); we only set
  temperature 0 and seed 42 as the task asked.
- Step 6 of the task ("note `ollama ps`/`nvidia-smi` per model") was done only for qwen3.5 (phi4-mini was dropped before a run).
- Two one-off helper scripts lived only in my scratch folder (thinking test, trace stats); nothing extra committed.

## 5. Questions for the Brain
1. Accept qwen3.5:4b as the daily test model **for read / route / reply tests only**, knowing it never proposes?
2. Should the practice-set checker get a stricter "expected write" mode (e.g. `refund_rows: 1` for d05) so a
   passive model cannot score 24/24? (A checker change on the practice set, never on `tests/data/*`.)
3. Is a code-side fix for "says it proposes but does not call the tool" wanted later (per the fix rule: a check
   or structure, e.g. send back to the agent when the answer claims a proposal but no proposal exists)?
4. Keep both models in memory (e.g. Ollama `OLLAMA_MAX_LOADED_MODELS` / keep-alive settings) to cut the swap time?

## 6. Next step
Brain review. If qwen3.5:4b is accepted for read-path tests, add the stricter "expected write" check on the
practice set, then decide on the code-side check for "claims a proposal without calling the tool".

**Choice (rule fixed in advance):** The pick is **qwen3.5:4b**: 0 crashes, 0 wrong writes, 24/24 twice with
identical results, 27.2 s average (≤ 30 s), and no API use. The runner-up, **phi4-mini**, was dropped because it
made no valid tool call in 3 tries (it echoes the tool schema as text). The main risk: qwen3.5:4b never calls the
proposal tools, so it cannot test the refund / subscription path and its 24/24 hides that gap.
