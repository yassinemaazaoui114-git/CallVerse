# Task 00: Map the existing code (read-only)

## Goal
Understand the CallVerse repo before we change anything. **Do not edit, create or delete any file except `docs/platform_map.md`.**

## Read first
1. `docs/platform.md` (platform brief).
2. `docs/platform_contract.md` (source of truth: tables, tool shapes, write functions, events, scripted cases).
3. `CLAUDE.md` and `README` if present, plus `config.yaml`.

If `docs/platform.md` and `docs/platform_contract.md` disagree, the contract wins. List every difference.

## Find and report
1. **ShopNova database**: where the SQLite file is, where its schema and seed code live, the existing tables and columns.
2. **Scripted orders**: check that orders 4505-4514 exist and match the table in `docs/platform.md` (4512: Sara, 59.90 TND, promised 2026-10-03, stuck at depot; 4506 refunded 189 TND; 4514 cash on delivery, 0 paid; and so on).
3. **Read tools**: the 3 existing tools, their Python signatures and JSON definitions.
4. **Registry and allow-lists**: where tools are registered, how the per-agent allow-list check works, what agent A is allowed.
5. **Agent A**: where it lives and how it calls the LLM (Groq `gpt-oss-120b`, backup `gpt-oss-20b`).
6. **Traces**: where tool calls are recorded and in what format.
7. **Config**: how `config.yaml` and `.env` are loaded. Confirm `.env` is in `.gitignore`. Never print key values.
8. **Tests**: how to run them. Run them and report pass/fail counts.

## Gap list
Compare the repo with `docs/platform_contract.md` and list what is missing for the platform:
- tables or columns (refunds, subscriptions, simulated clock, `ai_generated` / `scripted` flags, ...)
- read tools needed by agents A and B
- Coordinator-only write functions (refund with status `approved`, subscription with status `waiting`)
- clock / events for notifications (shipped, out_for_delivery, delivered)
- Layer 3 stub (above 300 TND to finance, approve up to 500, refuse above)
- policy files (R-DEL-01, R-DEL-02, R-REF-03, R-REF-05, R-RET-01, R-DMG-01, R-ESC-01, R-NOT-01)

## Output
Write `docs/platform_map.md` with these sections:
1. Repo layout (short tree of relevant folders only)
2. Existing pieces (one line each, with `file:line`)
3. Test result
4. Brief vs contract differences
5. Gap list (ordered by what blocks the demo first: S1 refund, S2 wrong amount sent back, S3 notification)
6. Open questions for Yassine

Then reply with a 5-line summary. Stop there. No code changes in this task.

## Done when
- `docs/platform_map.md` exists with all 6 sections.
- Tests were run and the result is reported.
- `git status` shows no changes besides `docs/platform_map.md`, `docs/platform.md`, `tasks/P00_map_code.md` and the `CLAUDE.md` "Platform work" section.
