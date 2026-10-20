# T02 — Restructure the repo and push the skeleton to GitHub

## Why
So anyone in the team can clone the project, understand it from the README, and take a part.
Nothing about the system's behaviour changes.

## Hard limits
- Do **not** change what the code does. All tests must pass before and after.
- Never commit `.env`, `*.db`, `traces/`, `.venv/`, caches.
- Push only to `https://github.com/yassinemaazaoui114-git/CallVerse.git`, branch `main`. **No force push.**
- If the remote already has commits or files, **stop and ask** (do not merge or overwrite).

## What to do
1. Run the tests and the demo once; record the numbers (before).
2. Create `scripts/` and move `run_demo.py` there; make it run with `python -m scripts.run_demo "<message>"`
   (or `python scripts/run_demo.py`) — fix imports, update any references.
3. Move `briefs/*` to `docs/briefs_archive/`; delete the empty `briefs/` folder.
4. Create empty packages `callverse/queues/` and `callverse/notifier/` (each `__init__.py` with a one-line note:
   which task fills it).
5. Write `README.md` (short, plain English):
   what CallVerse is (3 lines) · the prototype flow · setup (venv, `pip install -r requirements.txt`,
   copy `.env.example` to `.env`, seed, run demo, run tests) · how tasks work (`tasks/NEXT.md`) ·
   folder map · "status: what runs today / what is coming".
6. Write `docs/architecture.md` (one page): flow, model map M1–M5, the 4 safety rules
   (proposals only, Coordinator executes, allow-lists, traces).
7. Keep `docs/platform_contract.md` (already written by the Brain) — link it from the README.
8. Check `.gitignore` covers everything in the hard limits.
9. Run tests and demo again (after).

## Checks (with numbers)
- Tests: same count passing before and after (write both numbers, e.g. 15/15 → 15/15).
- Demo `"Hi, where is my order 4512?"` answers "stuck at depot" and "6 days late".
- `git ls-files` contains **0** files matching `.env`, `*.db`, `traces/`, `.venv/`.
- After push: the GitHub repo shows the same file count as `git ls-files` (write the number).

## Time box and stop rule
45 minutes. If push needs a GitHub login, let Yassine sign in when Git asks. If it still fails, stop and report the error.

## Git (approved by Yassine, 2026-10-20)
- `git init`, default branch `main`, one commit: `"Skeleton: LLM layer, agent A, tools, traces, tests"`.
- Add remote `origin` = the URL above; check it is empty (`git ls-remote origin`); push `main`.
- Do **not** create other branches yet (the branch strategy is waiting for approval).
