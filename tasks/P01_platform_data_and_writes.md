# P01 — ShopNova platform: policies, schema, write functions, events

## Why
Scenarios S1 (refund approved), S2 (wrong amount sent back) and S3 (delivery notification) need real
policies, a database that can record refunds/subscriptions/events, and write functions that **only the
Coordinator** can use. This task builds the platform side; agent B, the Coordinator and the notifier are core tasks.

## Hard limits
- `docs/platform_contract.md` wins over any other brief. Keep tool names and return shapes unchanged.
- Write functions live in `callverse/data/writes.py`, **outside** `tools/`. Never add them to
  `TOOL_FUNCTIONS`, `TOOL_SCHEMAS` or any allow-list.
- The demo date stays fixed (`sim_today` in `config.yaml`). Do not build a moving clock.
- Tests must never touch the real database: use a temporary copy.
- Do not change agents, `llm.py`, intake or anything outside the platform files listed below.
- No secrets in files.

## What to do
1. **Policies** — `callverse/kb/policies_shopnova.json`: the 8 rules R-DEL-01, R-DEL-02, R-REF-03, R-REF-05,
   R-RET-01, R-DMG-01, R-ESC-01, R-NOT-01. Each: `id`, `title`, `text` (what agents read), `condition`
   (machine-checkable, e.g. `days_late > 5 and not delivered`; `null` if none), `ai_generated: true`.
   Key numbers: > 5 days late → full refund on request; 14 days for returns; > 300 TND → Layer 3;
   notification events `shipped`, `out_for_delivery`, `delivered`. Plus `load_policies()` in
   `callverse/kb/policies.py` (returns the list; validates ids are unique and fields present).
   **Yassine reviews the wording before merge.**
2. **Schema changes** (`callverse/data/seed.py`):
   - columns `ai_generated` and `scripted` (0/1) on every table; all current rows `ai_generated = 1`;
     the 10 seed orders `scripted = 1`.
   - `refunds`: add `rule_id`, `proposal_id`, `created_at`. Status values: `approved`, `completed`, `refused`
     (4506 stays `completed`).
   - order status codes: `processing`, `shipped`, `stuck_at_depot`, `out_for_delivery`, `delivered`,
     `refunded`, `cancelled` (4512 becomes `stuck_at_depot`). Update the test that checks it.
   - new tables `subscriptions(id, order_id, event, status waiting|sent, created_at, ai_generated, scripted)` and
     `events(id, order_id, event, at, ai_generated, scripted)`.
3. **Read tool** — `get_refunds(order_id)` in `shopnova_tools.py` (+ JSON schema). Returns a list of refund rows
   (empty list if none). Do **not** add it to any allow-list (agent B's task does that).
4. **Write functions** — `callverse/data/writes.py`, each traced with `trace.log("db_write", ...)`:
   - `create_refund(order_id, amount, rule_id, proposal_id)` → row with status `approved`; returns the row.
   - `create_subscription(order_id, event)` → status `waiting`; refuses events not in R-NOT-01.
   - `set_order_status(order_id, new_status)` → updates the order and inserts an `events` row when the status is
     one of the notification events; refuses unknown status codes.
   - `scripts/advance_status.py --order 4512 --status out_for_delivery` calls `set_order_status` (for demo S3).
5. **Config** — `config.yaml`: `layer3: {stub_max_approve_tnd: 500}` (the 300 TND threshold stays in R-ESC-01's condition).
6. **Test isolation** — change `tests/conftest.py` so every test seeds a **temporary** DB (e.g. pytest `tmp_path`
   + making `DB_PATH` configurable), never `callverse/data/shopnova.db`.
7. **Contract** — update `docs/platform_contract.md` §2 (new columns, tables, status codes) and §4 (write functions).

## Checks (with numbers)
- Policies: **8/8** rules load; ids unique; every rule has the 4 fields.
- `get_refunds(4506)` → 1 row (189.00, `completed`); `get_refunds(4512)` → 0 rows.
- `create_refund(4512, 59.90, "R-REF-03", "p-test")` → 1 new row, status `approved`, with rule_id and proposal_id.
- `create_subscription(4512, "out_for_delivery")` → status `waiting`; `create_subscription(4512, "lost")` → refused.
- `set_order_status(4512, "out_for_delivery")` → order updated + **1** event row; unknown status → refused.
- After running the full test suite, the real `callverse/data/shopnova.db` is **unchanged** (compare its modification
  time before/after, or its absence).
- All tests pass (report x/y; old ones included).

## Time box and stop rule
2 hours. Stop and ask if a contract shape would have to change in a way not listed here.

## Git (approved by Yassine, 2026-10-20)
Work on branch `platform` (from the latest `main`), commit and push that branch. **Do not merge into `main`.**
Write `tasks/P01_report.md` (same 6-section format as CLAUDE.md) and set `tasks/NEXT_PLATFORM.md` to WAITING FOR REVIEW.
