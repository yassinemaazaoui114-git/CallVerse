# Platform contract — ShopNova (for the platform builder)

What the CallVerse agents expect from the ShopNova mock platform. Keep these names and shapes
so the agents work without code changes. All amounts in **TND**. Demo date: **2026-10-09**.

## 1. What already runs (prototype repo)
Shared LLM layer (Groq `gpt-oss-120b`, backup `gpt-oss-20b`), placeholder SQLite database
(`callverse/data/seed.py`), 3 read tools, per-agent allow-lists, Agent A, traces, tests.
Not built yet: policies + search, Agent B, Coordinator, notifications, Intake, SLM, Simulator.

## 2. Tables (same structure as the placeholder)
Schema in `callverse/data/seed.py`. Every table also has two labels (0/1):
`ai_generated` (fictional data written by an AI: all seed rows) and `scripted` (a demo case that must stay
exactly as it is: the 11 scripted orders 4505–4515 and the 4506 refund). Generated data (20 users ids 6–25,
120 orders ids 5001–5120 and their refunds) is `ai_generated = 1, scripted = 0`, built with a fixed random seed
(identical on every rebuild). Rows written at run time get `0 / 0`. Company profile: `callverse/data/company_profile.json`.
- `users(id, name, email, phone)`
- `products(id, name, price, stock)`
- `orders(id, user_id, items[JSON], total, paid, status, order_date, promised_date, delivered_date, carrier, tracking_number)`
  - `status` codes: `processing`, `shipped`, `stuck_at_depot`, `out_for_delivery`, `delivered`, `refunded`, `cancelled`
  - allowed moves: `processing → shipped → out_for_delivery → delivered`, `shipped → stuck_at_depot`,
    `stuck_at_depot → out_for_delivery`,
    any status → `cancelled` or `refunded` (staying on the same status is refused)
- `refunds(id, order_id, amount, status, rule_id, proposal_id, created_at)`
  - `status`: `approved` (written by the Coordinator), `completed` (paid out, e.g. 4506), `refused`
- `subscriptions(id, order_id, event, status waiting|sent, created_at, proposal_id)` — `proposal_id` = the approved
  `subscribe` proposal it came from
- `events(id, order_id, event, at)` — one row each time an order reaches a notification event
- Notification events (= R-NOT-01): `shipped`, `out_for_delivery`, `delivered`.
- `proposals(id TEXT 'P-0001', agent, action, params JSON, rule_id, facts_used JSON, user_confirmed 0|1, decision,
  decision_reason, created_at, decided_at)` — audit of every agent proposal and the Coordinator's decision.
  `decision`: `NULL` (not decided yet) or `approve | send_back | ask_user | ask_proof | layer3 | escalate`.
  `refunds.proposal_id` refers to `proposals.id` (seed refunds predate the system and have `NULL`).
- Dates are ISO `YYYY-MM-DD`; run-time writes and the generated seed data use the fixed demo date
  (`sim_today` in `config.yaml`, read through `callverse/config.py`; written in one place only).

## 3. How agents call tools
Plain Python functions + OpenAI-style JSON definitions (function calling). No LangChain.
Each call passes through a registry that checks the agent's allow-list.

```python
get_order(order_id: int) -> dict        # the order, or {"error": "..."}
```
```json
{"type": "function", "function": {"name": "get_order",
  "description": "Get a ShopNova order: items, total, amount paid, status, dates, carrier, tracking number.",
  "parameters": {"type": "object", "properties": {"order_id": {"type": "integer"}}, "required": ["order_id"]}}}
```
Read tools today: `get_user(email|phone|user_id)`, `get_order(order_id)`, `get_tracking(order_id)` (adds `days_late`
and `days_since_delivery` = sim_today − delivered_date, `null` if not delivered; used by R-RET-01),
`get_refunds(order_id)` → `{"order_id": 4512, "refunds": [rows], "refunded_total": 0.0}`; `refunded_total` = sum of
refunds with status `approved` or `completed` (`refused` does not count). Unknown order → `{"error": ...}`. On no allow-list yet.
`get_company_profile()` → the dict in `callverse/data/company_profile.json` (name, domain, description, sells,
cities_served, carriers, delivery_promise_days, currency, payment_methods, support_channels, support_languages,
ai_generated); missing/broken file → `{"error": ...}`. On no allow-list yet.

## 4. How the Coordinator approves (to be built)
`review(proposal)` → `approve | send_back | ask_user | ask_proof | layer3 | escalate`.
On **approve**, only the Coordinator writes: a `refunds` row with status `"approved"`, or a `subscriptions`
row with status `"waiting"`.

Write functions — `callverse/data/writes.py`, **outside** `tools/`, never in the registry or any allow-list.
Each returns the new row (dict) or `{"error": ...}` (never raises) and writes a trace line
(`db_write` or `db_write_refused`). Amounts must be a finite number > 0: NaN, infinity, `True`/`False` and text
are refused (`json.loads` accepts `NaN`, so a tool argument could carry it). They check data (order exists, valid codes) plus two safety nets that hold even
if the Coordinator has a bug; the other policy checks are the Coordinator's.
```python
record_proposal(proposal) -> {"id": "P-0001"} | {"error"}      # proposals row, not decided yet; always a dict
record_decision(proposal_id, decision, reason) -> dict          # updated proposals row; a proposal is decided
                                                                # once (corrected proposal = new proposal)
create_refund(order_id, amount, rule_id, proposal_id) -> dict   # refunds row, status "approved";
                                                                # refused unless proposal_id is a recorded proposal:
                                                                # decided "approve", action "refund", params.order_id
                                                                # = order_id, round(params.amount, 2) = round(amount, 2),
                                                                # not used before for a refund;
                                                                # refused if amount > paid - refunded_total
                                                                # or amount not a finite number > 0
mark_subscription_sent(subscription_id) -> dict                 # subscriptions row now "sent"; refused if not "waiting"
create_subscription(order_id, event, proposal_id) -> dict       # subscriptions row, status "waiting";
                                                                # refused if event not in R-NOT-01, or unless
                                                                # proposal_id is a recorded proposal: decided
                                                                # "approve", action "subscribe", params.order_id =
                                                                # order_id, params.event = event, not used before
set_order_status(order_id, new_status) -> dict                  # {"order_id","old_status","new_status","event"}
```
`set_order_status` refuses unknown status codes and moves outside the allowed list (§2); when the new status is a notification event it inserts one
`events` row (returned as `event`, else `None`); `delivered` also fills `delivered_date` if empty.
Demo S3 control: `python -m scripts.advance_status --order 4512 --status out_for_delivery`.

**Coordinator order for a write**: `record_proposal` → checks (facts re-read, policy, user confirmation) →
`record_decision` → if `approve`, `create_refund(..., proposal_id)` or `create_subscription(..., proposal_id)`.
The write must match **exactly** what was approved (P07): an approval for 10.00 TND cannot pay 378.00 TND (which would
also skip Layer 3), and a `subscribe` approval cannot pay a refund. Proposal shapes:
refund `{"action": "refund", "params": {"order_id", "amount"}}` · subscription `{"action": "subscribe", "params": {"order_id", "event"}}`. Above 300 TND: `layer3_decide` first; if finance
approves, the Coordinator records `approve`. `proposal` = `{agent, action, params, rule_id, facts_used, user_confirmed}`
(other keys such as `user_quote` are ignored; `params`/`facts_used` must be JSON-safe, so no NaN).

Read-only helpers (not tools, on no allow-list):
```python
reports.get_pending_notifications() -> [{"subscription_id", "order_id", "event", "event_at",
                                         "user": {"id", "name", "email", "phone"}}]
# events that match a "waiting" subscription (same order + event, on/after the day it was created), one per subscription
simulator_data.read_own_case(order_id) -> {"order_id", "user": {"name", "email"}, "items", "status",
                                           "promised_date", "days_late", "paid"}   # what the client knows; not over HTTP
simulator_data.list_scenario_cases() -> [{"order_id", "scenario", "description"}]  # not over HTTP
# 4512 late_refund · 4506 already_refunded · 4510 on_time · 4507 damaged · 4515 layer3
```

## 5. Policies — `callverse/kb/policies_shopnova.json`, loaded by `load_policies()` in `callverse/kb/policies.py`
Format per rule: `id`, `title`, `text` (what agents read), `condition` (what the Coordinator checks in code).
`check_condition(condition, facts) -> bool` evaluates a condition without `eval()` (names from `facts`,
comparisons, `and/or/not`, `+ -`, lists); a missing fact or anything else raises `ValueError`.
Order status moves are not a policy: they live in `STATUS_MOVES` (`seed.py`, §2), now including `shipped → stuck_at_depot`.
Facts used by the conditions: `days_late`, `delivered`, `amount`, `paid`, `refunded_total`, `days_since_delivery`,
`proof_received`, `event`.
Rules the prototype needs (draft): R-DEL-01 delivery promise · R-DEL-02 late 1–5 days: apologise + offer
notification · R-REF-03 late > 5 days and not delivered: full refund on request · R-REF-05 refund ≤ amount paid minus past refunds (`amount <= paid - refunded_total`) ·
R-RET-01 returns within 14 days · R-DMG-01 damaged item: photo proof · R-ESC-01 refunds > 300 TND need
finance (Layer 3) · R-NOT-01 notifications for shipped, out_for_delivery, delivered.

## 6. Scripted cases (placeholder data)
4512 Sara, 59.90 TND paid, promised 2026-10-03, stuck at depot, 6 days late (main demo) · 4506 already
refunded (189 TND) · 4507 delivered 2 days late · 4510, 4513 shipped on time · 4511 processing ·
4514 cash on delivery (0 paid) · 4505, 4508, 4509 delivered · **4515** Layer 3 case: user 2, 2 × Smart Watch,
378.00 TND paid, promised 2026-10-01, stuck_at_depot, 8 days late (full refund > 300 TND → finance approves ≤ 500).

## 7. Other settings
Layer 3 stub: refunds > 300 TND go to finance (R-ESC-01 condition); stub approves ≤ 500 TND, refuses above
(`layer3.stub_max_approve_tnd` in `config.yaml`).
```python
layer3_decide(order_id, amount, reason) -> dict   # callverse/data/layer3.py, no DB write, in no allow-list
# {order_id, amount, decision, by, rule_id: "R-ESC-01", reason}
# decision: "not_required" (amount <= 300, by None) | "approved" (<= 500, by "finance") | "refused" (> 500, by "finance")
# amount not a finite number > 0 (NaN, inf, bool, text, <= 0) or unknown order -> {"error": ...}.
# Traced as step "layer3_decision".
```
The 300 is read from R-ESC-01's condition (`layer3_threshold()`), never written twice.
`by` is `None` for `not_required`: finance is not involved below 300 TND.
Agent IDs: `A`, `B` (`C`, `D` later). Vector store: small numpy index (cosine) on `bge-small-en-v1.5`,
swappable for Chroma/FAISS.
Demo: S1 refund approved · S2 wrong amount sent back then corrected · S3 delivery notification after
advancing the clock · (if time) Atlas hotel cancelled with agent C.

## 8. Local server (localhost only)
`callverse/server/app.py` (FastAPI), started by `python scripts/run_platform_server.py` on **`127.0.0.1:8000`**
(never `0.0.0.0`; no deployment). A thin HTTP layer over the functions above: each endpoint returns exactly what
the function returns. `GET /docs` lists every endpoint. Every request is traced (step `http_request`, actor `server`,
with `agent` for tool calls).

| Endpoint | Calls | Notes |
|---|---|---|
| `GET /` | — | read-only HTML dashboard (no write buttons) |
| `GET /company` | `get_company_profile()` | |
| `GET /policies`, `GET /policies/{rule_id}` | `load_policies()`, `get_policy()` | unknown rule → 404 |
| `GET /orders?status=&scripted=&limit=50` | `reports.list_orders()` | list, sorted by id, limit 1–500 |
| `GET /orders/{id}`, `/orders/{id}/tracking`, `/orders/{id}/refunds` | `get_order`, `get_tracking`, `get_refunds` | `{"error"}` → 404 |
| `GET /users/{id}` | `get_user(user_id=id)` | `{"error"}` → 404 |
| `GET /summary` | `reports.summary()` | same numbers as `scripts/data_summary.py` |
| `GET /refunds`, `/subscriptions`, `/events` | `reports.list_rows()` | newest first (for the dashboard) |
| `GET /proposals` | `reports.list_rows("proposals")` | newest first, JSON columns decoded |
| `GET /notifications/pending` | `reports.get_pending_notifications()` | read-only |
| `GET /traces/recent?n=20` | — | last lines of this server run's trace file |
| `POST /tools/{name}` body `{"agent": "A", "args": {...}}` | `registry.run_tool(agent, name, args)` | not on the agent's allow-list → **403**; a tool's own `{"error"}` (e.g. order not found) stays 200 |
| `POST /coordinator/refunds` body `{order_id, amount, rule_id, proposal_id}` | `create_refund` | token; refused → 400 |
| `POST /coordinator/subscriptions` body `{order_id, event, proposal_id}` | `create_subscription` | token; missing/unmatched `proposal_id` or refused → 400 |
| `POST /coordinator/orders/{id}/status` body `{new_status}` | `set_order_status` | token; refused → 400 |
| `POST /layer3/decide` body `{order_id, amount, reason}` | `layer3_decide` | token; error → 400 |
| `POST /coordinator/proposals` body = proposal | `record_proposal` | token; returns `{"id": "P-0001"}`; refused → 400 |
| `POST /coordinator/proposals/{id}/decision` body `{decision, reason}` | `record_decision` | token; refused → 400 |
| `POST /coordinator/subscriptions/{id}/sent` | `mark_subscription_sent` | token; refused → 400 |
| `POST /admin/reset` | `seed()` | token; re-seeds the DB for demos |

**Token rule**: every `POST /coordinator/*`, `/layer3/decide` and `/admin/reset` needs the header
`X-Coordinator-Token` equal to `PLATFORM_COORDINATOR_TOKEN` in `.env`. If the variable is missing or empty, all of
them return **403** (writes are off by default). Missing or wrong header → 403. The token value is never printed,
returned or logged. Write functions are still in no allow-list: `POST /tools/create_refund` → 403.
`amount` is passed to the function unchanged, so its guard decides (`NaN` in the JSON body → 400).
