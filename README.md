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
Intake (T03): message → ticket with reasons, emotion, priority, style
(`python -m scripts.run_intake "<message>"`; first run downloads the local models, ~1 GB).
Pipeline (T04): Intake → rule router → Agent A or B (refund/return/damaged cases go to B),
priority queue (`python -m scripts.run_pipeline "<message>"` or `--batch`).
Policy search + Agent B (T06): `search_policy` finds rules by meaning (M3, `callverse/kb/search.py`);
Agent B (Payment & Refund) asks Agent A for delivery facts, cites the rule and submits a refund
**proposal** (`propose_refund`, nothing paid). Route B now runs Agent B. Held-out check:
`python -m scripts.eval_policy_search` (final evaluation only).
Coordinator (T07): rules only, no LLM (`callverse/coordinator/coordinator.py`). It re-reads the facts,
checks the cited rule, R-REF-05, the client's confirmation and Layer 3 (> 300 TND), then approves (only then
the platform writes), sends back (max 2, the agent corrects), asks the client, or escalates. Scenarios:
`python -m scripts.run_scenario S0|S1|S2|S4`. The LLM layer waits on short rate limits and falls back
gpt-oss-120b → gpt-oss-20b → Gemini Flash (force one with `CALLVERSE_FORCE_AGENTS_MODEL=<model>`).
Model switches (T16, temporary test setup until the M2 benchmark): Agent B has its own list `models.agent_b`
(Groq gpt-oss-120b → gpt-oss-20b, no Gemini), used by its turns and by its "ask Agent A" sub-call.
`CALLVERSE_AGENTS_SET=local` moves Intake's LLM fallback and Agent A to the local test models but **not** B;
`CALLVERSE_AGENT_B_SET=local` moves B too (`agent_b_local` = the same list as `agents_local`).
`CALLVERSE_FORCE_AGENT_B_MODEL=<model>` forces B's model; `CALLVERSE_FORCE_AGENTS_MODEL` no longer affects B.
No switch = A and B on Groq, as before.
Final reply (T05 + T08): the SLM (`qwen2.5:3b` via Ollama, `callverse/slm/writer.py`) writes the user's reply
from the Coordinator's decision only (`must_say`, `next_step`, facts), in the client's style; a rule check
and templates keep it safe. The agent's own text stays in the trace. Without Ollama the template answers.

Delivery notification (T09, story S3): Agent A proposes `propose_subscription` when the client asks to be
told; the Coordinator approves (R-NOT-01) and the platform records it; after the simulation clock moves
(`callverse/data/clock.py`), the notifier (`callverse/notifier/notifier.py`, `python -m scripts.run_notifier`)
sends one message per subscription. `python -m scripts.run_scenario S3` plays the whole story.

**Coming next:** Client Simulator (Brief #4).

## Data

The ShopNova database (`callverse/data/shopnova.db`, rebuilt by `python -m callverse.data.seed`) holds two kinds of data
(T15). Every row has labels so it is always visible what is real and what is AI-generated:

- **Scripted** (`source = 'scripted'`, `ai_generated = 1`): the hand-written demo data in `seed.py` — users 1–5,
  products 1–6, orders **4505–4515** (`scripted = 1`; 4512 = main demo, 4515 = Layer 3 case) and the 4506 refund.
  It must never change.
- **Real** (`source = 'olist'`): **2,000 real orders** (ids 10001+) of the Olist Brazilian E-Commerce dataset
  (CC BY-NC-SA 4.0, see `DATA_LICENCES.md`), with their real dates, statuses, payments (converted to TND) and review
  scores, moved into the 90 days before the demo date. Olist has no names, so client names, emails, phones, product
  names, stock, carriers and tracking numbers are generated (`ai_generated = 1` on users and products; see
  `docs/platform_contract.md` §2 for every column). Refunds only where the real data shows a late delivery and a
  1–2 star review (`source = 'generated'`).
- How to rebuild the real sample: download the Kaggle dataset `olistbr/brazilian-ecommerce` by hand into
  `data/raw/olist/` (never committed), then `python -m scripts.build_shopnova_sample` (fixed seed: same file every time).
- The company profile (`callverse/data/company_profile.json`) and the policy texts are AI-written
  (`ai_generated: true`); its `sells` and `delivery_promise_days` come from the real sample.
- Rows created while the system runs (refunds, subscriptions, events) get `0 / 0` and `source = NULL`.

`python -m scripts.data_summary` prints the counts per table, per status, and how many rows are generated or scripted.

## Run the platform server

The ShopNova platform can run as a small web server **on this PC only** (`127.0.0.1`, not reachable from the network):

```powershell
python scripts/run_platform_server.py
```

- Dashboard (read-only): <http://127.0.0.1:8000/> — company profile, orders with AI-generated / scripted labels,
  policies, refunds, subscriptions, events and the last trace lines.
- All endpoints: <http://127.0.0.1:8000/docs> (FastAPI's API page). Agents call tools with `POST /tools/{name}`,
  which checks their allow-list.
- Writes (`/coordinator/*`, `/layer3/decide`, `/admin/reset`) are **off** unless you put a value in
  `PLATFORM_COORDINATOR_TOKEN` in `.env` and send it in the `X-Coordinator-Token` header.
- Demo through the HTTP endpoints, no second terminal needed: `python scripts/demo_platform_http.py`.

Details: [docs/platform_contract.md](docs/platform_contract.md) section 8.

## For the platform builder

What the agents expect from the ShopNova mock platform (tables, tools, policies):
[docs/platform_contract.md](docs/platform_contract.md).
