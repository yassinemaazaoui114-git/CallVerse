# T16 — Agent B gets its own model setting (Groq), so the refund path works while the rest runs locally

## Why
Decision 2026-10-29 (option A, temporary test setup): the local agent model (qwen3.5:4b) reads, routes and replies
well but almost never calls `propose_refund` (T13c/T13f: d05, d17, d20, d24). So **only Agent B** runs on Groq
gpt-oss-120b; Intake, Agent A, the Coordinator and the SLM stay local. The ShopNova chat (T17) needs this to show
real refunds. Final setup is decided after our M2 benchmark. All details approved by Yassine on 2026-10-29
(items 1–7, all the Brain's ⭐).

## Hard limits
- **No change** to prompts, the agents' logic, tools, the Coordinator, rules, Intake, SLM. Only: model routing
  (`config.yaml`, `callverse/llm.py` if needed, `BaseAgent`/`AgentB` role key, `ask.py` sub-call role), the live-check
  pause, tests, docs.
- **0 Gemini calls** (B's list has no Gemini). Never run `tests/data/*` (held-out). Never read or stage `.env`.
- Default behaviour with **no switch set must stay exactly as today** (all agents on the Groq chain).

## What to do
0. **Git.** `git fetch`, `git checkout main`, `git pull` (main = 0a0f461 or later, pushed by Yassine). If `main` is
   not pushed yet, stop and ask. Branch `feature/t16-agent-b-model`. Commit this task file + `tasks/NEXT.md`
   (IN PROGRESS) first.
1. **`config.yaml`:** new list `models.agent_b`:
   `gpt-oss-120b` (Groq, `reasoning_effort: low`), then `gpt-oss-20b` (Groq, same options) as backup. No Gemini.
   New `models.agent_b_local` = the same entries as `agents_local`; write the local list **once** (YAML anchor /
   alias), so the two can never drift. Comment: T16, option A, temporary test setup, decided after the M2 benchmark.
2. **Who uses it:** Agent B's turns use role `agent_b` (e.g. `role_key = "agent_b"` on `AgentB`). Its **"ask Agent A"
   sub-call** (`callverse/agents/ask.py`) also runs on `agent_b` (Agent A's code and prompt unchanged; only the role
   key of that one call). Agent A in its own turns, and the Intake LLM fallback, keep role `agents`.
3. **Switches (existing mechanism in `llm.py`, no new idea):**
   - `CALLVERSE_AGENTS_SET=local` → Intake fallback + Agent A local; **B stays on Groq** (its own role).
   - `CALLVERSE_AGENT_B_SET=local` → B (and its sub-call) local too (`agent_b_local`).
   - `CALLVERSE_FORCE_AGENT_B_MODEL` works for B like the existing force switch. `CALLVERSE_FORCE_AGENTS_MODEL` no
     longer affects B: say so in the config comment and the README.
   - No switch → today's behaviour: A and B both on the Groq chain (B on its own 120b → 20b list).
4. **Live-check pause:** `scripts/run_live_check.py` pauses 5 s between messages when **any** agent role is on an API
   (agents or agent_b on the default set), 0 s only when both are local.
5. **Tests (offline, fake LLM, no API):** B asks role `agent_b`; B's sub-call to A asks `agent_b`; A's own turn asks
   `agents`; each switch combination picks the right list (no switch / AGENTS local / both local / force B);
   `agent_b` never contains a Gemini entry; pause rule. Full suite: **all pass**.
6. **Check run (once):** the 24 practice messages `tests/dev/live_dev_messages.json` with `CALLVERSE_AGENTS_SET=local`
   (A + Intake fallback on `cv-qwen3.5-4b`, B on Groq), strict checker, SLM qwen2.5:1.5b. Compare with T13f
   (19/24, local only): score, which failed, leaks, wrong writes, proposals made by B, reply sources, avg / max s
   per message. **Groq tokens used** (from the traces, e.g. `scripts/token_report.py`), calls per model. If Groq's
   **daily** limit answers, stop the run and report how far it got.
   Before the run: Yassine closes browsers (RAM).

## Checks (with numbers)
- Tests x/y (all pass); new tests listed.
- Practice run: x/24 vs 19/24; failed ids and why; B's proposals x (approved / sent back / layer3); leaks 0, wrong
  writes 0; reply sources; avg / max s per message; Groq tokens total + per message; calls per model and provider.
- `llm_call` lines: provider per role (A + Intake fallback = ollama only; B + its sub-call = groq only); **0 google**.
- One sentence each: does the refund path work now? is the Groq daily quota a risk for the demo?

## Time box and stop rule
45 min. Stop and report if: `main` is not pushed, a test fails, a Gemini call happens, the Groq daily limit answers,
or memory gets critically low.

## Git (approved by Yassine, 2026-10-29)
Commit and push `feature/t16-agent-b-model` (config, code, tests, README/docs, task file, report, `tasks/NEXT.md`).
**No merge into `main`.** Write `tasks/T16_report.md` (In plain words · Done · Evidence · Problems · Questions for the
Brain · Next step) and set `tasks/NEXT.md` to WAITING FOR REVIEW.
