# RL1d — Rename the style names in agent F (missed step of RL1c)

## Why
RL1c step 1b (added by the Brain after you started) was not done: agent F still uses the old style names. Yassine decided we do it ourselves.
Tiny task. 0 Groq, no merge.

## Hard limits
Never read `.env`; no secrets; no `models/` / `data/raw/` commits; no force push / rebase / reset; **no merge into main**. Nothing else in F changes.

## What to do
0. You start on `feat/t14d-request-match` with `tasks/NEXT.md` changed and this file new (Brain). Commit both there ("NEXT: RL1d (Brain)"), push.
   Then `git checkout feature/rl1-styles`, `git pull`.
1. In `callverse/quality/satisfaction.py`: `STYLES = ["short", "warm", "warm_next_step"]`. In `tests/test_satisfaction.py` (and anywhere else in
   `callverse/quality/` or its tests) replace `apology_first` / `apology_next_step` with the new names. `git grep -n "apology_first\|apology_next_step"`
   must return nothing outside old task/report files.
2. F's 14 tests + full suite green. Commit "RL1d: new style names in agent F", push `feature/rl1-styles`. **No merge.**
3. `git checkout feat/t14d-request-match`, put `tasks/NEXT.md` back to T14d IN PROGRESS (items 5–6 Monday), "Last done" = RL1d. Commit, push.
4. Reply in 3 lines: commit ids, test result, branch you are on.
