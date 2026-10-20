# P07 report — Writes must match their approved proposal

## 1. In plain words
Before this task, a refund only had to point to some approved proposal for the same order. So an approval for
10 TND could pay out 378 TND, skipping the finance check above 300 TND, and even an approved "notify me" request could
pay a refund. Now the database layer refuses that: a refund must match the approved proposal exactly (same action
"refund", same order, same amount). Subscriptions now work the same way and need an approved "subscribe" proposal
for the same order and event. Recording a proposal now always answers with a dict, `{"id": "P-0001"}`, never a bare text.

## 2. Done
- **`create_refund`** (`callverse/data/writes.py`): the proposal must now also have action `refund`, and
  `round(params.amount, 2)` must equal `round(amount, 2)`. All existing checks are kept (amount guard, exists, approved,
  same order, used once, R-REF-05). The shared checks moved into a small helper, `_approved_proposal()`.
- **`record_proposal`** returns `{"id": "P-0001"}` on success and `{"error": ...}` on failure, never a string.
- **`create_subscription(order_id, event, proposal_id)`**: keeps the R-NOT-01 event check. The proposal must exist, be
  approved, have action `subscribe`, `params.order_id` = order and `params.event` = event, and not be used before.
  `proposal_id` defaults to `None`, so a call without it is refused with an error (never a `TypeError`).
- **Schema**: `subscriptions` gets a `proposal_id` column. It is needed to refuse a proposal used twice; the task asks
  for that check but does not name the column (see Problems).
- **Server**: `POST /coordinator/subscriptions` body now has `proposal_id`; `POST /coordinator/proposals` returns the
  function's dict as is.
- **Callers updated**: both demos (S3 now records and approves a `subscribe` proposal first), `tests/test_writes.py`,
  `tests/test_proposals_notifications.py`, `tests/test_server.py`. No caller passed a different amount or event than
  its proposal, so the stop rule was not triggered.
- **"A proposal is decided once"**: unchanged.
- **Contract**: §2 (`subscriptions.proposal_id`), §4 (new checks, new shapes, proposal shapes for refund/subscribe),
  §8 (subscription endpoint body).
- **Tests (+5)** in `test_writes.py`: amount must match (10.00 → 378.00 refused, 59.90 → 30.00 refused, matching →
  approved), a `subscribe` proposal can't pay a refund, rounding (59.899 ≙ 59.90), the 7 subscription refusals plus the
  match, and `record_proposal` always returning a dict.

## 3. Evidence
- Tests: **102 passed / 102** (the 97 old tests + 5 new, 8.2 s). Real `shopnova.db` MD5 and mtime unchanged by the tests.
- Refund refusals, each with **no new `refunds` row** and the last trace line `db_write_refused`:
  - approved 10.00 on 4515, then refund 378.00 → "amount 378.0 does not match the approved amount 10.0";
  - approved 59.90 on 4512, then refund 30.00 → refused;
  - approved `subscribe` proposal used for a refund → "is a 'subscribe' proposal, not 'refund'";
  - matching proposal → `approved`, as before.
- `record_proposal(valid)` → `{"id": "P-0001"}`; `record_proposal("junk" | None | 42 | {"agent": "B"})` → `{"error": ...}`.
- `create_subscription(4512, "delivered", pid)`: no pid, unknown pid, not approved, action `refund`, other order (4510),
  other event (`shipped`) and the same pid used twice → each refused, no new row, `db_write_refused`. A matching approved
  `subscribe` proposal → `waiting`, with `proposal_id` stored.
- Demos: both exit 0; their 9 RESULT lines are **identical** to P06, for both the Python and the HTTP demo.
- Data rows: a DB built with the P06 `seed.py` and one built with the P07 `seed.py` have identical rows in all 7 tables.
  The file MD5 changes (`f43329d0…` → **`e18ff80b…bb31`**) only because of the new column.

## 4. Problems
- **New column not named in the task**: `subscriptions.proposal_id` is what makes "not already used for a subscription"
  checkable. It is added at the end of the existing columns, before the labels. Anyone reading subscriptions by column
  position would need to know; code that reads by name is unaffected.
- **DB MD5 changed again** (`e18ff80b…`), because of the schema; no data changed.
- **Action name `subscribe`**: Brief #2 (archive) used `subscribe_update`. I followed the P07 text (`subscribe`). T07 must
  use the same name, or subscriptions will be refused.
- An approved proposal whose `params.amount` is missing or invalid can never pay a refund (it is refused as "does not
  match"). That is intended but worth knowing.

## 5. Questions for the Brain
1. Confirm the action names for T07: `refund` and `subscribe` (not `subscribe_update`)?
2. Should `set_order_status` also require an approved proposal one day, or does it stay a carrier/demo control?

## 6. Next step
Merge plan (NEXT_PLATFORM): `platform` (P05–P07) joins `main` after T06, at the start of T07. T07's Coordinator records
proposals with exactly the params it will write: refund `{order_id, amount}`, subscribe `{order_id, event}`.

Git: committed on `platform` and pushed to `origin/platform`. Nothing merged.
