# CallVerse — prototype

CallVerse is a university data-science project: a **digital twin of a fully AI customer relation center**.
AI agents answer the clients of a mock e-commerce company, **ShopNova** (electronics, Tunisia, prices in TND).
Agents only read data through tools and **propose** actions; plain rules decide and write.
This repo is the **prototype**: it shows *why* each model, agent and rule is where it is.
Everything runs on one PC: big LLMs through APIs (Groq), small models locally (Ollama, CPU models).

## How it works

A client message goes through these steps (each one is traced in `traces/`, one JSON line per step):

1. **Channel** — the ShopNova app's Help chat calls `callverse/channels/web_chat.py` (one ticket per chat, saved in
   CallVerse's own database `callverse/data/callverse.db`); scripts can also send a message directly.
2. **Intake** (no agent) — the reason by meaning (`BAAI/bge-small-en-v1.5`), emotion, sentiment, priority, the
   client's style and the order number; a small LLM only when the reason is unclear.
3. **Queues** (rules) — order status / late delivery → **Agent A** (Status & Tracking); refund / return / damaged
   item → **Agent B** (Payment & Refund). Agent A hands money requests over to B.
4. **Agents** (shared LLM `openai/gpt-oss-120b` on Groq) — read facts with their allowed tools only
   (`callverse/tools/registry.py`), find the company rule with the policy search (RAG), and submit a **proposal**.
5. **Coordinator** (rules, no LLM) — re-reads the facts, checks the cited rule, the refund limit and the client's
   confirmation, then approves (only then the platform writes), sends back, asks the client or escalates.
   Refunds above 300 TND need finance (Layer 3): a fixed rule by default, or the ShopNova admin in the app.
6. **Reply writer** (SLM `qwen2.5:1.5b`, local) — writes the reply from the Coordinator's decision only, in the
   client's style; a rule check and templates keep it correct.

More detail: [docs/architecture.md](docs/architecture.md). Models and switches: `config.yaml` (the only place to change them).

## Setup (Windows, Python 3.12)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env          # then put your own API keys in .env (it is git-ignored: never commit it)
python -m callverse.data.seed   # builds the ShopNova database (callverse/data/shopnova.db)
```

- **`.env`**: the variable names are in `.env.example` (`GROQ_API_KEY` for the agents; `GOOGLE_API_KEY` for the
  Gemini backup; `OPENROUTER_API_KEY` optional; `PLATFORM_COORDINATOR_TOKEN` only for the platform server's writes).
- **Ollama** (<https://ollama.com>) runs the local models. Pull them once:
  ```powershell
  ollama pull qwen2.5:1.5b        # the reply writer (SLM)
  ollama pull qwen2.5:3b          # its backup
  ollama pull qwen3.5:4b          # local test model for Intake's fallback + Agent A (used by the ShopNova app)
  ollama pull phi4-mini           # its backup
  # the app uses copies with an 8,192-token context (Ollama's default 4,096 can cut a prompt):
  Set-Content Modelfile.qwen "FROM qwen3.5:4b`nPARAMETER num_ctx 8192";  ollama create cv-qwen3.5-4b -f Modelfile.qwen
  Set-Content Modelfile.phi  "FROM phi4-mini`nPARAMETER num_ctx 8192";   ollama create cv-phi4-mini  -f Modelfile.phi
  ```
  The Intake models (embeddings, emotion, sentiment) download by themselves on the first run (about 1 GB).
- **Demo logins**, once, by yourself (only bcrypt hashes go into the git-ignored `config/accounts.yaml`):
  ```powershell
  python -m scripts.create_demo_accounts   # type a password twice per account, or Enter = random (shown once)
  ```
  Accounts (see `config/accounts.example.yaml`): `sara`, `youssef`, `amira`, `karim`, `leila` (ShopNova clients 1–5),
  `admin` (ShopNova admin), `supervisor` (CallVerse Console, T19).

## Start the apps

**ShopNova app** (the company's website, <http://127.0.0.1:8501>, this PC only). Start Ollama first, then:
- **Desktop shortcut**: run `powershell -ExecutionPolicy Bypass -File .\scripts\make_desktop_shortcut.ps1` once, then
  double-click **ShopNova** on the Desktop. It runs `ShopNova.bat`, which checks Ollama (if it does not answer, the
  window says "Start Ollama first, then run ShopNova again."), starts the app and opens the browser.
- Or double-click `ShopNova.bat`, or run `.\start_shopnova.ps1` in PowerShell (then open the address yourself).

What is in it: Shop (everyone; buying needs a login), My orders and Help chat (a logged-in client); as `admin` also
Admin dashboard, Manage (products, orders, users, refunds, admin log) and Refund approvals. In the app a refund above
300 TND waits for the admin (`CALLVERSE_LAYER3_MODE=queue`); the client gets the decision as a new reply.
Models in the app: Intake + Agent A + reply writer local, Agent B on Groq. The app does not watch its files: **after a
code change, restart it** (close the window or Ctrl+C, then start again).
Clean demo data: `python -m callverse.data.seed` and delete `callverse/data/callverse.db` (the tickets).

**Atlas Travel app** (the second company's website, <http://127.0.0.1:8503>, this PC only; T22). Start Ollama first.
- **Accounts, once**: `python -m scripts.create_demo_accounts`. It adds only the missing accounts (`hedi`, `sonia`,
  `tarek`, `lobna`, `nizar`, `atlas_admin`), asks a password for those only and keeps every existing password.
- **Desktop shortcut**: the same `make_desktop_shortcut.ps1` also makes **Atlas Travel** (runs `Atlas.bat`).
- Or double-click `Atlas.bat`, or run `.\start_atlas.ps1`.

What is in it: Home, My bookings and Help chat (an Atlas client); as `atlas_admin` Admin dashboard, Approvals and
Records (read only). A refund above 1,500 TND and every compensation wait in Approvals; each decision is logged in
`atlas.db` (`admin_actions`) in one transaction with the money. Every account has a company: a ShopNova account cannot
use the Atlas app, and an Atlas account cannot use ShopNova's. Same models as the ShopNova app; restart it after a code
change. Clean demo data: `python -m callverse.data.atlas.seed` and delete `callverse/data/callverse.db`.

**CallVerse Console** (the center's own screen, <http://127.0.0.1:8502>, this PC only; T19). Login: `supervisor`.
- **Desktop shortcut**: the same `make_desktop_shortcut.ps1` also makes **CallVerse Console** (runs `Console.bat`).
- Or double-click `Console.bat`, or run `.\start_console.ps1`. It loads **no model** (no Ollama needed).

What is in it (read only: it opens `callverse.db`, `shopnova.db` and `atlas.db` in SQLite read-only mode, it never writes):
**Live tickets** (every ticket of every company, newest first, filters, refreshed every 10 s; click a row),
**Ticket detail** (the conversation, then per message how CallVerse worked: Intake → route → tools and rule
searches → proposal → each Coordinator check ✅/❌ and the decision → Layer 3 → reply writer → writes; tokens by
model and seconds), **Agents** (one card per agent: tickets, proposals, approved / sent back / escalated, errors,
time, tokens, models) and **Dashboard** (tickets per day / company, % solved by the AI alone, % escalated, % sent to
finance, reply time and late replies > 30 s, finance decisions, TND paid per company, review score, tokens per ticket, system
tokens, Groq tokens used today out of 200,000). Times there are the computer's time (`*_real` columns, T19); the
company rules keep the simulation clock. Only real tickets from the apps are shown: chat in ShopNova first.
Dali's `/demo` page (platform server) is **replaced by the CallVerse Console**; its files will be removed after
Dali's OK.

**Platform server** (ShopNova's data and tools as a small web API, <http://127.0.0.1:8000>):
`python scripts/run_platform_server.py` — read-only dashboard at `/`, all endpoints at `/docs`. Writes stay off
unless `PLATFORM_COORDINATOR_TOKEN` is set. Details: [docs/platform_contract.md](docs/platform_contract.md) §8.

**Command line**: `python -m scripts.run_demo "Hi, where is my order 4512?"` (one message, all steps),
`python -m scripts.run_scenario S1` (demo stories S0–S4), `python -m scripts.run_notifier` (delivery messages),
`python -m scripts.quota_check` (one tiny call per model: is the free quota there before a long run?). Demo plan: [docs/DEMO_RUNBOOK.md](docs/DEMO_RUNBOOK.md).

## Run the tests

```powershell
python -m pytest -q --ignore=tests/data   # 1048 tests, about 2 minutes
```
No API key, no API call and no Ollama needed: the tests use fake LLMs and a fresh copy of the database.
`tests/data/` holds the held-out test sets: they are only for final evaluations, never for building or tuning.

## Benchmarks

Measured comparisons of models and methods, kept apart from the running system (`benchmarks/`). They never change
`config.yaml`: switching to a winner is a separate step (done in T24, see below).
- **M3 (T23)**: embeddings for Intake's reasons and for the rule search. Table, winners and locked-test numbers:
  [docs/benchmarks/M3.md](docs/benchmarks/M3.md). **T24:** bge-base won on the cloud machine but its Intake p95 on the demo PC
  (124-134 ms) is above the 100 ms limit, so M3 stays **bge-small** (pinned revision) with T23's tuned settings: `top_k` 5,
  thresholds ShopNova 0.69 / Atlas 0.54, and the BGE query prompt in rule search. Re-measure on the PC:
  `python -m benchmarks.m3.pc_check` (validation sets only). **T25:** the Colab fine-tuned models (`models/`, git-ignored)
  lost on validation (bge-small-ft: Atlas F1 and rule-search top-2 fall), so nothing changed in the system;
  scoring: `python -m benchmarks.m3.t25_score <bge-small|bge-small-ft|bge-base-ft|bge-small-lora|table>`.
  **T25b:** a LoRA adapter on bge-small (Intake only) also lost on validation (avg 0.642 < 0.667, Atlas 0.791 < 0.884); no change. Needs ABCD in `data/raw/abcd/abcd_v1.1.json` (see DATA_LICENCES.md).
  ```powershell
  python -m benchmarks.m3.build_data            # ShopNova validation set from ABCD dev
  python -m benchmarks.m3.embed_run bge-small   # one model at a time (bge-small, minilm, bge-base, embeddinggemma, qwen3-0.6b, reranker)
  python -m benchmarks.m3.benchmark             # scores on validation + the choice (benchmarks/m3/results/)
  python -m benchmarks.m3.locked_test           # the winners on the locked test sets, ONCE (already done)
  ```

## Folders

```
README.md  CLAUDE.md  config.yaml  .env.example  requirements.txt  DATA_LICENCES.md
ShopNova.bat  start_shopnova.ps1  Console.bat  start_console.ps1  Atlas.bat  start_atlas.ps1  start_demo.ps1
callverse/          the code
  config.py llm.py trace.py   settings (config.yaml), the one shared LLM layer, the trace
  companies.py        the companies of the center: each one's reasons, routes, rules, gate
  intake/             Intake: reasons, emotion, sentiment, priority, style
  queues/             the rule router and the priority queue
  agents/             Agent A, Agent B, the shared agent loop
  tools/              read tools, proposal tools, per-agent allow-lists (registry.py)
  kb/                 ShopNova's policies and the policy search (RAG); Atlas Travel's rules (policies_atlas.json)
  coordinator/        the Coordinator (rules); Atlas Travel's gate (atlas_coordinator.py: amounts by code)
  slm/                the reply writer, its rule check and templates
  notifier/           delivery notifications (story S3)
  data/               ShopNova data: seed, read views, the ONLY write functions (writes.py), clock, Layer 3
    atlas/            Atlas Travel data: schema, seed, database access, read functions, its write functions,
                      the Atlas app's read views (atlas_app_reads.py)
  tickets/ channels/  CallVerse's tickets database, the web chat channel, refund approvals
  console/            the Console's read-only queries (reads.py: all its SQL)
  auth/               demo logins, roles and permissions
  server/             the platform server (FastAPI)
  simulator/          Client Simulator (planned)
apps/shopnova/      the ShopNova Streamlit app (app.py, Home.py, pages/)
apps/console/       the CallVerse Console Streamlit app (app.py, pages/: Live tickets, Ticket detail, Agents, Dashboard)
apps/atlas/         the Atlas Travel Streamlit app (app.py, Home.py, pages/: My bookings, Help chat, Admin dashboard,
                    Approvals, Records)
config/             accounts.example.yaml (the real accounts.yaml is not in git)
scripts/            runnable entry points
benchmarks/m3/      the M3 embeddings benchmark (T23): code, validation data, results
tests/              pytest tests (tests/data: held-out sets)
tasks/              NEXT.md, task files, reports
docs/               design and contract documents
traces/             run logs (not in git)
```

## Data and licences

`callverse/data/shopnova.db` (rebuilt by `python -m callverse.data.seed`) holds two kinds of data, and every row says
which one it is (`source`, `ai_generated`, `scripted`):
- **Scripted** demo data written by hand (`seed.py`): clients 1–5, products 1–6, orders 4505–4515 (4512 = main demo,
  4515 = Layer 3 case). It never changes.
- **Real** data: 2,000 orders of the **Olist Brazilian E-Commerce dataset** (ids 10001+), with their real dates,
  statuses, payments (converted to TND) and review scores; names, emails, phones, product names and stock are generated.

Olist is licensed **CC BY-NC-SA 4.0**: source, credit line and changes in [DATA_LICENCES.md](DATA_LICENCES.md).
The raw files are never committed (`data/raw/`). `python -m scripts.data_summary` prints the counts.

**Atlas Travel** (the second sector: hotel stays and flights) has its own database, `callverse/data/atlas.db`, and goes
through the same center as ShopNova (T21): Intake, router, agents A / B, Coordinator, reply writer, tickets, Console.
Its website is the Atlas Travel app (T22, see above).
- **Real** data: 2,000 bookings of **Hotel Booking Demand** (CC BY 4.0, ids 20001+) and 2,000 flights of the
  **US DOT 2015 Flight Delays** (CC0, ids 1+), moved to 2026, prices in TND.

- **Generated:** one Tunisian user per booking (ids 101+) and one flight booking per flight (ids 30001+).
- **Scripted** demo data (`callverse/data/atlas/seed.py`): users 1–5, bookings 7001–7012, one for each rule case.
- Rules: `callverse/kb/policies_atlas.json` (ids `AT-…`). Profile: `callverse/data/atlas_profile.json`.

To rebuild: download `hotel_bookings.csv` (Kaggle `jessemostipak/hotel-booking-demand`) and `flights.csv`,
`airlines.csv`, `airports.csv` (Kaggle `usdot/flight-delays`) into `data/raw/atlas/`, then:
```powershell
python -m scripts.build_atlas_sample   # about 30 s: makes atlas_sample.json and atlas_profile.json (same bytes each run)
python -m callverse.data.atlas.seed    # builds atlas.db (also built by itself on first use)
```
The built sample is committed, so only the second command is needed, and the tests need no raw file.

What works for Atlas (T21): 8 reasons of its own, booking status and delay questions (Agent A), refunds, compensation
and hotel cancellation (Agent B). The company comes from the channel, never from the text. Agents propose without any
amount: the Coordinator computes it from the rules, and it decides by code whether the client asked (T22: that decision
and its reason are stored on the proposal, next to the agent's own flag, and shown in the Console and in Approvals). A
refund above 1,500 TND and every compensation wait for finance (Approvals page, `approvals.decide`); rebooking and
special assistance go straight to a colleague until agent C exists.

**ABCD** (ASAPP, MIT) is used only by the M3 benchmark (T23), never by the running system; credit in DATA_LICENCES.md.

## Task history

How we work: `tasks/NEXT.md` says which task is next; each task has a file `tasks/Txx_*.md` and a report
`tasks/Txx_report.md`. Rules for the builder (Claude Code): [CLAUDE.md](CLAUDE.md).

- **T01** Core: shared LLM layer, placeholder ShopNova database, read tools, allow-lists, Agent A, traces.
- **T02** Repo restructured and the skeleton pushed to GitHub.
- **T03** Intake: reasons by meaning, emotion, sentiment, priority, style.
- **T04** Pipeline: Intake → rule router → Agent A (handover to B); T04a joined the platform and Intake into `main`.
- **T05** Reply writer (SLM) with Ollama; T05b exact key sentences, calm opener, temperature 0.
- **T06** Policy search (RAG) and Agent B (refund proposals).
- **T07** Coordinator (rules; stories S1, S2, Layer 3) and the rate-limit fallback.
- **T08** Coordinator joined to the reply writer: one correct, polite reply per client.
- **T09** Story S3: delivery notification (subscription, simulation clock, notifier).
- **T10** Live-typing test (whatever is typed in front of the teacher); T10b finished it on this PC + demo runbook.
- **T11** Demo tools merged into `main`.
- **T12** Unseen live-typing test, run once.
- **T13** Local test models for the agents; T13b context benchmark; T13c stricter checker and safety net; T13d RAG
  check; T13e small SLM test; T13f reply writer switched to `qwen2.5:1.5b`.
- **T14** Reserved for core fixes (e.g. the cancellation rule, a second question in the same chat): not done yet.
- **T15** ShopNova on real data: 2,000 Olist orders.
- **T16** Agent B gets its own model setting (Groq), so refunds work while the rest runs locally.
- **T17** ShopNova app, part 1: tickets, web chat channel, logins, Shop, My orders, Help chat.
- **T18** ShopNova app, part 2: Admin dashboard, Manage, Refund approvals (the real Layer 3 queue).
- **T19** CallVerse Console: Live tickets, Ticket detail, Agents, Dashboard (read only); computer-time columns and
  reply seconds in `callverse.db`; new ticket status "Escalated"; replaces Dali's `/demo` page.
- **T20** Atlas Travel's company data on real datasets (hotels + flights): its own database, rules `AT-…`, profile,
  read functions (no app or agent yet).
- **T21** Routing by company, part A: Atlas Travel through the same center (own reasons, agents' prompts and tools,
  rule search, amounts by code, writes, approvals); ShopNova unchanged.
- **T22** Routing by company, part B: the Atlas Travel app (My bookings, Help chat, Admin dashboard, Approvals, Records),
  accounts with a company, Atlas admin log, the code's confirmation decision stored and shown.
- **T23** Benchmark of M3 (embeddings) for Intake reasons and rule search, on ABCD + Brain's sets, chosen on validation,
  locked test once: winner bge-base-en-v1.5 for both jobs (not switched yet; [docs/benchmarks/M3.md](docs/benchmarks/M3.md)).

The platform lane (Dali) has its own tasks `tasks/P01`–`P09b` (data and writes, Layer 3, server, clock, demo screen).

## Docs

- [docs/architecture.md](docs/architecture.md) — the architecture and why each part is there
- [docs/platform_contract.md](docs/platform_contract.md) — tables, tools, policies, Layer 3, server (the reference)
- [docs/platform.md](docs/platform.md), [docs/platform_map.md](docs/platform_map.md),
  [docs/platform_P01_P02_summary.md](docs/platform_P01_P02_summary.md) — the platform builder's notes
- [docs/decision_format.md](docs/decision_format.md) — what the Coordinator gives the reply writer
- [docs/ui_design.md](docs/ui_design.md) — the ShopNova app and the Console (design)
- [docs/DEMO_RUNBOOK.md](docs/DEMO_RUNBOOK.md) — how to run the demo
- [docs/benchmarks/M3.md](docs/benchmarks/M3.md) — the M3 embeddings benchmark (T23): table, winners, locked test
- [DATA_LICENCES.md](DATA_LICENCES.md) — data sources and licences
