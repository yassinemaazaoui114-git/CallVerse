# P06 report — Platform support for the Coordinator, the notifier and the Simulator

## 1. In plain words
The platform now keeps a written record of every proposal an agent makes and of the Coordinator's decision on it
(numbered P-0001, P-0002, ...). A refund can only be written if it points to a proposal the Coordinator approved, so
no refund can appear without a recorded decision. The notifier can now ask "which notifications must I send?", and
mark each one as sent exactly once. The Client Simulator can read what a client knows about their own order, plus the
list of 5 demo cases. A shipped parcel can now also get stuck at the depot. All of this is also on the local server
and the dashboard, which now shows a proposals table.

## 2. Done
- **`proposals` table** (`seed.py`): `id 'P-0001'`, agent, action, params (JSON), rule_id, facts_used (JSON),
  user_confirmed, decision (NULL or `approve | send_back | ask_user | ask_proof | layer3 | escalate`), decision_reason,
  created_at, decided_at, plus the two labels. It starts empty; no existing row changed.
- **`writes.py`** (all traced, all on no allow-list):
  - `record_proposal(proposal) -> "P-xxxx"` (or `{"error"}` for a missing agent/action or non-JSON-safe params such as NaN);
  - `record_decision(id, decision, reason)` → updated row. A proposal is decided **once** (see Questions);
  - `create_refund(..., proposal_id)` now refuses unless the proposal exists, is decided `approve`, is for the same
    order, and was not already used for another refund. The R-REF-05 amount safety net is still there;
  - `mark_subscription_sent(subscription_id)` → `sent`; refused if not `waiting`.
- **Read-only helpers**: `reports.get_pending_notifications()` (events matching `waiting` subscriptions, with the user)
  and `callverse/data/simulator_data.py` (new) with `read_own_case(order_id)` and `list_scenario_cases()`. Neither is a
  tool, and the simulator data is not on HTTP.
- **Status move** `shipped → stuck_at_depot` added to `STATUS_MOVES`.
- **Callers updated** (review notes): `tests/test_writes.py`, `tests/test_server.py`, both demos and the server now
  record and approve a proposal before `create_refund`.
- **Server** (same token rule): `POST /coordinator/proposals` (returns `{"id": "P-0001"}`),
  `POST /coordinator/proposals/{id}/decision`, `POST /coordinator/subscriptions/{id}/sent`, `GET /notifications/pending`,
  plus `GET /proposals` for the dashboard. **Dashboard**: a read-only "Proposals & Coordinator decisions" table.
- **Demos**: every refund goes through proposal → decision → refund. S2's 70.00 proposal is recorded as `send_back`.
  S3 ends with the pending notification → `mark_subscription_sent` → `sent`, and a second call is refused.
- **Contract**: §2 (proposals table, transitions), §4 (new functions, Coordinator order, read helpers),
  §5 (transitions note), §8 (5 new endpoints).
- **Tests**: new `tests/test_proposals_notifications.py` (10); `test_writes.py` +1 (`shipped → stuck_at_depot`);
  `test_server.py` +4.
- `CLAUDE.md`: Dali's own "Do the next platform task" line was already in the working tree; I committed it with P06.

## 3. Evidence
- Tests: **97 passed / 97** (83 old + 14 new, 11 s). Real `shopnova.db` MD5 `f43329d0…12aa` and mtime unchanged by the tests.
- `record_proposal` → `P-0001`, then `P-0002`. `record_decision` stores decision, reason and `decided_at`
  2026-10-09; a second decision on the same proposal is refused.
- `create_refund` with `"p-made-up"` → "safety net: proposal p-made-up not found". Not decided → "not approved".
  Other order → refused. Reused → "already used". `send_back` → refused.
- S3: `get_pending_notifications()` → **1** item (subscription 1, `delivered`, Sara Ben Ali). After
  `mark_subscription_sent` → **0** items, status `sent`; a second call → refused.
- `read_own_case(4512)` → `days_late` 6, `paid` 59.9, status `stuck_at_depot`, Sara's name and email, no internal fields.
  `list_scenario_cases()` → **5** tagged cases (4512 late_refund, 4506 already_refunded, 4510 on_time, 4507 damaged,
  4515 layer3), all scripted.
- `set_order_status(4510, "stuck_at_depot")` (shipped → stuck_at_depot) allowed, no event; `delivered → shipped` still refused.
- Demos: both exit 0. The 8 old RESULT lines are **identical**, plus the new S3 line
  `RESULT S3: subscription #1 marked 'sent'; 0 notifications pending.` The HTTP demo's RESULT lines are identical to the Python demo's.
- Data unchanged: a DB built with the P05 `seed.py` (MD5 `56d970b1…b189`) and one built with the new `seed.py` have
  identical rows in all 6 old tables. The only difference is the new, empty `proposals` table, which changes the file
  MD5 to `f43329d0…12aa`.
- Live server: dashboard script (run in Node against the server) shows 131 orders, the 11-row scripted filter, 8 policies
  and the proposals table ("none yet" on the real DB). `GET /proposals` and `GET /notifications/pending` → 200;
  `POST /coordinator/proposals` without a token → 403.

## 4. Problems
- **The DB file MD5 changed** (`56d970b1…` → `f43329d0…`) because of the new table. Any check that compares against the
  P03 MD5 must use the new value. The data rows are identical (proven above).
- **`record_proposal` returns two types**: the id string on success, `{"error": ...}` on refusal, because the task says
  `-> id`. The other write functions return a dict. Callers must check `isinstance(result, dict)`. Over HTTP it is
  always a dict (`{"id": ...}` or `{"error": ...}`).
- **Extra safety checks in `create_refund`**, beyond "decision is approve": the proposal must be for the same order, and one
  proposal pays at most one refund. Both are cheap and close obvious holes. The proposal's `amount` is **not** compared
  with the refund amount; the R-REF-05 net covers over-refunds.
- **Notification matching** uses dates only (`event.at >= subscription.created_at`). With a fixed demo date, an event
  and a subscription on the same day always match, even if the event came first. That is fine for S3; a real clock
  would need timestamps.
- `get_pending_notifications` lives in `reports.py` (read views), not in `writes.py`. `mark_subscription_sent` is in `writes.py`.

## 5. Questions for the Brain
1. **Decided once?** I refuse a second decision on the same proposal (the audit is never rewritten; a corrected proposal
   is a new proposal). If T07 wants `layer3` recorded first and then `approve` on the same proposal, this must be relaxed.
   Today the flow is: finance first, then `approve` (as agreed).
2. Should `create_refund` also require `amount` = the proposal's `params.amount`?
3. Should `create_subscription` also require an approved proposal (`subscribe_update`), like refunds?

## 6. Next step
Merge plan (NEXT_PLATFORM): `platform` (P05 + P06) joins `main` after T06, at the start of T07. T07's Coordinator can use
`record_proposal` → checks → `record_decision` → `create_refund` / `create_subscription`, and the notifier can use
`get_pending_notifications` + `mark_subscription_sent`.

Git: committed on `platform` and pushed to `origin/platform`. Nothing merged.
