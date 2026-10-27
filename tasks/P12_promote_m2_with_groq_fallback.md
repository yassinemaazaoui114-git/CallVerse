# P12 — Make the fine-tuned model the default agents model, Groq as fallback  ·  Dali's lane (core files)

## Why
Only if P11 **passed** and Yassine approved the change of the locked decision "M2 = gpt-oss-120b on Groq" (CLAUDE.md).
Then agents A and B (and everything that uses the `agents` role: `ask_agent`, Intake LLM fallback) run locally by
default, and Groq stays as backup. Agents C and D are not part of this task (no code; team decision, see
`docs/m2_finetune_review.md` §5).

## Hard limits
- Start only if `tasks/P11_report.md` says pass **and** "Approved by" names Yassine's OK for the locked-decision change.
- Update CLAUDE.md "Locked decisions" line for M2 only with Yassine's written OK (quote it in the report).
- No change to prompts, Coordinator rules, policies, SLM, Intake or `tests/data/*`.
- Model choice stays in `config.yaml` only. One small pipeline change (step 3), nothing else.

## What to do
1. **Default chain** in `config.yaml` `models.agents`:
   `callverse-m2-abcd` (ollama, temperature 0, seed 42) → gpt-oss-120b (groq) → gpt-oss-20b (groq) → gemini-3.5-flash.
   Provider fallback already works (`llm.chat`: Ollama down = connection error → next model). Comment the reason.
2. **Timeout for the local model.** A cold load can pass 60 s on 4 GB. Add an agent warm-up at start-up like the SLM
   one (`slm.writer.warm_up`), or a per-model `timeout_s` in config read by `llm.chat` (pick one, explain why).
3. **Behaviour fallback (decision 5 in the review).** Today, if the local model answers without any tool, the T10
   safety net re-runs the **same** model once. Add: if that retry still uses no tool, run the agent once more on the
   Groq chain only (e.g. a role `agents_api` = the 3 API models in config). Trace it (`agent_fallback_api`).
   If Yassine says no to this step, skip it and write so in the report.
4. **Tests (offline, fake LLM):** default chain order; Ollama down → Groq used; no-tool answer twice → API role used
   once; no API call when the local model uses tools.
5. **Live check:** `python -m scripts.run_live_check --file tests/dev/live_dev_messages.json` with the new default,
   plus the scenarios S1, S2, S3, S4 (`scripts/run_scenario.py`). Count API fallbacks.

## Checks (with numbers)
- Offline tests x/y, all pass (existing ones unchanged except the chain-order test, explained).
- Practice x/24, crashes, leaks, wrong writes, avg / max s; S1 to S4 pass yes/no with the key line of each.
- `agent_fallback_api` count and `llm_fallback` count; API tokens used.
- With Ollama stopped: one message still gets a correct reply through Groq (proof of fallback).

## Time box and stop rule
2 h. Stop if the practice score drops below P11's, or any wrong write appears.

## Git (needs approval)
Branch from the P11 branch. Commit and push. **Merge into `main` only after the Brain's review and Yassine's OK.**
Write `tasks/P12_report.md`, set `tasks/NEXT_PLATFORM.md` to WAITING FOR REVIEW.
