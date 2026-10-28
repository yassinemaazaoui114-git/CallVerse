# T11 report — Merge the demo tools into main (roadmap step 01)

## 1. In plain words
The demo tools built in T10b (the quota check, the demo on/off switch, the one-command demo start and the demo
runbook) were only on a side branch. They are now merged into `main`, so every next task starts with them.
The merge had no conflict, all 300 tests pass, and `main` was pushed to GitHub. No API was called.

## 2. Done
- `git fetch`, `git checkout main`, `git pull` (main was already up to date with origin).
- `git merge --no-ff origin/feature/t10b` → merge commit `d125959` "Merge feature/t10b (T10b demo tools) into main".
- Ran all tests offline (`python -m pytest -q`).
- Pushed `main` (`4cba464..d125959`).
- No code changes. No other branch touched. `.env` not read or staged.

## 3. Evidence
- Merge: no conflict, 13 files changed, 379 insertions, 4 deletions (2 commits from `feature/t10b`: `c3eb0b4`, `e8a36ee`).
- Tests: **300/300 passed** in 88 s on this PC.
- `main` now contains `scripts/quota_check.py`, `start_demo.ps1`, `docs/DEMO_RUNBOOK.md` (all present).
- `config.yaml` line 143: `server.demo_enabled: false` (unchanged).
- Groq quota: untouched (no story, test set or held-out file was run).

## 4. Problems
- Small git detail: my uncommitted edit of `tasks/NEXT.md` (the T11 entry) blocked the switch to `main`, so I stashed
  it, merged, and restored it. It applied cleanly on top of the merged file.
- `tasks/NEXT.md`, `tasks/T11_merge_demo_tools.md` and this report are **not committed**: the task only allowed the
  merge on `main`, and committing them directly on `main` would be an extra push to `main`.
- `.vscode/` is untracked (editor settings); left alone.

## 5. Questions for the Brain
- Where should the T11 task file, this report and `tasks/NEXT.md` be committed? (Options: a small commit on `main`
  with Yassine's OK, or on the first branch of the next task.)

## 6. Next step
Roadmap step 02 (next full-version task), starting a new branch from the updated `main`.
