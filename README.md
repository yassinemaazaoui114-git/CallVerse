# CallVerse — prototype

CallVerse is a university data-science project: a **digital twin of a fully AI customer relation center**.
AI agents answer clients of a mock e-commerce company, **ShopNova**, using tools that read its database.
This repo is the **prototype** (proof of concept): it shows *why* each model, agent and rule is where it is.

## The prototype flow

```
Client Simulator → Intake → Queues (rules) → Agent A / Agent B → Coordinator (rules) → SLM → reply
```

- **Agent A** — Status & Tracking ("where is my order?"). **Agent B** — Payment & Refund.
- Agents only **read** data and **propose** actions. The **Coordinator** (plain rules, no LLM) checks
  each proposal and is the only part that changes data.
- More detail: [docs/architecture.md](docs/architecture.md).

## Setup (Windows, Python 3.12)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env          # then paste your API keys into .env (never commit it)
python -m callverse.data.seed   # creates the placeholder ShopNova database
python -m scripts.run_demo "Hi, where is my order 4512?"
python -m pytest -q             # run the tests
```

On macOS/Linux: `source .venv/bin/activate` and `cp .env.example .env`.
The demo re-seeds the database itself, so every run starts from the same data.
Each run writes a trace file in `traces/` (one JSON line per step).

## How we work: tasks

- `tasks/NEXT.md` says which task is next, its status and who approved it.
- Each task has a file `tasks/Txx_....md` (what to do, limits, checks). When it is done, the builder
  writes `tasks/Txx_report.md` and the task waits for review.
- Rules for the builder (Claude Code) are in [CLAUDE.md](CLAUDE.md).

## Folder map

```
README.md  CLAUDE.md  config.yaml  .env.example  requirements.txt  .gitignore
callverse/          the code
  config.py           reads config.yaml (models, sim_today)
  llm.py              one shared LLM layer for all agents (provider + backup chain from config.yaml)
  trace.py            writes every step to traces/*.jsonl
  data/               placeholder ShopNova database (seed.py)
  tools/              tool functions + per-agent allow-lists (registry.py)
  agents/             base agent loop + Agent A
  kb/ coordinator/ queues/ notifier/ intake/ slm/ simulator/   empty, filled by later tasks
scripts/            runnable entry points (run_demo.py)
tests/              pytest tests (no API key needed)
tasks/              NEXT.md, task files, reports
docs/               architecture.md, platform_contract.md, briefs_archive/
traces/             run logs (not in git)
```

## Status

**Runs today:** shared LLM layer (Groq `gpt-oss-120b`, backup `gpt-oss-20b`), placeholder database,
3 read tools (`get_user`, `get_order`, `get_tracking`), allow-list registry, Agent A, traces, tests.
Intake (branch `feature/intake`, T03): message → ticket with reasons, emotion, priority, style
(`python -m scripts.run_intake "<message>"`; first run downloads the local models, ~1 GB).

**Coming next:** Policy KB + search (RAG), Agent B, Coordinator, queue router, delivery notifications
(Brief #2) · SLM reply writer and Client Simulator (Brief #4).

## For the platform builder

What the agents expect from the ShopNova mock platform (tables, tools, policies):
[docs/platform_contract.md](docs/platform_contract.md).
