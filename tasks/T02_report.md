# T02 report — Restructure the repo and push the skeleton to GitHub

## 1. In plain words
The project is now on GitHub, so every teammate can download it and start from the same files.
I tidied the folders (the demo script moved to `scripts/`, old briefs moved to `docs/briefs_archive/`) and
added two empty folders for parts that come next (queues and notifier). I wrote a README that explains
what CallVerse is and how to run it, and a one-page architecture document. Nothing about how the system
behaves has changed: the same tests pass and the demo gives the same answer.

## 2. Done
- `run_demo.py` → `scripts/run_demo.py` (+ `scripts/__init__.py`). New command:
  `python -m scripts.run_demo "<message>"`. Only the usage line in its docstring changed; no import fix was
  needed (the script already imported `callverse...`, and all file paths in the code are relative to the code files).
- `callverse/trace.py`: comment updated to the new script path (comment only).
- `briefs/*` → `docs/briefs_archive/` (2 files); empty `briefs/` deleted. Archived briefs left unchanged
  (BRIEF_01 still mentions the old `run_demo.py` path; it is a historical document).
- New empty packages `callverse/queues/` and `callverse/notifier/`, each with a one-line note
  (both filled by the Brief #2 task).
- New `README.md`: what CallVerse is, flow, setup, tasks workflow, folder map, status, link to
  `docs/platform_contract.md`.
- New `docs/architecture.md`: flow (with why + status per step), model map M1–M5, the 4 safety rules.
- `.gitignore` checked: already covers `.env`, `*.db`, `traces/`, `.venv/`, `__pycache__/`, `.pytest_cache/`. No change.
- Git: `git init -b main`, remote `origin` added, remote checked empty, one commit `fb187b5`
  "Skeleton: LLM layer, agent A, tools, traces, tests", pushed to `main` (no force, no other branch).

## 3. Evidence
| Check | Before | After |
|---|---|---|
| Tests (`python -m pytest -q`) | **14/14** passed | **14/14** passed |
| Demo `"Hi, where is my order 4512?"` | "stuck at the depot" + "6 days late" (tools: get_tracking, 2 steps) | "stuck at the depot" + "6 days late" (tools: get_order, get_tracking, 3 steps) |

- Demo command before: `python run_demo.py ...`; after: `python -m scripts.run_demo ...`.
- Traces: `traces/run_20261020_160605_709506.jsonl` (before), `traces/run_20261020_160740_137788.jsonl` (after).
- `git ls-remote origin` before push: empty (no refs).
- `git ls-files`: **39** files; files matching `.env`, `*.db`, `traces/`, `.venv/`, caches: **0**.
- Scan of staged files for API-key patterns (Groq, OpenRouter, Google, OpenAI): **0** matches.
- After push: GitHub `main` tree has **39** files (GitHub API, not truncated) = `git ls-files` (39).
  Remote `refs/heads/main` = `fb187b5`.
- Time: about 10 minutes (time box 45).

## 4. Problems
- The demo's wording and tool choice differ between runs (the LLM is not deterministic). The facts were the same both times.
- `tasks/T02_report.md` (this file) and the final `tasks/NEXT.md` status are **not** in the commit: only one
  commit was approved, and the report needs the push results. On GitHub, `NEXT.md` still shows "IN PROGRESS".
- Git warned that LF line endings will become CRLF in the Windows working copy (`core.autocrlf`).
  This is harmless, but teammates on macOS/Linux may see line-ending noise. A `.gitattributes` file would fix it (not added: outside the task).
- Only `python -m scripts.run_demo` works. `python scripts/run_demo.py` gives "No module named callverse"
  because Python then searches `scripts/`, not the repo root. The task allowed either form; the README uses the `-m` form.

## 5. Questions for the Brain
1. Brief #2 names the notifier as one file, `callverse/notifier.py`. T02 and CLAUDE.md want a package,
   `callverse/notifier/`. Both cannot exist under that name. The Brief #2 task file should say e.g.
   `callverse/notifier/notifier.py`.
2. Should the report and the status update for T02 be pushed in a second commit, and from now on, should each
   task end with one commit that includes its report?
3. Add a `.gitattributes` (`* text=auto eol=lf`) in a later task?

## 6. Next step
Approve the branch strategy, then the Brief #2 task (Policy KB + RAG, Agent B, Coordinator, queue router,
notifications), including the notifier path from question 1.
