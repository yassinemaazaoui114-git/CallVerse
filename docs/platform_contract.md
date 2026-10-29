# Platform contract — ShopNova (for the platform builder)

What the CallVerse agents expect from the ShopNova mock platform. Keep these names and shapes
so the agents work without code changes. All amounts in **TND**. Demo date: **2026-10-09**.

## 1. What already runs (prototype repo)
Shared LLM layer (Groq `gpt-oss-120b`, backup `gpt-oss-20b`), placeholder SQLite database
(`callverse/data/seed.py`), 3 read tools, per-agent allow-lists, Agent A, traces, tests.
Not built yet: policies + search, Agent B, Coordinator, notifications, Intake, SLM, Simulator.

## 2. Tables (same structure as the placeholder)
Schema in `callverse/data/seed.py`. Every table also has two labels (0/1):
`ai_generated` (the row, or part of it — see the table below — was written by an AI or a generator) and `scripted`
(a demo case that must stay exactly as it is: the 11 scripted orders 4505–4515 and the 4506 refund).
Rows written at run time get `0 / 0`. Company profile: `callverse/data/company_profile.json`.

**Two kinds of seed data (T15).**
- **Scripted** (`source = 'scripted'`, written by hand in `seed.py`, all `ai_generated = 1`): users 1–5, products 1–6,
  orders 4505–4515 (`scripted = 1`), refund 1 of order 4506 (`scripted = 1`).
- **Real** (`source = 'olist'`): **2,000 real orders** of the Olist Brazilian E-Commerce dataset (CC BY-NC-SA 4.0,
  see `DATA_LICENCES.md`), ids **10001+**; their clients (users **1001+**), products (**101+**) and review scores.
  Built by `scripts/build_shopnova_sample.py` (fixed seed 2026) into `callverse/data/real/shopnova_olist_sample.json`;
  `seed.py` only loads that file. Refunds made from real signals have `source = 'generated'`.
  The old generated data (users 6–25, orders 5001–5120, `generate_data()`) is removed.

**Schema additions (T15).** On `users`, `products`, `orders`, `refunds`, `reviews`:
`source` (`scripted` | `olist` | `generated` | `app`; `app` = an order a client placed in the ShopNova app
(`create_order`, T17); `NULL` = written at run time by the Coordinator) and `source_id` (the Olist id of a real
row: `order_id`, `customer_unique_id`, `product_id`, `review_id`; `NULL` otherwise; Olist reuses a few `review_id`s).
`users.city` (one of the 8 `cities_served`; `NULL` for users 1–5). New table `reviews(id, order_id, score 1–5, created_at)`.

**Schema additions (T17 follow-up, Q2).** `products.category` (Olist's English category, e.g. `audio`; real
products from the sample file, products 1–6 from `seed.SCRIPTED_CATEGORIES`: 1 audio, 2 telephony, 3 electronics,
4 watches_gifts, 5 audio, 6 computers_accessories) and `orders.payment` (`card` | `cash_on_delivery`, required; real
orders from the Olist mapping — boleto → cash on delivery; scripted: 4514 `cash_on_delivery`, all others `card`).
All other values of the scripted rows are unchanged (`tests/test_seed_data.py`: the md5 of the old columns is the same).
Note: the read tools return whole rows, so agents now also see `payment` in `get_order`.

**Schema additions (T18, ShopNova admin).** Reseed needed (`python -m callverse.data.seed`).
- `products.active INTEGER NOT NULL DEFAULT 1` (0/1): soft delete. The Shop (`shop_reads`) shows only active
  products and `create_order` refuses an inactive one; old orders keep showing it (their `items` carry name + price).
- New table `admin_actions(id, at, admin, action, target_table, target_id, before JSON, after JSON)`: one row per
  change made by the ShopNova admin (`at` = simulation clock), written in the SAME transaction as the change by the
  admin write functions of `writes.py`: `create_product`, `update_product`, `deactivate_product`,
  `reactivate_product`, `admin_set_order_status` (STATUS_MOVES only, `cancelled` only from `processing` with the
  stock put back, `refunded` never by hand), `create_user`, `update_user`; and `log_admin_action` for a refund
  approval / refusal (the refund itself is written by `create_refund`). None of them is in any agent allow-list.
  Admin products / users get `source = 'app'`, `ai_generated = 0`, `scripted = 0`.
- In CallVerse's own tickets DB (`callverse.db`, not ShopNova's): `tickets.user_unread` (0/1, added on connect if
  missing) and the `approvals` rows are now used (the real Layer 3 queue, §7).

**Real vs generated columns, per table (rows with `source = 'olist'` / `'generated'`).**

| Table | Real (from Olist) | Generated | Row label |
|---|---|---|---|
| `orders` | `order_date` (purchase), `promised_date` (Olist estimated delivery), `delivered_date`, `status` (mapped, below), `total` and `paid` (Olist payments, converted), `items` (products, qty, unit prices, and one `Delivery` line = the real freight; converted), `user_id`/product links, `source_id` | `carrier`, `tracking_number` (orders past processing, as the old seed), the `refunded` status (see refunds) | `ai_generated = 0` |
| `users` | that the client exists, which orders are theirs (one user per Olist `customer_unique_id`, so repeat buyers stay), `city` (from the real Brazilian state, fixed table below), `source_id` | `name` (Tunisian), `email`, `phone` | `ai_generated = 1` |
| `products` | that the product exists, its category, `price` (median of its real item prices in the sample), `source_id` | `name` ("Audio item 0042", from the English category), `stock` | `ai_generated = 1` |
| `reviews` | `score`, `created_at`, `order_id`, `source_id` (the Portuguese text is not kept) | — | `ai_generated = 0` |
| `refunds` (`source = 'generated'`) | the signals: order delivered after its promised date **and** latest real review score 1–2 | the refund itself: full `amount` = paid, `status = completed`, `rule_id = R-RET-01`, `created_at` = delivery + 2–6 days; none above 300 TND (R-ESC-01) — those orders stay `delivered` | `ai_generated = 1` |

How the real data was turned into ShopNova data (all in the builder script, with comments):
- **Orders kept:** all items in electronics categories (`telefonia`, `telefonia_fixa`, `informatica_acessorios`,
  `eletronicos`, `audio`, `pcs`, `pc_gamer`, `tablets_impressao_imagem`, `relogios_presentes`, `consoles_games`);
  left out: 3 "delivered" orders without a delivery date, 12 orders whose real story lasts more than 90 days.
- **Sample:** clients drawn at random (seed 2026), all their orders taken, until 2,000 orders or more.
- **Dates:** each order moves by its own whole number of days so that everything that happened (purchase, delivery,
  reviews) falls in the 90 days before `sim_today`; all real durations stay. A promised date may be after
  `sim_today` (it is a promise, not an event).
- **Status:** `delivered` → `delivered`; `shipped` → `shipped`, or `stuck_at_depot` if its promised date is before
  `sim_today`; `canceled`/`unavailable` → `cancelled`; `created`/`approved`/`invoiced`/`processing` → `processing`.
- **Money:** 1 BRL = 0.5625 TND (`currency` in `config.yaml`, Wise mid-market, 2026-10-29), rounded to 0.01.
  `total` = items + delivery (= the Olist payments); for 8 orders with a voucher or instalment interest the total is
  the converted payment and differs from the lines (listed in `tests/test_seed_data.py`).
- **Payment:** Olist `boleto` → cash on delivery (`paid = 0` until delivered); card, debit card, voucher → card;
  cancelled → `paid = 0`.
- **Cities** (Brazilian state → `cities_served`): states ranked by their number of Olist customers, then given the
  8 cities in profile order, round robin: SP, ES, PB, AC → Tunis; RJ, GO, PI, AP → Ariana; MG, PE, RN, RR → Ben Arous;
  RS, CE, AL → Sousse; PR, PA, SE → Sfax; SC, MT, TO → Monastir; BA, MA, RO → Nabeul; DF, MS, AM → Bizerte.
- **Company profile:** `delivery_promise_days` (min / median / max days from order to promise) and `sells` (the real
  categories in English) are written by the builder from the sample.

- `users(id, name, email, phone, city, source, source_id)`
- `products(id, name, price, stock, category, active, source, source_id)`
- `orders(id, user_id, items[JSON], total, paid, status, order_date, promised_date, delivered_date, carrier, tracking_number, payment, source, source_id)`
  - `items`: list of `{product_id, name, qty, price}`; real orders end with one `{"product_id": null, "name": "Delivery", "qty": 1, "price": <freight>}`
  - `status` codes: `processing`, `shipped`, `stuck_at_depot`, `out_for_delivery`, `delivered`, `refunded`, `cancelled`
  - allowed moves: `processing → shipped → out_for_delivery → delivered`, `shipped → stuck_at_depot`,
    `stuck_at_depot → out_for_delivery`,
    any status → `cancelled` or `refunded` (staying on the same status is refused)
- `refunds(id, order_id, amount, status, rule_id, proposal_id, created_at, source, source_id)`
  - `status`: `approved` (written by the Coordinator), `completed` (paid out, e.g. 4506), `refused`
- `reviews(id, order_id, score, created_at, source, source_id)` — real Olist review scores 1–5 (no text)
- `subscriptions(id, order_id, event, status waiting|sent, created_at, proposal_id)` — `proposal_id` = the approved
  `subscribe` proposal it came from
- `events(id, order_id, event, at)` — one row each time an order reaches a notification event
- Notification events (= R-NOT-01): `shipped`, `out_for_delivery`, `delivered`.
- `proposals(id TEXT 'P-0001', agent, action, params JSON, rule_id, facts_used JSON, user_confirmed 0|1, decision,
  decision_reason, created_at, decided_at)` — audit of every agent proposal and the Coordinator's decision.
  `decision`: `NULL` (not decided yet) or `approve | send_back | ask_user | ask_proof | layer3 | escalate`.
  `refunds.proposal_id` refers to `proposals.id` (seed refunds predate the system and have `NULL`).
- Dates are ISO `YYYY-MM-DD`. The real sample is placed with the fixed start date (`sim_today` in `config.yaml`,
  read through `config.sim_start()` by the builder; written in one place only). Run-time writes use `sim_today()`, which follows the
  simulation clock (§9): it is 2026-10-09 until the clock is moved.

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
create_order(user_id, product_id, quantity, payment) -> dict    # T17: called by the ShopNova app only (logged-in
                                                                # client), never by the Coordinator or an agent;
                                                                # user and product exist, stock >= quantity,
                                                                # quantity 1-10, payment card | cash_on_delivery;
                                                                # "processing", promised = today + 25 days,
                                                                # paid = total (card) or 0, stock decreases,
                                                                # source "app", ai_generated 0, scripted 0
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

**Real Layer 3 queue (T18).** `config.yaml` `layer3: {mode: stub, ...}`: `stub` (default) = the rule above;
env `CALLVERSE_LAYER3_MODE=queue` (set by `start_shopnova.ps1` and the ShopNova app) = the ShopNova admin decides.
In queue mode the Coordinator returns the new outcome **`layer3_pending`** at step 6 (the stub is not called, the
proposal stays undecided, nothing is written; the user is told "Your refund of X TND for order N needs approval
from our finance team. We will reply here as soon as it has been reviewed."). The web chat channel creates the
`approvals` row (pending) and sets the ticket to "Waiting for finance"; a new message about the same order gets a
fixed reply with no agent call. `callverse/channels/approvals.py` `decide(approval_id, admin, approve, reason)`
re-checks the data, records the decision on the proposal (`approve` or `layer3`), writes the refund with
`create_refund` (+ `refunded` for R-REF-03), logs `admin_actions`, and posts a new reply (SLM) on the ticket.
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
| `GET /clock` | `clock.now()`, `clock.start()` | read-only `{now, start, today}`; the clock is never moved over HTTP |
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

**Demo screen (P09)** — `callverse/server/demo.py` + `demo.html`, page `GET /demo`. **Off by default**
(`config.yaml → server.demo_enabled: false` → every demo route answers 404) and not listed on `/docs`.
`POST /demo/message {text}` runs `pipeline.handle()` → `{run_id, final_reply, reply_source, route, decision, seconds,
stages}`; `POST /demo/story/{S0|S1|S2|S4|...}` (re-seeds first; S2 = injected first amount, always undone) → same
shape, or `{"error": "not available yet"}`; `GET /demo/runs/{run_id}` → stages read from that run's trace (ids
`run_[A-Za-z0-9_]+` only); `POST /demo/clock/advance {hours}`, `POST /demo/clock/reset`, `POST /demo/notifier/run`
(T09), `POST /demo/reset` (re-seed + clock reset). One request at a time (409 when busy), one trace run per request,
a POST whose `Origin` is not this server → 403, API-key-like strings removed from every answer.
P09b: a request whose `Host` is not `127.0.0.1:<port>` or `localhost:<port>` (port = `server.port`, default 8000) → 403. `POST /demo/story/S3` resets data + clock, runs the S3 message and returns `next: ["+24 h", "+30 h", "Send notifications"]`; `POST /demo/notifier/run` calls `notifier.run_notifier()` → `{run_id, messages: [{subscription_id, order_id, event, text, reply_source}], sent, stages}`. Typed messages never re-seed (only `POST /demo/reset` does).

## 9. Simulation clock + scripted delivery timeline (story S3)
`callverse/data/clock.py`. The clock is stored in the database (one-row table `sim_clock`; applied timeline events in
`sim_timeline_applied`). Both tables are created the first time the clock moves, so a freshly seeded database is
unchanged.
```python
clock.start() -> datetime        # sim_today from config.yaml at 09:00 (2026-10-09T09:00)
clock.now() -> datetime          # current simulated time (= start until advance() is called)
clock.advance(hours) -> {"from", "to", "applied": [event results]}   # finite hours, 0 < hours <= 8760 (one year), else {"error"}
clock.reset() -> {"now", "orders_restored"}
config.sim_start() -> date       # the fixed start date (used by seed.py, never moves)
config.sim_today() -> date       # clock.now().date(): days_late, days_since_delivery and new dates follow it
```
- **Timeline** `callverse/data/scenario_timeline.json` (`scripted: true`, `ai_generated: true`): order **4510**
  (shipped, promised 2026-10-10, on time; simulator scenario `on_time`): `+24 h → out_for_delivery`, `+30 h → delivered`.
  Event shape `{id, order_id, after_hours, status}`; hours count from `clock.start()`.
- `advance()` applies every due event once, in time order, through `set_order_status` (transition table applies);
  the `events` row that `set_order_status` writes gets `scripted = 1`. An illegal move is refused, reported in `applied`
  as `{"applied": false, "reason": ...}`, and never retried. Applied: `{"applied": true, "old_status", "event_row", ...}`.
- Dates stay `YYYY-MM-DD` (`events.at`, `delivered_date`, `created_at`, ...): the clock's date is used. Only `sim_clock`
  stores a datetime.
- `reset()` is the **one exception** to "status changes only through `set_order_status`": it restores the timeline
  orders' seeded `status` and `delivered_date` directly (going back, e.g. delivered → shipped, is refused by the
  transition table) and deletes their `scripted = 1` events rows and the applied list.
- Notifications are not sent here: after `advance()`, `reports.get_pending_notifications()` returns the waiting
  subscriptions whose event has now happened; the notifier (core) sends them and calls `mark_subscription_sent`.
- Script: `python scripts/advance_clock.py --hours N` / `--reset`. Traced steps: `clock_advance`, `clock_reset`, `clock_refused`.
