# P07 — Writes must match their approved proposal  ·  Dali's lane (approved by Yassine, 2026-10-20)

## Why
P06 review found that `create_refund` checks that the proposal exists, is approved, is for the same order and is
used once, but **not what was approved**:
- a proposal approved for **10.00 TND** on 4515 can pay a refund of **378.00 TND**. That also skips Layer 3,
  because the Coordinator only checked 10.00 (< 300);
- an approved proposal with action `subscribe` (or any action) can pay a refund.
The database layer must refuse both, independently of the Coordinator (same idea as the R-REF-05 safety net).

## Hard limits
- Branch `platform`, no merge into `main`. Tests on the temporary DB only. No secrets.
- Keep function names and return shapes. Scripted data unchanged. Demo RESULT lines unchanged.

## What to do
1. In `create_refund` (`callverse/data/writes.py`), refuse (trace `db_write_refused`) unless:
   - the proposal's `action` is `refund`;
   - the proposal's `params.amount`, rounded to 2 decimals, equals `amount` rounded to 2 decimals.
   Keep every existing check (approved, same order, used once, R-REF-05, amount guard).
2. Tests: approved 10.00 then refund 378.00 → refused; approved 59.90 then refund 30.00 → refused;
   `subscribe` proposal used for a refund → refused; matching proposal → `approved` (as today).
3. **`record_proposal` always returns a dict** (Yassine): `{"id": "P-0001"}` on success, `{"error": ...}` on failure
   (never a bare string). Update every caller: `create_refund` / demos / server / tests use `result["id"]`.
4. **`create_subscription` needs an approved proposal** (Yassine): new signature
   `create_subscription(order_id, event, proposal_id)`. Refuse (trace `db_write_refused`) unless the proposal exists,
   its decision is `approve`, its `action` is `subscribe`, its `params.order_id` = `order_id`, its `params.event` =
   `event`, and it was not already used for a subscription. Keep the R-NOT-01 event check.
   Update the server endpoint `POST /coordinator/subscriptions` (body gets `proposal_id`), both demos, and tests.
5. **Keep "a proposal is decided once"** (unchanged).
6. Contract §4 (+ §8 for the endpoint body): list the new checks and the new `record_proposal` / `create_subscription` shapes.

## Checks (with numbers)
- The 3 refusals above, each with no new `refunds` row and one `db_write_refused` trace line.
- `record_proposal(valid)` → `{"id": "P-0001"}`; `record_proposal("junk")` → `{"error": ...}`; never a string.
- `create_subscription(4512, "delivered", pid)`: no pid / unknown pid / not approved / action `refund` / other order /
  other event (`shipped`) / pid used twice → refused, no new row; matching approved `subscribe` proposal → `waiting`.
- Demos (`demo_platform.py`, `demo_platform_http.py`): same RESULT lines as P06.
- All tests pass (report x/y, the 97 old ones included). Real `shopnova.db` unchanged by the tests.

## Time box and stop rule
1 hour. Stop and ask if an existing caller passes a different amount or event than its proposal.

## Git
Commit and push branch `platform`. No merge. Write `tasks/P07_report.md`, set `tasks/NEXT_PLATFORM.md` to WAITING FOR REVIEW.
