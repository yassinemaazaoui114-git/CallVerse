# P03 — Company profile, data volume, days_since_delivery, safety checks

## Why
The prototype needs a believable company (profile + enough orders) for demos and for the teacher's
"explain your data" question, a real Layer 3 story, the field that makes the 14-day return rule (R-RET-01)
checkable, and two safety nets in the database layer.

## Hard limits
- The 10 scripted orders **4505–4514 stay exactly as they are** (all fields). 4512 must stay 6 days late.
- New generated orders use ids **5001–5120**, `ai_generated = 1`, `scripted = 0`, created with a **fixed random
  seed** (same data on every rebuild).
- Existing tool fields do not change. `days_since_delivery` is an **added** field only.
- Tests use the temporary DB only; the real `shopnova.db` must stay unchanged by the test suite.
- No agent, Coordinator, intake or LLM code changes. No secrets in files.

## What to do
1. **Company profile** — `callverse/data/company_profile.json`: name, what it sells, cities served, carriers,
   delivery promise (days), currency TND, support channels; `ai_generated: true`.
2. **Generated orders** — about 120 orders (5001–5120) over the 60 days before 2026-10-09: realistic mix of statuses
   (mostly delivered; some shipped, processing, out_for_delivery, stuck_at_depot, cancelled, refunded), some late,
   a few cash-on-delivery (paid 0), items from the product list. Consistent dates (order ≤ promised; delivered only
   for delivered/refunded). Generated users only if needed (also `ai_generated = 1`).
3. **Scripted Layer 3 case** — order **4515**: a scripted user, 2 × Smart Watch = 378.00 TND, paid 378.00,
   promised at least 6 days before 2026-10-09, not delivered, status `stuck_at_depot`, `scripted = 1`.
4. **`days_since_delivery`** in `get_tracking`: `sim_today - delivered_date` for delivered orders, `null` otherwise.
   Update the JSON schema description and `docs/platform_contract.md`.
5. **Safety net in `create_refund`** — refuse (and trace `db_write_refused`) if
   `amount > paid - refunded_total`, independently of the Coordinator.
6. **Status transitions in `set_order_status`** — allowed moves only:
   `processing → shipped → out_for_delivery → delivered`, `stuck_at_depot → out_for_delivery`,
   any status → `cancelled` or `refunded`. Refuse and trace anything else.
7. **Summary script** — `scripts/data_summary.py`: counts per table, orders per status, scripted vs generated,
   late orders, total paid, refunds total.
8. **Docs** — `docs/platform_contract.md` (new field, transitions, 4515), short "Data" section in the README
   explaining what is AI-generated and what is scripted.

## Checks (with numbers)
- Orders: **11 scripted** (4505–4515) + **~120 generated**; 4505–4514 byte-identical to before (compare a dump).
- 4512 still `days_late = 6`; 4515 `paid = 378.00`, `days_late ≥ 6`.
- `get_tracking(4505)` → `days_since_delivery = 25` (2026-10-09 − 2026-09-14); `get_tracking(4512)` → `null`.
- `create_refund(4506, 1.00, ...)` → refused by the safety net.
- `set_order_status(4505, "shipped")` (delivered → shipped) → refused; `stuck_at_depot → out_for_delivery` → allowed.
- `layer3_decide(4515, 378.00, ...)` → approved by finance (≤ 500).
- Rebuild the DB twice → identical summary output (fixed seed).
- All tests pass (report x/y); real `shopnova.db` unchanged by the tests.

## Time box and stop rule
2 hours. Stop and ask if a scripted order would have to change.

## Git (approved by Dali, platform lane, 2026-10-20)
Work on branch `platform`, commit and push it. **Do not merge into `main`** (merge needs Yassine and Dali).
Write `tasks/P03_report.md` (6-section format) and set `tasks/NEXT_PLATFORM.md` to WAITING FOR REVIEW.

## Notes from review (Dali, 2026-10-20)
- `tests/test_writes.py::test_delivered_sets_delivered_date` calls `set_order_status(4512, "delivered")`
  (`stuck_at_depot → delivered`), which the new transitions refuse. Update it to go through `out_for_delivery` first;
  keep what it checks (`delivered_date` = 2026-10-09).
- `scripts/demo_platform.py` extra still calls `layer3_decide(4513, 350 / 600)` (4513 paid only 189). Replace it with
  the real story: **4515, 378.00 TND → approved by finance**. Keep one direct stub call above 500 (e.g. 600 on 4515)
  to show a refusal, labelled as a stub test. S1, S2, S3 RESULT lines must stay the same.
- In the demo, also show the `create_refund` safety net: second refund on 4506 refused by the database layer.
