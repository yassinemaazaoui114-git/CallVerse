# P03 report — Company profile, data volume, days_since_delivery, safety checks

## 1. In plain words
ShopNova now has a company profile and looks like a real shop: 131 orders instead of 10. All of them are
labelled AI-generated, and 11 are marked as fixed demo cases. The 120 new orders are made by a program with a
fixed "random seed", so the database is exactly the same every time it is rebuilt. A new demo case, order 4515
(378 TND), tells the large-refund story where finance must approve. Tracking now also says how many days ago an
order was delivered, so the 14-day return rule can be checked. Finally, the database layer itself now refuses two
kinds of mistakes even if the Coordinator gets them wrong: refunding more than what is left, and moving an order
status backwards.

## 2. Done
- **Company profile** `callverse/data/company_profile.json`: name, domain, description, products sold, 8 cities,
  carriers, delivery promise 3–6 days, TND, payment methods, support channels and languages, `ai_generated: true`.
- **Generated data** (`callverse/data/seed.py`, `generate_data()` with `random.Random(2026)`, dates relative to a
  fixed `SIM_TODAY` = 2026-10-09): 20 users (ids 6–25), 120 orders (ids 5001–5120), and a `completed` refund equal to
  `paid` for every generated `refunded` order. Generated orders belong only to generated users, so the scripted
  clients' histories don't change. All are `ai_generated = 1, scripted = 0`.
- **Scripted order 4515**: user 2 (Youssef), 2 × Smart Watch = 378.00 TND, paid 378.00, promised 2026-10-01
  (8 days late), `stuck_at_depot`, Aramex, `scripted = 1`.
- **`days_since_delivery`** added to `get_tracking` (other fields unchanged); JSON description updated.
- **Safety net in `create_refund`**: refused + traced `db_write_refused` if `amount > paid - refunded_total`.
- **Status transitions in `set_order_status`**: allowed moves in `STATUS_MOVES` (seed.py); any status → `cancelled`
  or `refunded`; everything else refused + traced. Staying on the same status is also refused.
- **Bug fix in `check_condition`** (P02 code): `and` / `or` now stop early like Python does. Before, R-RET-01
  (`delivered and days_since_delivery <= 14`) crashed on `None <= 14` for an undelivered order.
- **`scripts/data_summary.py`**: profile, rows per table (total / ai_generated / scripted), orders per status,
  scripted vs generated, late orders, cash on delivery, total paid, refunds total. Read-only.
- **Demo** `scripts/demo_platform.py` (review notes applied): the 4515 Layer 3 story (R-REF-03, R-REF-05, R-ESC-01 →
  finance approves → refund written); a 600 TND stub-only test labelled as such; the `create_refund` safety net
  refusing a second refund on 4506. The 4513 calls are removed.
- **Tests**: new `tests/test_seed_data.py` (9 tests: scripted orders field by field, counts and labels, status
  mix, date consistency, totals and refunds, 4515, days_since_delivery, identical rebuild); `test_writes.py`: safety net
  and transitions (+2), `test_delivered_sets_delivered_date` now goes through `out_for_delivery`; `test_tools.py`
  count 10 → 11; `test_policies.py` +1 (R-RET-01 with real `days_since_delivery`).
- **Docs**: `docs/platform_contract.md` §2 (labels, generated ids, transitions), §3 (`days_since_delivery`),
  §4 (safety nets), §6 (4515), §7 (`by` = `None`); README: new "Data" section.

## 3. Evidence
- Tests: **54 passed / 54** (`python -m pytest -q`, 7.0 s). The 42 old tests are included; 3 were updated as described.
- Orders: **11 scripted** (4505–4515) + **120 generated** (5001–5120) = 131.
- 4505–4514 + 4506 refund: a JSON dump saved before any change is **identical** to the one after. There is also a field-by-field
  test (`test_scripted_orders_unchanged`).
- `get_tracking(4512)["days_late"]` = 6; 4515 `paid` 378.00, `days_late` 8.
- `get_tracking(4505)["days_since_delivery"]` = 25, 4507 = 17, 4512 = `None`.
- `create_refund(4506, 1.00, ...)` → refused: "safety net R-REF-05: amount 1.0 > paid 189.0 - refunded 189.0 = 0.0 TND".
- `set_order_status(4505, "shipped")` → refused ("move delivered -> shipped is not allowed"); 4512
  `stuck_at_depot → out_for_delivery` → allowed.
- `layer3_decide(4515, 378.00)` → `approved` by `finance`.
- Data checks on all 131 orders: 0 future dates, 0 `order_date > promised_date`, 0 delivered/refunded without
  `delivered_date` (or the opposite), 0 wrong totals, 0 refunds over `paid`.
- Determinism: two rebuilds give the same MD5 `56d970b1…b189`, and the summary output is identical after a rebuild.
- Real DB unchanged by the tests: MD5 `56d970b1…b189` and mtime `18:46:13.03` are the same before and after.
- Demo (`python scripts/demo_platform.py`, no API key): exit 0. The S1, S2, S3 RESULT lines are **identical** to P02 (diffed).
  New extras:
  ```
  RESULT: 4506 second refund REFUSED by R-REF-05 (already fully refunded).
  RESULT: 4506 second refund REFUSED by the database safety net (create_refund).
  RESULT: 4515 refund of 378.00 TND APPROVED BY FINANCE (Layer 3, R-ESC-01).
  RESULT (stub test): layer3_decide(4515, 600) -> REFUSED by finance
  ```
- `python scripts/data_summary.py` (exit 0):
  ```
  Company : ShopNova (e-commerce, TND) - profile ai_generated = True
  Carriers: Aramex, Rapid-Poste | promise 3-6 days | cities: 8

  Rows per table (total | ai_generated | scripted)
    users            25 |   25 |    0
    products          6 |    6 |    0
    orders          131 |  131 |   11
    refunds           7 |    7 |    1
    subscriptions     0 |    0 |    0
    events            0 |    0 |    0

  Orders per status
    delivered           73
    stuck_at_depot      13
    shipped             12
    processing          12
    out_for_delivery     8
    refunded             7
    cancelled            6

  Scripted orders : 11 (ids 4505-4515)
  Generated orders: 120 (ids 5001-5120)
  Late orders     : 42 (22 not delivered yet, 20 delivered late); 11 more than 5 days late and not delivered
  Cash on delivery: 10 orders not paid yet (paid = 0)
  Total paid      : 19086.80 TND
  Refunds         : 7 rows, 909.20 TND
  ```

## 4. Problems
- **The status mix is "rough"**: `stuck_at_depot` came out at 9% of generated orders (11 of 120) against a weight of 5%.
  That is normal randomness with 120 orders, and the fixed seed keeps it the same on every rebuild. Changing the seed
  would change the mix, and the summary numbers in this report would then need updating.
- **11 open orders are more than 5 days late** (the 2 scripted ones and 9 generated). Each would qualify for R-REF-03 if a
  client asked. That's realistic, but a simulated client picking a random order may hit refunds more often than expected.
- **Transitions are strict**: `shipped → stuck_at_depot` (a parcel getting stuck) is not in the allowed list, so it is refused.
  I followed the task text exactly.
- **Rule choices not in the task**: generated `cancelled` orders have `paid = 0` (cancelled before payment); generated
  refunds use `rule_id` `R-RET-01` (returned items); the same-status "move" is refused.
- `SIM_TODAY` in `seed.py` repeats `sim_today` from `config.yaml` (2026-10-09). A test catches it if 4512 stops being
  6 days late, but the two values could drift if someone changes only one of them.
- Process: the old task file `tasks/P03_profile_and_seed_volume.md` was already deleted (staged) in the working tree
  when I started. The commit includes that deletion.

## 5. Questions for the Brain
1. Should `shipped → stuck_at_depot` be an allowed move? Real parcels get stuck after shipping, and a later
   scenario may need it.
2. Should `seed.py` read `SIM_TODAY` from `config.yaml` instead of repeating it? That would be one source, but it
   would also change how the seed depends on the config.
3. Is `paid = 0` for generated cancelled orders OK, or should some cancelled orders be paid and refunded?
4. Agents may later get the company profile (for example through a read tool). Should it become a tool in a later P task?

## 6. Next step
Core lane: Agent B + Coordinator can now use `get_tracking` (with `days_since_delivery`), `check_condition`,
`layer3_decide` (4515 is the Layer 3 test case) and the write functions, whose safety nets protect the database. Platform
lane: optionally, a `get_company_profile` read tool, and if the Brain agrees, the `shipped → stuck_at_depot` move.

Git: committed on branch `platform` and pushed to `origin/platform`. Not merged into `main`.
