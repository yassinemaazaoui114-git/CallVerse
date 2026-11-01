# M2T3 — Dali's model vs our local model on all 60 test messages; if it wins, make it the default (Groq as backup)

## Why
M2T / M2T2: Dali's `callverse-m2-v3` as Agent B = 21/24 vs Groq 20/24, 0 wrong writes. M2T2's speed rule was badly designed
(Brain's mistake: a tie lost by 0.09 s, and the 24 messages never used Agent A on its own). Yassine (1 Nov 21:57): test on **everything
we have** — all 60 real messages with written answers — and if it is as safe and as good, **use it now**, Groq only as backup.
Local only: **0 Groq calls**. No merge.

## The 60 messages (all real TWCS tweets with an `expect`; NOT the T14d held-out)
`tests/dev/decline_practice_messages.json` (12), `tests/data/decline_heldout_messages.json` (12, already used: dev now),
`tests/dev/t14b_practice_messages.json` (12), `tests/dev/t14c_practice_messages.json` (12), `tests/data/t14c_heldout_messages.json` (12, dev now).
Use the runner that fits each format (`scripts/run_t14c.py`, `scripts/run_decline_check.py`); fresh DBs per message, clock 2026-10-09.
If one set has no `expect` for a message, count only crash / leak / wrong write for it and say so.

## Setups (both fully local, same code: branch `test/m2-v3-agent-b`)
| Setup | Agent A + its own turns | Agent B (+ its "ask A" calls) |
|---|---|---|
| **L** (ours, local) | cv-qwen3.5-4b | cv-qwen3.5-4b |
| **D** (Dali) | callverse-m2-v3 | callverse-m2-v3 |
Reference only (not in the rule): the saved Groq runs on the same messages, if any exist in `out/` (say which code they came from).

## Win rule (fixed before the run — do not change)
D **wins** if on the 60: 0 crashes, 0 leaks, **0 wrong writes** (any refund row or order/booking status change not allowed by `expect`),
and expect passes **≥ L's**. Speed is reported (avg / p95 s), **not** part of the rule.

## Hard limits
Never read `.env`; no secrets; never commit `models/` / `data/raw/`; no force push / rebase / reset; **no merge into main**.
0 Groq/API calls during the runs (force all agent roles local; check the traces). No prompt, tool, rule, Coordinator or writer change.
Do not open `tests/data/t14d_heldout_messages.json`. Stop if RAM < 300 MB or GPU out of memory.

## What to do
0. You start on `feat/t14d-request-match` with `tasks/NEXT.md` changed and this file new (Brain). Commit both there ("NEXT: M2T3 (Brain)"), push.
   `git checkout test/m2-v3-agent-b`, `git pull`. Ollama running; `ollama list` shows `callverse-m2-v3` and `cv-qwen3.5-4b`.
1. Run setup L on the 60, then setup D on the 60 → `out/m2t3_L_*.json`, `out/m2t3_D_*.json`. Count Agent A's OWN turns
   (not "ask A" sub-calls) per setup and list which messages had them.
2. Compare (extend `scripts/compare_m2t.py --m2t3`): per message (id, set, expected, L got, D got, Groq ref if any, pass, seconds);
   totals per setup (passes, wrong writes, crashes, leaks, avg / p95 s, tool problems, Groq calls = 0); separate line for Agent A's own turns;
   the **WIN RULE line**.
3. **Only if the rule is true — switch (Yassine's request):** in `config.yaml`: Agent A = `callverse-m2-v3` first, then `cv-qwen3.5-4b`
   (local backup), then the current backup if any; Agent B = `callverse-m2-v3` first, then the Groq chain as today (120b → 20b → Gemini).
   Intake fallback, SLM writer and every other role unchanged. Quota check: do not ping Groq at start when the local model answers.
   Update the tests that pin model order (on purpose; list them), README model table, `docs/architecture.md`, `docs/DEMO_RUNBOOK.md`.
   Full suite green. If the rule is false: change nothing, say exactly where D lost.
4. Commit on `test/m2-v3-agent-b`, push. **No merge.** Write `tasks/M2T3_report.md`, copy to `out/M2T3_report.md`.
   Then `git checkout feat/t14d-request-match`, put `tasks/NEXT.md` back to T14d IN PROGRESS (items 5–6), "Last done" = M2T3. Commit, push.

## Time box
2 h (120 local runs at ~20 s + model swaps). WIP stop allowed between setups.
Report format: In plain words · Numbers (WIN RULE true/false) · Problems · Questions for the Brain · Next step.
