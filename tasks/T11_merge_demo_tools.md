# T11 — Merge the demo tools into main (roadmap step 01)

## Why
The quota check, the demo switch (`CALLVERSE_DEMO_ENABLED`), `start_demo.ps1` and `docs/DEMO_RUNBOOK.md` are still
only on `feature/t10b`. Every full-version task starts from `main`, so `main` must have them first.

## Hard limits
- Only this merge. No code changes, no new features.
- Do NOT run any story, test set or held-out file that calls an API (keep the Groq quota for step 06).
- No secrets; never read or stage `.env`.

## What to do
1. `git fetch`, `git checkout main`, `git pull`.
2. `git merge --no-ff origin/feature/t10b` (the Brain checked: no conflict expected).
3. Run all tests (`python -m pytest -q`, no API calls).
4. If all pass, push `main`.

## Checks (with numbers)
- Tests x/y (expected 300/300 on this PC).
- `main` contains `scripts/quota_check.py`, `start_demo.ps1`, `docs/DEMO_RUNBOOK.md`.
- `config.yaml` still has `server.demo_enabled: false`.

## Time box and stop rule
20 minutes. Stop and report if there is any conflict or any failing test.

## Git (approved by Yassine, 2026-10-23)
Merge `feature/t10b` into `main` and push. No other branch changes. Write `tasks/T11_report.md`,
set `tasks/NEXT.md` to WAITING FOR REVIEW.
