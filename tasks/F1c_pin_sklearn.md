# F1c — Pin scikit-learn for agent F, then hand back to T14d

## Why
F1b passed (approved by Yassine 1 Nov 16:15, all ⭐): run accepted as is; pin scikit-learn so the model file always loads;
then Yassine merges `review/agent-f` into main. Tiny task, no Groq, no merge by you.

## Hard limits
Never read `.env`; no secrets; never commit `models/` or `data/raw/`; no force push / rebase / reset; no merge into main.

## What to do
0. You are on `feat/t14d-request-match` with `tasks/NEXT.md` changed and this file new (written by the Brain). Commit both there
   ("NEXT: F1c (Brain)"), push.
1. `git checkout review/agent-f`, `git pull`. In `requirements.txt` change the scikit-learn line to `scikit-learn>=1.9.1,<1.10`
   (keep its comment). Run F's 14 tests with the `.venv` python. Commit "F1c: pin scikit-learn for agent F", push. **No merge.**
2. `git checkout feat/t14d-request-match`. Put `tasks/NEXT.md` back to T14d exactly as it was before step 0 (Status IN PROGRESS,
   the T14d task file, items 5–6 on Monday) with "Last done" = "F1c — scikit-learn pinned on review/agent-f (ready for Yassine's merge)".
   **Delete the "Model" row** (Yassine's rule: no model names in NEXT.md). Commit, push.
3. Reply in 3 lines: commit ids, test result, branch you are on.
