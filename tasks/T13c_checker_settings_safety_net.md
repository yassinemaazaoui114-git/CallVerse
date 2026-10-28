# T13c — Stricter practice checker, qwen3.5 settings tests, "claims a proposal" safety net (+ 3 small fixes)

## Why
- In T13, qwen3.5:4b scored 24/24 although it never made a refund or subscription: the practice checker allowed
  "no write" on the 5 action messages. In T13b (Ollama 0.40.12) it **did** propose on d20. We need an honest score.
- Two qwen3.5 defaults may hurt tool calls (presence_penalty 1.5 punishes repeating order numbers / tool names).
- When the agent **writes** "I propose a refund … sent for checking" but calls no proposal tool, nothing happens.
  Fix rule (Confirmed): fix it in code, not with a model-specific prompt trick.
All details below were agreed with Yassine on 2026-10-28 (items 1–10, all the Brain's ⭐ options).

## Hard limits
- **0 API calls** (local Ollama only). Ollama stays 0.40.12.
- No change to agent prompts, the Coordinator, policies, the SLM, Intake or `tests/data/*` (held-out).
- The settings tests are **test-only**: the winning setting goes into `config.yaml` only after Yassine's OK
  (report it; do not change `models.agents_local` settings in this task).
- Never read or stage `.env`.

## What to do
1. **Git.** `git fetch`; create `feature/t13c-checker` from `origin/feature/t13b-context`. Commit this task file
   and the current `tasks/NEXT.md` first (the Brain edited it; commit it as is).
   Ollama must be running (`ollama list` answers). If not: stop and report.
2. **Three small fixes (from T13b):**
   - `ollama rm cv-qwen3.5-4b-ctx16384` (leftover copy). Check `cv-qwen3.5-4b` is still `num_ctx 8192`.
   - `config.yaml` comment above `agents_local`: replace "one agent turn is ~6,000 tokens" with the measured fact:
     the largest single prompt is ~2,300 tokens (T13b); ~6,000 was the total of all calls in one turn.
   - `CALLVERSE_FORCE_AGENTS_MODEL`: when `CALLVERSE_AGENTS_SET=local`, accept **any Ollama model name** (even if not
     listed in `models.agents_local`), using the same settings as the first local entry. Default set: unchanged
     (a forced name must still be in the list). Offline tests for both cases.
3. **Stricter practice checker (L2), practice set only** (`tests/dev/live_dev_messages.json`):
   change the `expect` of the 5 action messages to exact values:
   - d05: `refund_rows: 1`, `refund_amount: 59.9` (order 4512); keep its `reply_not_contains`.
   - d17: `refund_rows: 1`, `refund_amount: 378.0` (order 4515); keep `if_refund_reply_contains: finance`.
   - d18: `subscriptions: 1`, `subscription_event_if_any: out_for_delivery`; keep its other keys.
   - d20: `refund_rows: 1`, `refund_amount: 59.9`, `refund_order_if_any: 4512`.
   - d24: `refund_rows: 1`, `refund_amount: 59.9`.
   Do not change any other message. Say in the report that gpt-oss passed these in T10 (24/24 with 4 refunds + 1
   subscription), so the new expectations match what a correct agent does.
4. **Settings tests (L5), 3 full runs** of the 24 practice messages with the stricter checker,
   `CALLVERSE_AGENTS_SET=local`, seed 42, **without** the safety net:
   - Run 1: today's settings (presence_penalty 1.5 from qwen's defaults, temperature 0) — also re-checks T13's
     "never proposes" on Ollama 0.40.12;
   - Run 2: presence_penalty **0**, temperature 0;
   - Run 3: presence_penalty **0**, temperature **0.3**.
   Set the values for the run only (e.g. a temporary Ollama copy forced by name, thanks to fix 2, or request options);
   say exactly how. `config.yaml` keeps today's settings.
5. **Safety net (L3), detection by the agent's own text (option a):**
   in `pipeline.run_agent_with_coordinator`, after the agent's turn: if the answer **claims** a proposal (e.g.
   "propose", "proposal", "sent for checking", "submitted … for review") **and** the agent called no proposal tool
   (`propose_refund` / `propose_subscription`) **and** there is no proposal, run the same agent **once more** with
   a short note: the answer says it proposes, but no proposal tool was called; if a rule allows it, call the
   proposal tool now; otherwise answer without saying that anything is proposed.
   - At most **1** such retry per case (on top of the existing T10 retry, never more than 2 extra runs in total).
   - Trace it as a new step (e.g. `proposal_claim_retry`). Keep the phrase list short and in code, with tests
     (offline, fake LLM): claim + no tool → one retry; claim + tool → no retry; no claim → no retry.
   - The Coordinator still checks every proposal as before (the net never writes anything itself).
6. **Run 4:** the **best** of runs 1–3 (highest score with the stricter checker; tie → faster) **with** the safety net.
7. **5 s pause (R3):** in `scripts/run_live_check.py`, wait 5 s between messages **only when the agents use the
   default (Groq) set**; no pause with `CALLVERSE_AGENTS_SET=local`. One offline test. Do not run any Groq test.

## Checks (with numbers)
- Offline tests x/y (all pass), incl. the new ones.
- `cv-qwen3.5-4b`: `num_ctx 8192`; `cv-qwen3.5-4b-ctx16384` gone.
- One table:
  | Run | presence_penalty | temperature | Safety net | x/24 (strict) | Refunds / subscriptions made (of 4 / 1) | Crashes | Leaks | Wrong writes | Avg / max s per msg | Safety-net retries (how many helped) |
- For each FAIL: id, the problem as printed, cause in one line (model / pipeline / checker). Diagnosis only.
- Per run: which of d05, d17, d18, d20, d24 made the right write.
- 0 `llm_call` lines with provider groq or google.
- One sentence: the setting you would recommend for `models.agents_local`, and whether the safety net is worth keeping.

## Time box and stop rule
2.5 h. Stop and report if: Ollama is not running, any API call happens, a test fails, or a run crashes twice.

## Git (approved by Yassine, 2026-10-28)
Commit and push `feature/t13c-checker` (code, tests, practice-set expectations, config comment, task file, report,
`tasks/NEXT.md`). **No merge into `main`.** Write `tasks/T13c_report.md` (In plain words · Done · Evidence ·
Problems · Questions for the Brain · Next step) and set `tasks/NEXT.md` to WAITING FOR REVIEW.
