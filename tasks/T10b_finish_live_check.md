# T10b — Finish T10 on this PC: merges, quota check, regression, held-out live-typing run, demo runbook

## Why
T10 stopped because the free API quotas were used up. The demo will run on **this PC (Yassine's)**, not Dali's, so
everything is merged, run and checked here. We stay on the **free tier** (decision 2026-10-21): spend tokens carefully.

## Hard limits
- `tests/data/live_typing_test_messages.json` (held-out, written by the Brain): run it ONCE, unchanged; never read its
  messages or expected answers to change anything. Do not fix anything after the held-out run; report as it is.
- No change to policies, Coordinator rules, `tests/data/*`. No new provider or library. Never read or stage `.env`.
- `config.yaml` stays `server.demo_enabled: false` in git (see step 5).

## What to do
0. **Merges (approved by Yassine, 2026-10-21).** On `main` (pull first): merge `--no-ff` `origin/feature/live-check` (T10),
   then `origin/feature/demo-screen` (P09, P09b + fixes 3f0333d). Run all tests; if they pass, push `main`. Branch `feature/t10b`.
1. **Quota guard (before any real run).** One tiny real call per agents model (a few tokens). If Groq answers with a
   daily-limit error (the 429 message names tokens per day), STOP and report: do not start anything else.
   Make `scripts/run_live_check.py` **abort the whole run without scoring** if any call fails with a daily-limit error,
   and say so (an aborted run does not count as the "one run"; a run that finished does).
2. **Smoke test:** S1 once (≈ 10k tokens). Must approve 59.90.
3. **Held-out run, once:** `python -m scripts.run_live_check --file tests/data/live_typing_test_messages.json`.
   Keep the full results file (`out/…`) and paste the table into the report exactly as printed.
4. **Regression with what is left:** S0, S2 (`--inject-error`), S3, S4 (once each; S4 more times only if quota allows).
   Leak check 0. Stop cleanly if the daily limit is hit; report which ones ran.
5. **Demo on this PC:**
   - add an override so the demo can be switched on **without editing git files**: env var `CALLVERSE_DEMO_ENABLED=1`
     (default off; config value still works). One test.
   - start the server with it, open `/demo`, press S0 (cheap: Agent A only). One screenshot to `docs/screenshots/`.
   - write `docs/DEMO_RUNBOOK.md`: the exact steps for demo day on this PC, in order: start Ollama; start the server
     (exact PowerShell commands, env var); open the page; warm-up (S0); Reset demo; story order S1 → S3 → S2 → S4 → live;
     what to do if Groq is out (backup models, recording); how to stop. No keys in the file.

## Checks (with numbers)
- All tests pass (report x/y) after the merges and after step 5.
- Quota guard result (OK / stopped).
- Held-out (one run): crashes · leaks · wrong writes (refunds or subscriptions not allowed) · fully passing x/20 ·
  average and max seconds. Targets: 0 · 0 · 0 · ≥ 18/20.
- S1 smoke + regression results per story; leak check 0.
- `/demo` works on this PC (screenshot), runbook written.
- Tokens used today (from traces, `scripts/token_report.py`).

## Time box and stop rule
2 h. Stop and report at the first daily-limit error (except an aborted, unscored held-out run, which you report too).

## Git (approved by Yassine, 2026-10-21)
Step 0 merges into `main` and push. Commit and push `feature/t10b`. No other merge. Write `tasks/T10b_report.md`
(and fill the held-out numbers into `tasks/T10_report.md`), set `tasks/NEXT.md` to WAITING FOR REVIEW.
