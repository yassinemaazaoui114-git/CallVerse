# P06 — Platform support for the Coordinator, the notifier and the Simulator  ·  Dali's lane

## Why
The core tasks (Coordinator T07, notifier, Simulator) need a few more platform pieces: an audit table for proposals and
decisions, notification sending helpers, and read-only case data for simulated users.

## Hard limits
- Branch `platform` (it already holds P05, still under review). Do not merge into `main`.
- Write functions stay in `callverse/data/writes.py` (outside `tools/`, on no allow-list).
- Keep existing tool names and return shapes. Tests on a temporary DB only. No secrets.

## What to do
1. **Proposals table** — `proposals(id TEXT 'P-0001', agent, action, params JSON, rule_id, facts_used JSON,
   user_confirmed, decision, decision_reason, created_at, decided_at, ai_generated, scripted)`.
   `record_proposal(proposal) -> id` (next `P-xxxx`) and `record_decision(id, decision, reason)` in `writes.py`, traced.
   `create_refund(..., proposal_id)` must reference an existing proposal id.
2. **Notifications** — `get_pending_notifications() -> [{subscription_id, order_id, event, event_at, user}]`
   (events that match `waiting` subscriptions, read-only) and `mark_subscription_sent(subscription_id)` (write, traced;
   refuses if not `waiting`).
3. **Simulator data (read-only)** — `read_own_case(order_id)` → user name + email, order id, items, status,
   promised_date, days_late, paid; `list_scenario_cases()` → the scripted cases with a short scenario tag
   (e.g. 4512 "late_refund", 4506 "already_refunded", 4510 "on_time", 4507 "damaged", 4515 "layer3").
   Not on any agent allow-list.
4. **Status move** — allow `shipped → stuck_at_depot` in the transition table.
5. Update `docs/platform_contract.md` (§2 proposals table, §4 new functions, §5 transitions) and the platform demo
   (S3 ends with `mark_subscription_sent`, status `sent`).

## Checks (with numbers)
- `record_proposal` → ids `P-0001`, `P-0002` in order; `record_decision` stores decision + reason.
- `create_refund` with an unknown proposal id → refused.
- S3: `get_pending_notifications()` → 1 item; after `mark_subscription_sent` → 0 items, status `sent`; second call refused.
- `read_own_case(4512)` → days_late 6, paid 59.90; `list_scenario_cases()` → 5 tagged cases.
- `shipped → stuck_at_depot` allowed; `delivered → shipped` still refused.
- All tests pass (report x/y); real DB unchanged by tests.

## Time box and stop rule
2 hours. Stop and ask if a contract shape must change in a way not listed here.

## Git (approved by Dali, 2026-10-20)
Commit and push branch `platform`. No merge. Write `tasks/P06_report.md`, set `tasks/NEXT_PLATFORM.md` to WAITING FOR REVIEW.

## Notes from review (Dali, 2026-10-20)
- **Existing callers of `create_refund`** pass made-up proposal ids ("p-test", "demo-s1", ...): `tests/test_writes.py`
  (9 calls), `scripts/demo_platform.py` (3), `scripts/demo_platform_http.py`, `callverse/server/app.py` and
  `tests/test_server.py`. Update them to call `record_proposal` first. Demo RESULT lines must stay the same
  (S3 gets the new `sent` line).
- **Keep the P05 server in step** (same token rule): `POST /coordinator/proposals`,
  `POST /coordinator/proposals/{id}/decision`, `POST /coordinator/subscriptions/{id}/sent`,
  `GET /notifications/pending`. Show a read-only proposals table on the dashboard. `read_own_case` and
  `list_scenario_cases` are not exposed over HTTP. Update contract §8.
- **Safety net (agreed with Yassine, 2026-10-20)**: `create_refund` refuses unless `proposal_id` is a recorded
  proposal whose decision is `approve`. Coordinator order: record proposal -> check -> record decision -> create refund.
  For 4515 finance approves first, then the Coordinator records `approve`.
- **Answers to P05 questions (Yassine)**: keep `httpx` (warning is harmless); no per-agent HTTP token (agents call the
  platform in Python on localhost); a tool's own `{"error"}` stays HTTP 200, only allow-list refusals are 403.
