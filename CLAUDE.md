# CallVerse — rules for Claude Code (the Builder)

## Roles (Brain–Builder workflow)
- **Brain** = Claude in the PIDS chat: plans, writes task files, reviews reports.
- **Builder** = you, Claude Code: build exactly the current task, then report.
- **Approver** = Yassine: approves every task before you start it.

When Yassine types **"Do the next task"**:
1. Open `tasks/NEXT.md`. Work only if Status is **READY** and "Approved by" is filled. Otherwise stop and say why.
2. Set Status to **IN PROGRESS**, open the task file it names, and do exactly that task.
3. Write `tasks/Txx_report.md` (format below), then set Status to **WAITING FOR REVIEW**.

## What CallVerse is
A university data-science project: a digital twin of a fully AI customer relation center.
This repo is the **prototype** for the next validation. The teacher grades **architectural reasoning**
("why is this model / agent / rule here?"). Yassine must understand every file: write simple, commented code.

## Locked decisions (do not change)
- Prototype flow: Client Simulator → Intake → Queues (rules) → Agent A / Agent B → Coordinator (rules) → SLM → reply.
- Company: **ShopNova** (mock e-commerce). Data and policies come from the teammate's platform; until ready,
  placeholder data with the **same structure** (`callverse/data/seed.py`).
- Out of scope for the prototype: agents C, D, E, F, fallback mode, fine-tuning, benchmarking.
- Models, switchable in `config.yaml` only:
  M2 agents' shared LLM = `openai/gpt-oss-120b` on Groq (backup `openai/gpt-oss-20b`);
  M1 simulator = an API model of a **different family** (Gemini Flash);
  M3 embeddings = `BAAI/bge-small-en-v1.5` (local CPU);
  M4 classifiers = ready-made emotion/sentiment models (chosen later);
  M5 SLM = small local model 1–4B via Ollama (chosen later). Max 6 GB VRAM: big LLMs only via API.
- **Agents never act directly.** Read tools only within the agent's allow-list; action tools only create a
  **proposal**; only the **Coordinator** (rules, no LLM) executes after its checks.
- **Facts come from tools**, never from model memory. Allow-list per agent, enforced in code (`tools/registry.py`).
- **Every step is traced** (JSON lines in `traces/`). One shared LLM layer (`callverse/llm.py`).
- Fixed demo date: `sim_today` in `config.yaml` (2026-10-09).

## Hard rules
1. **Git — free on your own branch, protected on `main`.** Any teammate may, without asking:
   `git fetch` / `git pull`, create their own branch from the latest `main`, commit on it, and push it.
   Still **forbidden without the owners' approval** (Yassine + the branch owner): merging into `main`,
   pushing to `main`, force push, rebase or reset of a shared branch, deleting branches, rewriting history.
2. **Never tune or choose anything on test data.** Keep test sets separate from examples used for building.
3. **No secrets in files.** Keys only in `.env` (git-ignored). Never print or copy keys.
4. **Stop and ask** in the report if something is unclear, contradicts this file, or needs a decision.
5. Do only the current task. No extra features, no architecture changes, no new libraries unless the task allows them.
6. Respect the task's **time box**; when it runs out, stop and report what is done and what is left.
7. Keep all tests passing. Explain new files in simple words.
8. At the end of every task, update README.md with what changed (only what is necessary).

## Git and branches
- `main` must always work (tests pass, demo runs). It only changes through a reviewed merge.
- One branch per part or task, from the latest `main`: `feature/<part>` (e.g. `feature/agent-b`, `feature/voice`, `platform`).
- Pull, commit and push **your own branch** freely; merge into `main` only after the Brain's review and the owners' OK.
- Lanes: Yassine (core) "Do the next task" → `tasks/NEXT.md`; Dali (platform) "Do the next platform task" →
  `tasks/NEXT_PLATFORM.md`; Semah (voice) "Do the next voice task" → `tasks/NEXT_VOICE.md`.

## Report format — `tasks/Txx_report.md`
1. **In plain words** — 3–5 sentences a non-programmer understands.
2. **Done** — list of what was built or changed.
3. **Evidence** — numbers and file paths (tests passed/total, demo output, timings, counts).
4. **Problems** — what went wrong or is fragile.
5. **Questions for the Brain** — decisions you need.
6. **Next step** — what you suggest next.

## Folder layout
```
README.md  CLAUDE.md  config.yaml  .env.example  requirements.txt  .gitignore
callverse/     code: llm, config, trace, data, tools, agents, kb, coordinator, queues,
               intake, slm, simulator, notifier
scripts/       runnable entry points (run_demo.py, ...)
tests/
tasks/         NEXT.md, Txx task files, Txx reports
docs/          architecture.md, platform_contract.md, briefs_archive/
traces/        run logs (git-ignored)
```

## Platform work
Platform tasks (mock company DB, policies, write tools, clock, Layer 3 stub) are files `tasks/Pxx_*.md`.
Follow `docs/platform.md`; `docs/platform_contract.md` wins if they disagree.
When Dali types **"Do the next platform task"**: open `tasks/NEXT_PLATFORM.md` (not `tasks/NEXT.md`) and follow the
same rules as above (Status READY, "Approved by" filled, write the Pxx report, set WAITING FOR REVIEW).
