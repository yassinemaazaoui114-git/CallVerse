# P01 report — ShopNova platform: policies, schema, write functions, events

## 1. In plain words
ShopNova now has its 8 written rules (policies) in one file that the code can load and check. The
database can now record refunds with the rule that justified them, delivery-notification requests, and
"order status changed" events, and every row says whether it is AI-written and whether it is a demo case.
Three new functions change the data (create a refund, create a subscription, change an order's status);
they sit outside the tool box, so no agent can ever call them — only the Coordinator (built later) will.
The tests now work on a temporary copy of the database, so running them never changes the real one.

## 2. Done
- **Policies**: `callverse/kb/policies_shopnova.json` — 8 rules, each `id, title, text, condition, ai_generated: true`.
  `callverse/kb/policies.py` — `load_policies()` (checks the 4 fields and unique ids), `get_policy(id)`,
  `notification_events()` (reads the event list from R-NOT-01's condition, so it is written in one place only).
  **Wording to be reviewed by Yassine.**
- **DB access in one place**: new `callverse/data/db.py` — `connect()`, `db_path()`, `use_db(path)`.
  Read tools, write functions and seed all open the DB through it; tests switch it to a temp file.
- **Schema** (`callverse/data/seed.py`):
  - `ai_generated` and `scripted` (0/1) on all 6 tables; all seed rows `ai_generated = 1`; the 10 orders `scripted = 1`.
  - `refunds` + `rule_id, proposal_id, created_at`; status CHECK `approved | completed | refused` (4506 stays `completed`).
  - order status CHECK with the 7 codes; 4512 is now `stuck_at_depot`.
  - new tables `subscriptions` and `events` (event CHECK = R-NOT-01 events).
- **Read tool** `get_refunds(order_id)` + JSON schema in `callverse/tools/shopnova_tools.py`. Not on any allow-list.
- **Write functions** `callverse/data/writes.py`: `create_refund`, `create_subscription`, `set_order_status`,
  each traced (`db_write` / `db_write_refused`, actor `platform`). Not in `TOOL_FUNCTIONS`, `TOOL_SCHEMAS` or allow-lists (tested).
- **Demo script** `scripts/advance_status.py --order 4512 --status out_for_delivery`.
- **Config**: `layer3: {stub_max_approve_tnd: 500}` in `config.yaml`.
- **Test isolation**: `tests/conftest.py` uses `tmp_path/shopnova_test.db` for every test, then restores the default.
- **Tests**: updated `test_tools.py` (status code + 3 new tests); new `test_policies.py` (4), `test_writes.py` (8).
- **Contract**: `docs/platform_contract.md` §2 (columns, labels, status codes, new tables), §3 (`get_refunds`),
  §4 (write functions), §5 (file location), §7 (Layer 3 config key).

## 3. Evidence
- Tests: **29 passed / 29** (`python -m pytest -q`, 4.5 s). Old 14 included (one updated for `stuck_at_depot`).
- Policies: **8/8** load, ids unique, 4 fields each (`test_policies.py`).
- `get_refunds(4506)` → 1 row (189.00, `completed`); `get_refunds(4512)` → `[]` (`test_tools.py::test_get_refunds`).
- `create_refund(4512, 59.90, "R-REF-03", "p-test")` → +1 row, `approved`, rule_id + proposal_id stored, `created_at 2026-10-09`.
- `create_subscription(4512, "out_for_delivery")` → `waiting`; `"lost"` → refused, row count unchanged.
- `set_order_status(4512, "out_for_delivery")` → status updated + **1** event row; `"teleported"` → refused, status unchanged.
- Real DB unchanged by the test run: `callverse/data/shopnova.db` mtime `2026-10-20 16:35:01.61` and
  MD5 `2da68362…4903` identical before and after.
- Demo script on the real DB: `stuck_at_depot -> out_for_delivery`, event `{id 1, 4512, out_for_delivery, 2026-10-09}`;
  `--status lost` → refused. Real DB was then re-seeded clean (`python -m callverse.data.seed`).

## 4. Problems
- **Old DB files keep the old schema.** A `shopnova.db` created before this task has no `events`/`subscriptions`
  tables. `run_demo.py` re-seeds by itself; anything else needs `python -m callverse.data.seed` once. (I re-seeded the local one.)
- **Agent A now sees `stuck_at_depot`** (underscore code) instead of `stuck at depot`. The model will usually
  rephrase it, but I did not run a live agent call to check (agents are outside this task).
- `get_refunds` returns a **list** (as the task asks), while the other tools return a dict. It works with the
  agent loop (results are JSON-encoded), but an unknown order returns a dict `{"error": ...}` — two shapes.
- Seed data detail beyond the task text: the 4506 refund row is also `scripted = 1` (it is part of scripted case
  4506); users and products are `scripted = 0`.
- Two small choices not in the task: `set_order_status(..., "delivered")` fills `delivered_date` with `sim_today`
  (otherwise `get_tracking` would say "not delivered"); run-time rows get `ai_generated = 0, scripted = 0`.

## 5. Questions for the Brain
1. `get_refunds`: keep the bare list, or wrap it as `{"order_id": ..., "refunds": [...]}` so every tool returns a dict?
2. Is `scripted = 1` on the 4506 refund row right?
3. Should `set_order_status` also refuse odd jumps (e.g. `delivered` → `shipped`)? Today it only refuses unknown codes.
4. Policy wording (8 texts in `policies_shopnova.json`) — waiting for Yassine's review.
5. Push access: add `dalimraihi` as collaborator on GitHub, or work through a fork + pull request?

## 6. Next step
Core task for Agent B + Coordinator: add `get_refunds` to B's allow-list, call `create_refund` /
`create_subscription` on approve, and use `load_policies()` + the conditions for the checks. Then the notifier
reads `events` rows and marks matching `subscriptions` as `sent` (demo S3).

Git: committed on branch `platform` (commit `70a0e41` + this report fix). **Push failed**: GitHub answered 403,
"Permission to yassinemaazaoui114-git/CallVerse.git denied to dalimraihi". Yassine needs to add `dalimraihi` as a
collaborator (or Dali pushes to a fork + PR). Then: `git push -u origin platform`. Not merged into `main`.
