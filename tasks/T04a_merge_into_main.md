# T04a — Join `platform` and `feature/intake` into `main`

## Why
`main` is the official version. Two reviewed drafts must join it so every next task starts from one up-to-date
version: Dali's platform (P01–P04: policies, writes, 131 orders, safety nets) and Yassine's Intake (T03).
Review status: both reviewed by the Brain (platform 68/68 tests; intake 34/34 + held-out 18/20). Approved by Yassine.

## Hard limits
- Merge with **`--no-ff`** (keeps a clear history). **No force push. No rebase. No branch deletion.**
- Never commit `.env`, `*.db`, `traces/`, `.venv/`, caches, model caches.
- Do not change code behaviour while resolving conflicts: only combine both sides.
- If a conflict is not in the list below, or a test fails after the merge, **stop and report** (do not push).

## What to do
1. **Protect the Brain's local files.** Run `git status`. Copy every modified or untracked file under `tasks/` and
   `tests/data/` (including this file) to a backup folder **outside the repo**:
   `..\_brain_backup\` (keep the same sub-paths). Then make the working tree clean:
   `git restore` modified tracked files, delete those untracked copies. Do **not** touch `.env`.
2. `git fetch origin` → `git checkout main` → `git pull --ff-only`.
3. **Merge platform:** `git merge --no-ff origin/platform -m "Merge platform (P01–P04) into main"`.
   Run `python -m pytest -q` → expect **68/68** (report).
4. **Merge intake:** `git merge --no-ff origin/feature/intake -m "Merge feature/intake (T03) into main"`.
   Expected conflicts and how to resolve them (combine both sides):
   - `config.yaml`: keep **both** sections (`layer3:` and `intake:`).
   - `README.md`, `docs/architecture.md`: keep both sets of status lines (platform + intake), no duplicates.
   - `tasks/*` files: keep both versions' files; for `tasks/NEXT.md` take the intake side (it is replaced in step 6).
   - `.gitignore`, `requirements.txt`: keep all lines from both sides.
5. `pip install -r requirements.txt` (intake libraries) → run **all** tests → report x/y (expect platform 68 + intake 20
   + any others, all passing). Then run:
   - `python -m scripts.run_demo "Hi, where is my order 4512?"` → still "stuck at the depot" + "6 days late"
     (4512 is now `stuck_at_depot`: check the answer still reads well).
   - `python -m scripts.run_intake "Hi, my order 4512 is a week late. I want my money back!"` → late_delivery + refund_request, HIGH.
   - `python scripts/demo_platform.py` → same RESULT lines as P04.
6. **Restore the Brain's files** from `..\_brain_backup\`: copy back **only** files that do not exist in the merged
   tree **plus** `tasks/NEXT.md`, `tasks/T04_pipeline_router.md`, `tasks/T05_slm.md`, `tasks/T04a_merge_into_main.md`,
   `tests/data/slm_test_decisions.json` (Brain versions win for these). For `P01_*.md`, `P03_*.md`, `NEXT_PLATFORM.md`,
   keep the **merged** (platform) versions.
7. Commit: `"Brain task files: T04a, T04, T05, SLM held-out decisions"`.
8. **Push `main`** (`git push origin main`). Show `git log --oneline -6`.

## Checks (with numbers)
- After platform merge: **68/68**. After intake merge: **all tests pass** (report x/y).
- Demo 4512: "stuck at the depot" + "6 days late". Intake example: HIGH priority. Platform demo: RESULT lines = P04.
- `git ls-files` contains **0** forbidden files; key scan **0** matches.
- GitHub `main` = local `main` (same last commit id).

## Time box and stop rule
45 minutes. Any unexpected conflict or failing test → stop before pushing and report.

## Git (approved by Yassine, 2026-10-20)
Merges into `main` as described, one extra commit for the Brain's files, push `main`. Nothing else.
Write `tasks/T04a_report.md` and set `tasks/NEXT.md` to WAITING FOR REVIEW (commit both in the same push).
