# P03 — ShopNova platform: company profile, realistic data volume, return-window fact

## Why
The "ShopNova & Atlas – Platform Requirements" (prototype minimum) asks for two things we do not have yet:
- **#1 Company profile**: name, domain, one-paragraph description (what it sells, where it delivers).
- **#3 Seed data**: about 50-200 orders, with the scripted cases, and AI-generated data clearly labelled.
  Today the DB has 10 orders, 5 users, 6 products.
P02 also left one gap: R-RET-01 needs `days_since_delivery`, which nothing computes yet.

## Hard limits
- `docs/platform_contract.md` wins. Update it for every shape you change.
- **The 10 scripted orders (4505-4514) and the 4506 refund stay exactly as they are** (same ids, users, amounts,
  dates, statuses). The demos depend on 4512, 4506 and 4510. All demo results (S1, S2, S3, extras) must stay the same.
- `days_since_delivery` only **adds** a field: do not change `days_late` or any existing field.
- Generated data is **deterministic** (fixed seed, `random.Random(42)`, no current time), so re-seeding gives a
  byte-identical DB.
- Do not change agents, `llm.py`, `registry.py` allow-lists, intake, Coordinator or notifier.
- Standard library only. Tests use the temporary DB only. No secrets in files.

## What to do
1. **Company profile** — `callverse/data/company_shopnova.json`: `name`, `domain` (e-commerce), `description`
   (one paragraph: what it sells, where it delivers — Tunisia), `currency` "TND", `support_languages`, `carriers`
   (the carriers used in the seed), `ai_generated: true`. Add `get_company_profile()` in `callverse/data/company.py`
   (reads the JSON, checks the required fields). Not a tool, not on any allow-list (agents may get it later).
2. **More data** (`callverse/data/seed.py`), generated with `ai_generated = 1, scripted = 0`:
   - ~30 more users (Tunisian names, fake emails `@example.com`, fake phones), ~20 more products with TND prices
     and stock (a few with stock 0).
   - **Exactly 120 more orders**, ids **5001-5120** (never collide with 45xx). Order dates between 2026-08-01 and
     2026-10-08; every date consistent with `sim_today` 2026-10-09 (no delivered date in the future, delivered
     orders have `delivered_date`, others do not).
   - Status mix (rough): delivered 55%, shipped 15%, processing 10%, out_for_delivery 5%, stuck_at_depot 5%,
     refunded 5%, cancelled 5%. Some delivered late (1-5 days), a few late > 5 days and not delivered.
   - ~5 cash-on-delivery orders with `paid = 0`.
   - A refund row (`completed`) for every `refunded` order, amount = paid.
   - `total` = sum of items; `paid` = total, except cash on delivery.
   - Keep it under ~80 new lines in `seed.py`: one generator function, plain loops.
3. **`days_since_delivery`** in `get_tracking`: integer days from `delivered_date` to `sim_today`, or `null` if not
   delivered. Add it to the JSON description and contract §3, plus a test (it serves R-RET-01, 14-day returns).
4. **Layer 3 `by` field**: keep `None` for `not_required` and document it in contract §7 (answer to P02 Q1).
5. **Data summary script** — `scripts/data_summary.py`: prints counts per table, orders per status, total paid
   (TND), how many rows are `ai_generated` / `scripted`, and the company profile. This is what we show the professor for "label AI data".

## Checks (with numbers)
- Orders: **130** total = exactly **10** scripted + **120** generated (5001-5120, all `ai_generated = 1, scripted = 0`).
- 4505-4514 and the 4506 refund: same values as before (a test compares them field by field).
- **4512 still 6 days late** (`get_tracking(4512)["days_late"] == 6`); 4510 still `shipped`, on time.
- No order has `delivered_date` > 2026-10-09, `order_date` > `promised_date`, or a delivered status without
  `delivered_date`.
- Every `refunded` order has refunds summing to its `paid`; no refund exceeds `paid` (R-REF-05 holds on all data).
- Re-seeding twice gives the same MD5.
- `get_tracking(4507)["days_since_delivery"]` = 17 (delivered 2026-09-22); `get_tracking(4512)` → `null`.
- `get_company_profile()` returns all required fields.
- `python scripts/demo_platform.py` gives the **same RESULT lines** as P02. `python scripts/data_summary.py` exits 0;
  **paste its output in the report** (orders per status, total paid).
- Real `callverse/data/shopnova.db` unchanged after the test suite.
- All tests pass on the temporary database (report x/y, the 42 old ones included).

## Time box and stop rule
1.5 hours. Stop and ask if keeping the scripted cases identical forces a contract change.

## Git
Work on branch `platform`, commit and push `origin/platform`. Do not merge into `main`.
Write `tasks/P03_report.md` (same 6-section format as CLAUDE.md) and set `tasks/NEXT_PLATFORM.md` to WAITING FOR REVIEW.
