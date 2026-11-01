# T14d finish — Dali's model on top of T14d, switch if it wins, then the T14d held-out (all local)

## Why
M2T3 (branch `test/m2-v3-agent-b`): on the 60 real messages Dali's `callverse-m2-v3` scored 53/56 vs our cv-qwen3.5-4b 46/56, but made
2 wrong writes (t14c h03, h12) — the same 2 that Groq makes and exactly the 2 cases T14d items 1–2 fix (already built on this branch).
Approved by Yassine 1 Nov 22:57: do it all tonight, local, no quota wait. **No merge** (Yassine merges after the Brain's review).

## Win rule (fixed before the run — do not change)
On the 60 messages **with T14d's code**, setup D (A + B = callverse-m2-v3) wins if: 0 crashes, 0 leaks, **0 wrong writes**
(M2T3's definition: runner WRONG WRITE, or any refund / compensation row, or order / booking status change not allowed by `expect`),
and expect passes **≥ 46** (setup L's score in M2T3). Speed reported only.

## Hard limits
Never read `.env`; no secrets; never commit `models/` / `data/raw/`; no force push / rebase / reset; **no merge into main**.
Step 2 runs with 0 Groq calls (all agent roles forced local). No prompt, tool, rule, Coordinator or writer change beyond T14d's.
`tests/data/t14d_heldout_messages.json`: open it **only in step 4**, run it **once**, fix nothing after it.

## What to do
0. You are on `feat/t14d-request-match` with `tasks/NEXT.md` changed and this file new (Brain). Commit both ("NEXT: T14d finish (Brain)"), push.
1. Bring onto this branch, from `test/m2-v3-agent-b`: the `callverse-m2-v3` entry in `config.yaml` and `scripts/compare_m2t.py`
   (cherry-pick or copy; list the commits). Full suite green.
2. **Run setup D on the 60** (same 5 files and runners as M2T3, fresh DBs, clock 2026-10-09, forced local) → `out/t14d_D_<set>.json`.
   Compare with M2T3's L and D (`compare_m2t.py`): per message + totals + the **WIN RULE line**. Say what T14d changed (h03, h12, h04, others).
3. **If the rule is true — switch** (as written in M2T3 step 3): Agent A = `callverse-m2-v3` → `cv-qwen3.5-4b`; Agent B = `callverse-m2-v3` →
   Groq chain (120b → 20b → Gemini); quota check does not ping Groq when the local model answers; update the tests that pin model order
   (list them), README model table, `docs/architecture.md`, `docs/DEMO_RUNBOOK.md`. Full suite green. Commit.
   **If false:** no switch; stop after step 2 and report (the held-out then waits for the Groq quota on Monday).
4. **T14d held-out, once** (only if step 3 switched): `python -m scripts.run_t14c --file tests/data/t14d_heldout_messages.json --out out/t14d_heldout.json`
   with the NEW default config (no forcing). Record per message which model answered (any Groq fallback = say so). Pass bar from the T14d
   task: ≥ 10/12, 0 crashes, 0 leaks, 0 wrong writes (runner incl. order status), 0 forbidden words. Note in the report: T14c's held-out ran on Groq,
   this one on the local model (Yassine's choice).
5. Write `tasks/T14d_report.md` (items 0–6 + the switch: In plain words · Numbers · Problems · Questions for the Brain · Next step).
   Set `tasks/NEXT.md` to **WAITING FOR REVIEW** (T14d + model switch). Commit, push `feat/t14d-request-match`. **No merge.** Copy the report to `out/T14d_report.md`.

## Time box
2.5 h (60 local runs + 12 held-out). WIP stop allowed after step 2.
