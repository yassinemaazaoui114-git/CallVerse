# T12 — Run the unseen live-typing test once (roadmap step 06)

## Why
The prototype's last open number: how the whole system copes with 20 free-typed messages it has never seen.
T10b's attempt was aborted unscored at message 16 (gpt-oss-120b daily limit), so the one official run is still
unused. Yassine's quota check on 2026-10-24 10:11: gpt-oss-120b OK, gpt-oss-20b OK, gemini-3.5-flash OK.
The run needs about 80,000–120,000 gpt-oss-120b tokens in one go (limit: 200,000 per rolling 24 h).

## Hard limits
- `tests/data/live_typing_test_messages.json` is held-out (written by the Brain). Run it **once**, unchanged.
  Do not open or read its messages or expected values, before or after.
- **No fixes** after the run, even small ones. Report the results as they are. Fixes come in a later task,
  checked on new data (roadmap step 08), never on this file.
- No code, config, policy, Coordinator rule or `tests/data/*` change in this task.
- No other API run before the held-out run (no story, no smoke test, no dev set): the full quota goes to it.
- Never read, stage or print `.env`.

## What to do
1. **Git.** `git fetch`, `git checkout main`, `git pull` (expect `d125959`). Create branch `feature/t12-heldout`.
   Commit the files left from T11: `tasks/T11_merge_demo_tools.md`, `tasks/T11_report.md`, `tasks/NEXT.md`,
   plus this file. Leave `.vscode/` alone.
2. **Offline tests.** `python -m pytest -q` (no API). Expected 300/300. If any test fails, STOP and report.
3. **Quota window check (no API).** Sum the `llm_call` tokens per model from `traces/*.jsonl` written in the last
   24 h (use the file timestamps). Do not commit a new script for this; a one-off command is fine.
   - If gpt-oss-120b used **more than 60,000** tokens in the last 24 h → STOP, report the numbers, do not run.
4. **Ollama up.** Start Ollama if needed and check that `qwen2.5:3b` answers (e.g. `ollama list` plus one
   request to `http://localhost:11434/api/tags`). If Ollama is not up, STOP: replies would come from the
   fallback template and the result would not reflect the system.
5. **The run, once.**
   `python -m scripts.run_live_check --file tests/data/live_typing_test_messages.json`
   - If it prints `ABORTED, NOT SCORED`: it does **not** count as the one run. Do not rerun today. Report it.
   - If it prints the warm-up `Warning:` line, say so in the report.
6. **After the run.** `python -m scripts.quota_check` once (to record what is left).
   Paste into the report the per-message table and the SUMMARY line **exactly as printed**.
   Fill the held-out numbers into `tasks/T10_report.md` (section 3, the "Held-out run" bullet) and
   `tasks/T10b_report.md` (section 3, the "Held-out run" bullet), marked "done in T12".

## Checks (with numbers)
- Offline tests x/y (expected 300/300).
- Tokens per model in the 24 h before the run (from traces).
- Held-out run, one finished run: crashes · leaks · wrong writes · fully passing x/20 · avg and max seconds.
  **Pass = 0 · 0 · 0 · ≥ 18/20.**
- For each FAIL: id, route, outcome, the problem text as printed, and which part caused it
  (Intake / router / agent / Coordinator / SLM / checker) in one line. Diagnosis only, no fix.
- Which models answered during the run (count of `llm_call` per model in the run's trace), and whether any
  backup model was used.
- Tokens used by the run per model (from its trace).
- `quota_check` result after the run.

## Time box and stop rule
45 minutes (the run itself takes about 4–12 minutes). Stop and report at: a failing offline test, more than
60,000 gpt-oss-120b tokens in the last 24 h, Ollama down, or an aborted run.

## Git (approved by Yassine, 2026-10-24)
Commit and push `feature/t12-heldout` (T11 files, this file, the report, the T10 / T10b report updates,
`tasks/NEXT.md`). `out/` stays git-ignored. **No merge into `main`.** Write `tasks/T12_report.md`
(In plain words · Done · Evidence · Problems · Questions for the Brain · Next step) and set `tasks/NEXT.md`
to WAITING FOR REVIEW.
