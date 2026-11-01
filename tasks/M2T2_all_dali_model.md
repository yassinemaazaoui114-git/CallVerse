# M2T2 — Agents A and B both on Dali's model (callverse-m2-v3); if it wins, make it the default with Groq as backup

## Why
M2T (branch `test/m2-v3-agent-b`): Dali's model as Agent B = 21/24 checks vs Groq 20/24, 0 wrong writes, ~19 s vs ~7 s per message.
Yassine (1 Nov 21:30): test it **overall** (A + B) on the same 24 real messages, and if it wins, **use it now** — local first,
Groq only as a backup (tired of quota limits). Local only for the test: **0 Groq calls**. No merge (Yassine merges after the Brain's review).

## Win rule (fixed before the run — do not change)
Setup 3 (A = m2-v3, B = m2-v3) **wins** if, on the 24 messages: 0 crashes, 0 leaks, **0 wrong writes**, expect passes **≥ setup 1's (20)**,
and average seconds per message **≤ setup 2's (19.1)**. Speed is part of the rule this time (one model loaded instead of two should be faster).

| Setup | Agent A | Agent B | Source |
|---|---|---|---|
| 1 | cv-qwen3.5-4b (local) | Groq | `out/t14c_practice_run1.json`, `out/t14c_heldout.json` (already run) |
| 2 | cv-qwen3.5-4b (local) | m2-v3 | `out/m2t_practice.json`, `out/m2t_dev.json` (M2T) |
| 3 | **m2-v3** | **m2-v3** | **new run** |

## Hard limits
Never read `.env`; no secrets; never commit `models/` / `data/raw/`; no force push / rebase / reset; **no merge into main**.
0 Groq/API calls in the test (force both roles local: `CALLVERSE_AGENTS_SET=local`, `CALLVERSE_FORCE_AGENT_A_MODEL` / `..._AGENT_B_MODEL`
or the existing mechanism). No prompt, tool, rule, Coordinator or writer change. Do not open `tests/data/t14d_heldout_messages.json`.
Stop if RAM < 300 MB or GPU out of memory.

## What to do
0. You start on `feat/t14d-request-match` with `tasks/NEXT.md` changed and this file new (Brain). Commit both there ("NEXT: M2T2 (Brain)"), push.
   Then `git checkout test/m2-v3-agent-b`, `git pull` (it has the model entry in `config.yaml`). `ollama list` must show `callverse-m2-v3`.
1. **Run setup 3** with `scripts/run_t14c.py` on `tests/dev/t14c_practice_messages.json` and `tests/data/t14c_heldout_messages.json`
   → `out/m2t2_practice.json`, `out/m2t2_dev.json`. Also note which model each Agent A call used (from the trace).
2. **Compare** (extend `scripts/compare_m2t.py`): table per message with the 3 setups (outcome, pass, seconds), totals per setup
   (passes, wrong writes, crashes, leaks, avg / p95 s, Agent A tool problems, Groq calls = 0), and the **WIN RULE line**.
3. **Only if the rule is true — make it the default (Yassine's request):** in `config.yaml` on this branch, Agent A and Agent B use
   `callverse-m2-v3` FIRST; the Groq chain (gpt-oss-120b → 20b → Gemini, as today) stays AFTER it as the backup when the local model
   fails or Ollama is down. The SLM writer, Intake and every other role unchanged. Update the tests that pin the model order on purpose
   (list them), the quota check (do not ping Groq when the local model answers), README model table and `docs/` if they name the models.
   Full test suite green. If the rule is false: change nothing, say why.
4. Commit on `test/m2-v3-agent-b`, push. **No merge.** Write `tasks/M2T2_report.md`, copy to `out/M2T2_report.md`.
   Then `git checkout feat/t14d-request-match`, put `tasks/NEXT.md` back to T14d IN PROGRESS (items 5–6), "Last done" = M2T2. Commit, push.

## Time box
1 h. WIP stop allowed. Start Ollama first.
Report format: In plain words · Numbers (WIN RULE true/false) · Problems · Questions for the Brain · Next step.
