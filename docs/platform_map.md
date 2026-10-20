# Platform map — what exists today and what the platform still needs

Written for task P00 (read-only mapping). Date: 2026-10-20. Branch: `platform`.
Sources read: `docs/platform.md`, `docs/platform_contract.md`, `CLAUDE.md`, `README.md`, `config.yaml`,
all code under `callverse/`, `scripts/`, `tests/`, plus `docs/architecture.md` and
`docs/briefs_archive/BRIEF_02_policies_agentB_coordinator.md` (the older plan for agent B / Coordinator).

---

## 1. Repo layout (relevant parts only)

```
config.yaml              sim_today + providers + model chains
.env / .env.example      API keys (.env is git-ignored)
callverse/
  config.py              loads config.yaml, gives sim_today()
  llm.py                 shared LLM layer (Groq gpt-oss-120b -> gpt-oss-20b)
  trace.py               JSON-lines trace writer -> traces/<run_id>.jsonl
  data/seed.py           ShopNova schema + placeholder data -> data/shopnova.db
  tools/shopnova_tools.py  3 read tools + their JSON schemas
  tools/registry.py      allow-lists + run_tool() (the only way agents run tools)
  agents/base_agent.py   tool-calling loop shared by all agents
  agents/agent_a.py      Agent A - Status & Tracking
  kb/ coordinator/ queues/ notifier/ intake/ slm/ simulator/   empty packages (only __init__.py)
scripts/run_demo.py      one message -> Agent A -> printed answer + trace path
tests/                   conftest.py + 4 test files (no API key needed)
traces/                  run logs (git-ignored)
```

---

## 2. Existing pieces (one line each)

**ShopNova database**
- DB file: `callverse/data/shopnova.db`, path set in [seed.py:13](../callverse/data/seed.py#L13); git-ignored by `*.db` ([.gitignore:6](../.gitignore#L6)).
- Schema: [seed.py:15-47](../callverse/data/seed.py#L15-L47) — 4 tables:
  - `users(id, name, email, phone)`
  - `products(id, name, price, stock)`
  - `orders(id, user_id, items[JSON text], total, paid, status, order_date, promised_date, delivered_date, carrier, tracking_number)`
  - `refunds(id, order_id, amount, status)`
- Seed data: users [seed.py:54](../callverse/data/seed.py#L54) (5), products [seed.py:63](../callverse/data/seed.py#L63) (6), orders [seed.py:80-96](../callverse/data/seed.py#L80-L96) (10), refunds [seed.py:98-101](../callverse/data/seed.py#L98-L101) (1).
- `seed()` deletes and rebuilds the DB file every time: [seed.py:104](../callverse/data/seed.py#L104). Also called automatically by tools if the file is missing ([shopnova_tools.py:20-26](../callverse/tools/shopnova_tools.py#L20-L26)).
- AI-generated label today = a code comment only ([seed.py:49-52](../callverse/data/seed.py#L49-L52)); no column.

**Scripted orders 4505–4514 — all match the brief/contract** (checked by calling the real tools, `days_late` at sim_today 2026-10-09):

| Order | Client | Total / Paid (TND) | Status | Promised | Delivered | days_late | Brief says | OK |
|---|---|---|---|---|---|---|---|---|
| 4505 | Youssef | 34.50 / 34.50 | delivered | 09-15 | 09-14 | 0 | delivered | ✅ |
| 4506 | Amira | 189.00 / 189.00 | refunded (+ refunds row 189.00 `completed`) | 09-18 | 09-17 | 0 | already refunded 189 | ✅ |
| 4507 | Karim | 108.90 / 108.90 | delivered | 09-20 | 09-22 | 2 | delivered 2 days late | ✅ |
| 4508 | Leila | 74.90 / 74.90 | delivered | 09-23 | 09-23 | 0 | delivered | ✅ |
| 4509 | Sara | 39.80 / 39.80 | delivered | 09-25 | 09-24 | 0 | delivered | ✅ |
| 4510 | Youssef | 59.90 / 59.90 | shipped | 10-10 | — | 0 | shipped, on time | ✅ |
| 4511 | Amira | 54.40 / 54.40 | processing | 10-13 | — | 0 | processing | ✅ |
| 4512 | Sara | 59.90 / 59.90 | stuck at depot | 10-03 | — | **6** | main demo | ✅ |
| 4513 | Karim | 189.00 / 189.00 | shipped | 10-11 | — | 0 | shipped, on time | ✅ |
| 4514 | Leila | 89.00 / **0.00** | processing | 10-14 | — | 0 | cash on delivery, 0 paid | ✅ |

**Read tools** — [shopnova_tools.py](../callverse/tools/shopnova_tools.py)
- `get_user(email: str|None=None, phone: str|None=None, user_id: int|None=None) -> dict` — [line 41](../callverse/tools/shopnova_tools.py#L41); schema [line 99](../callverse/tools/shopnova_tools.py#L99) (no `required`, "give exactly one").
- `get_order(order_id: int) -> dict` — [line 58](../callverse/tools/shopnova_tools.py#L58); schema [line 114](../callverse/tools/shopnova_tools.py#L114) (`order_id` integer, required). Matches the contract §3 shape.
- `get_tracking(order_id: int) -> dict` — [line 64](../callverse/tools/shopnova_tools.py#L64); returns status, delivered, dates, `days_late`, carrier, tracking_number, `checked_on`; schema [line 126](../callverse/tools/shopnova_tools.py#L126).
- All return `{"error": ...}` when nothing is found; `SCHEMAS` dict [line 98](../callverse/tools/shopnova_tools.py#L98), `FUNCTIONS` dict [line 141](../callverse/tools/shopnova_tools.py#L141).

**Registry and allow-lists** — [registry.py](../callverse/tools/registry.py)
- All tools merged into `TOOL_FUNCTIONS` / `TOOL_SCHEMAS`: [registry.py:12-13](../callverse/tools/registry.py#L12-L13).
- Agent A allow-list = `get_user, get_order, get_tracking`: [registry.py:16](../callverse/tools/registry.py#L16); `ALLOW_LISTS = {"A": ...}` [line 18](../callverse/tools/registry.py#L18). No `B` yet.
- `schemas_for(agent)` sends the model only its allowed tools: [line 23](../callverse/tools/registry.py#L23).
- `run_tool(agent, name, args)` checks the list, refuses + traces `tool_refused` [lines 34-39](../callverse/tools/registry.py#L34-L39), catches exceptions as `{"error": ...}` [lines 41-44](../callverse/tools/registry.py#L41-L44), traces `tool_call` [line 46](../callverse/tools/registry.py#L46).

**Agent A and the LLM**
- `AgentA` class: [agent_a.py:39](../callverse/agents/agent_a.py#L39); prompt [agent_a.py:20](../callverse/agents/agent_a.py#L20); `[HANDOVER: B]` tag handling [agent_a.py:18](../callverse/agents/agent_a.py#L18), [agent_a.py:46](../callverse/agents/agent_a.py#L46).
- Loop: `BaseAgent.run()` [base_agent.py:45](../callverse/agents/base_agent.py#L45), calls `llm.chat("agents", ...)` [line 57](../callverse/agents/base_agent.py#L57), runs tools via `run_tool` [line 85](../callverse/agents/base_agent.py#L85), max 5 steps [line 17](../callverse/agents/base_agent.py#L17).
- `llm.chat(role_key, messages, tools)`: [llm.py:28](../callverse/llm.py#L28) — OpenAI SDK, models tried in order from config; falls back on 429/404/5xx/connection [llm.py:64](../callverse/llm.py#L64), not on 400.
- Model chain: [config.yaml:17](../config.yaml#L17) `openai/gpt-oss-120b`, [config.yaml:19](../config.yaml#L19) `openai/gpt-oss-20b`, both on Groq.

**Traces**
- `trace.log(step, actor, data)`: [trace.py:34](../callverse/trace.py#L34) — appends one JSON line `{time, run_id, step, actor, data}` to `traces/<run_id>.jsonl`.
- Steps used today: `llm_call`, `llm_skip`, `llm_fallback`, `tool_call`, `tool_refused`, `agent_start`, `agent_step`, `final_answer`, `step_limit`.
- Tool calls are recorded in `run_tool` with `{agent, tool, args, result}`.

**Config and keys**
- `load_config()` reads `config.yaml` once (cached): [config.py:15](../callverse/config.py#L15); `sim_today()` [config.py:21](../callverse/config.py#L21) reads `sim_today: "2026-10-09"` ([config.yaml:5](../config.yaml#L5)).
- `.env` loaded with `python-dotenv` at import of llm.py: [llm.py:21](../callverse/llm.py#L21). Key **names** are in `config.yaml` (`key_env`), values only in `.env`.
- `.env` is git-ignored: confirmed with `git check-ignore -v .env` → `.gitignore:2:.env`. Key values were not read or printed.

---

## 3. Test result

Command: `python -m pytest -q` (Python 3.12.5, repo root).
**Result: 14 passed / 14, 0 failed, 3.79 s.** (11 test functions; one is parametrized ×4.)
Files: `test_tools.py` (4), `test_registry.py` (2), `test_agent_loop.py` (3, fake LLM), `test_llm.py` (5, fake client).

Note: `tests/conftest.py:18` calls `seed()` on the **real** DB path before each test, so running the tests resets
`callverse/data/shopnova.db`. Harmless today; it will matter once the platform writes refunds/subscriptions.

---

## 4. Brief (`platform.md`) vs contract (`platform_contract.md`) differences

The contract wins in each case.

1. **`ai_generated` / `scripted` flags.** Brief requires them on generated / scripted data; contract §2 table
   columns do not include them. → Adding them as extra columns would not break the contract shapes, but it is not in the contract.
2. **Simulated clock.** Brief says "simulated clock starts here (2026-10-09)"; contract has no clock (only a fixed
   demo date and "emit events when an order status changes"). How the clock moves is not specified in either.
3. **`create_refund` signature vs `refunds` table (inside the contract itself).** Contract §4 gives
   `create_refund(order_id, amount, rule_id, proposal_id)`, but contract §2 `refunds(id, order_id, amount, status)`
   has no column to store `rule_id` or `proposal_id`. The brief does not name the write functions at all.
4. **Write-function names.** Contract names `create_refund` and `create_subscription(order_id, event)`; brief only
   describes them ("writes a refunds row ... a subscriptions row"). No conflict, contract is more precise.
5. **Policy-text wording.** Brief R-REF-03 "full refund"; contract "full refund on request". Brief R-DEL-02 "apologise
   and offer a notification"; contract same meaning. Brief adds the rule-format and key numbers (> 5 days, 14 days,
   300 TND, 3 events) — consistent with the contract.
6. **Layer 3.** Same numbers (> 300 to finance; approve ≤ 500, refuse above). Brief 02 (archive) adds "rule in config"; neither the brief nor the contract says where the 300/500 numbers live.
7. **CLAUDE.md line.** Brief asks to add "follow docs/platform.md"; CLAUDE.md already has a "Platform work" section that
   also says the contract wins. Consistent.
8. **Notifier location (archive only).** Brief 02 says `callverse/notifier.py`; the repo has a package `callverse/notifier/`. Not in the brief/contract, just noted.

No difference on: tables users/products/orders/refunds, tool shapes, agent IDs, scripted cases, currency, demo date, LLM models.

---

## 5. Gap list (ordered by what blocks the demo first)

### S1 — 4512 refund approved (R-REF-03, 59.90 TND)
1. **Policy file + loader** with the 8 rules (`id, title, text, condition`) — none exist. S1 needs at least R-REF-03, R-REF-05, R-ESC-01. (Search/RAG itself lives with the RAG code, not the platform.)
2. **`get_refunds(order_id)` read tool** — needed by the Coordinator ("not already refunded") and Agent B (contract allow-list in Brief 02). Missing.
3. **Allow-list `B`** in `registry.py` (read tools only). Missing. Agent B itself is not platform work.
4. **`create_refund(order_id, amount, rule_id, proposal_id)`** Coordinator-only write function, inserting a `refunds` row with status `approved`. Missing. Must **not** be added to `TOOL_FUNCTIONS` / any allow-list.
5. **`refunds` columns** for `rule_id`, `proposal_id`, `created_at` (traceability) — missing; needs a decision (see Q2).
6. **Labels**: `ai_generated` / `scripted` columns — missing on all tables.
7. **Write tracing**: write functions should log through the existing `trace.log` (e.g. step `db_write`). Not present yet.

### S2 — wrong amount sent back (R-REF-05), corrected, approved
8. Nothing new on the platform beyond S1: `orders.paid` exists; R-REF-05 condition `amount <= paid` needs the policy file (gap 1). Send-back logic is Coordinator work.

### S3 — delivery notification after advancing the clock (R-NOT-01)
9. **`subscriptions(id, order_id, event, status waiting|sent, created_at)` table** — missing.
10. **`events(id, order_id, event, at)` table** — missing.
11. **`create_subscription(order_id, event)`** Coordinator-only write, status `waiting` — missing.
12. **Simulated clock** — today `sim_today()` is a fixed, cached config value; nothing can advance it. Needs a way to move the date and/or an order's status (e.g. an `advance_clock` function/script).
13. **Status change → event**: a function that sets an order's status to `shipped` / `out_for_delivery` / `delivered` and inserts an `events` row. Missing. (The notifier that reads events and marks subscriptions `sent` is notifier work.)
14. **Order status vocabulary** — undefined. Today: `delivered, refunded, shipped, processing, stuck at depot` (with spaces); the contract events use `out_for_delivery` (underscores) and this status does not exist yet.
15. R-NOT-01 rule in the policy file (gap 1).

### Other (not blocking S1–S3)
16. **Layer 3 stub** (> 300 → finance; approve ≤ 500, refuse > 500) — missing. No scripted order goes above 300 TND paid (max is 189), so no demo case triggers it today.
17. Remaining policies R-DEL-01, R-DEL-02, R-RET-01, R-DMG-01 (in the same file as gap 1).
18. Test isolation: tests reset the real DB (see §3); platform write tests should use a temp DB.

---

## 6. Open questions for Yassine

1. **Flags**: add `ai_generated` and `scripted` as columns on `orders` (and `users`, `products`, `refunds`)? Are the 10 scripted orders `scripted = 1, ai_generated = 1` (written by AI for a script) or `ai_generated = 0`?
2. **`refunds` table**: may I add `rule_id`, `proposal_id`, `created_at` columns so `create_refund(order_id, amount, rule_id, proposal_id)` can store what it receives? (Contract shows 4 columns only.)
3. **Clock**: should the simulated date live in the DB (e.g. a `clock` table, so it can move) or stay in `config.yaml`? When the clock moves, `days_late` for 4512 grows (7, 8, ...) — is that wanted, or do we only change order statuses?
4. **Status names**: standardise on underscores (`stuck_at_depot`, `out_for_delivery`) or keep `stuck at depot`? Changing it touches the seed and maybe Agent A's answers.
5. **Refund status**: existing 4506 row is `completed`; new ones are `approved`. Keep both values?
6. **Where do write functions go**: e.g. `callverse/data/writes.py` (outside `tools/`, so agents can never reach them)? And Layer 3 numbers (300 / 500) in `config.yaml`?
7. **Process**: `tasks/NEXT.md` still shows T02 *IN PROGRESS* and does not list P00. I did P00 because you asked directly; NEXT.md was not changed. Should platform tasks be tracked in NEXT.md too?
