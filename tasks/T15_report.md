# T15 report — ShopNova on real Olist data (STOPPED at step 6: a non-count test fails)

## 1. In plain words
I built the tool that turns the real Olist shop data into ShopNova's data: 2,000 real electronics orders, with
their real dates, statuses, payments and review scores, converted to dinars and moved into the 90 days before the
demo date. The database now loads these real orders in place of the 120 invented ones, and I proved that the 11
demo orders did not change at all. Then I ran the tests: 320 of 325 pass. Four of the 5 failures are old tests that
counted the invented data. The fifth checks that "order total = sum of the item prices", and real Olist totals also
include the delivery fee. The task's stop rule says to stop on that kind of failure, so I stopped there and you need
to decide how delivery fees should be shown.

## 2. Done (steps 0–5 partly, 7 done; stopped in step 6)
- **Step 0 Git:** branch `feature/shopnova-real-data` from `main` 7164f54; commit 416972d = task file + NEXT.md
  IN PROGRESS + `data/raw/` in `.gitignore`.
- **Step 1 check:** no **code** depends on orders 5001–5120 or users 6–25. What I found:
  - Tests: `tests/test_seed_data.py` (lines 47–58: ids 5001–5120, count 131, status mix of id ≥ 5001),
    `tests/test_server.py:42,47` (`== 131` orders), `tests/test_tools.py:56` ("every seed row is ai_generated = 1").
  - `callverse/slm/dev_decisions.json` d01/d02 (order 5042) and d06 (order 5017): these are only labels inside
    hand-made SLM decision examples. The SLM code never opens the database (no `db`/`sqlite` in `callverse/slm/`),
    so they keep working. They now name orders that don't exist (cosmetic).
  - Docs: `docs/platform_contract.md:15`, `README.md:93–97`, `docs/platform_P01_P02_summary.md:74` (history).
  - `tests/dev/live_dev_messages.json`: none (as the Brain said).
- **Step 2 builder** `scripts/build_shopnova_sample.py` (new, commented): checks that the 9 files exist and have the
  expected columns (stops otherwise), applies items 3–14, and writes
  `callverse/data/real/shopnova_olist_sample.json` (one row per line, licence note at the top). It runs in 3.5 s.
  Running it twice gives the same file, because it uses seed 2026 and sorted inputs.
- **Rate in `config.yaml`:** `currency: {brl_to_tnd: 0.5625, rate_date: "2026-10-29", rate_source: "Wise mid-market
  rate, read by the Brain on 2026-10-29"}`. Only the builder reads it.
- **Step 4 `seed.py`:** the schema now has `source` and `source_id` on users, products, orders and refunds, a
  `city` column on users and a new `reviews` table. Scripted rows are inserted exactly as before (same values, now
  with named columns) plus `source = 'scripted'`. After them, the real sample is loaded. `generate_data()` (users
  6–25, orders 5001–5120) is **removed**, and `import random` / `sim_start` went with it. Seeding takes 0.23 s.
- **Step 7 proof:** done, see Evidence.
- **Not done (after the stop):** the test updates and new tests (step 6), `docs/platform_contract.md` §2 and README
  text (steps 3/4), `DATA_LICENCES.md` (step 5; the sample file already has the licence note at the top), and the
  step 8 sanity print.

## 3. Evidence
- **Tests: 320 / 325 pass**, 5 fail (`pytest -q`, 184 s):
  | Test | Kind | Why |
  |---|---|---|
  | `test_seed_data::test_counts_and_labels` | seed count | expects 5001–5120 / 120 / 131 |
  | `test_seed_data::test_status_mix_and_cash_on_delivery` | seed count/mix of generated orders | `id >= 5001` mix; real data has no `shipped`/`out_for_delivery` left |
  | `test_server::test_orders_filters_and_summary` | seed count | `== 131` orders |
  | `test_tools::test_labels_on_seed_data` | seed label | "no row with ai_generated = 0", but item 3 makes real orders/reviews `ai_generated = 0` |
  | **`test_seed_data::test_totals_and_refunds_are_consistent`** | **consistency, not a count → STOP** | total must equal the sum of the items; e.g. 11.19 items vs 20.64 total |
- **Why the totals differ:** in the 2,000 sampled orders, Olist payments = item prices for only **27**, and
  payments = item prices + freight for **1,997** (3 others: voucher/instalment rounding). Freight is a median **18%**
  of items + freight. Item 7 (total = payments, item prices converted) therefore leaves the freight with no line.
- **Scripted rows identical: YES.** I dumped orders 4505–4515, users 1–5, products 1–6 and refund 1 (all old columns
  incl. labels) from `main`'s seed and from the new seed, and the two JSON files are byte-identical (`cmp`).
  `scenario_timeline.json` was not touched (md5 8266145c…).
- **Sample (from the builder's output):**
  - Eligible electronics orders: **20,808** (20,823 minus 15 left out: **12** "real story > 90 days" (they can't fit
    the window with real durations), **3** "delivered" with no delivery date). Sample **2,000**.
  - Categories: all 10 start-list names exist; `pc_gamer` is missing from Olist's translation file (known gap,
    named by hand). In the sample (products | order lines): computers_accessories 365 | 654, watches_gifts 292 | 554,
    telephony 269 | 397, electronics 131 | 248, consoles_games 68 | 101, audio 19 | 40, fixed_telephony 19 | 23,
    computers 12 | 22, tablets_printing_image 3 | 8; `pc_gamer` 0 (only 3 products in the whole dataset).
  - Status Olist → ours: delivered → delivered 1,869 · delivered → refunded 79 · shipped → stuck_at_depot 30 ·
    invoiced → processing 13 · processing → processing 5 · canceled → cancelled 4. No `shipped` left: all 30 shipped
    orders' promised dates passed. **No `out_for_delivery`.**
  - Late share (delivered after promised): **115 / 1,948 = 5.9%**. Median delivery is **12 days before** the promise.
  - Stuck at depot: **30** (days late min/median/max 2 / 33 / 65). Processing: 18, **all 18 past their promised date**
    (3 / 30 / 63 days).
  - Cash on delivery (boleto): **404** orders; unpaid right now: 10.
  - Refunds: **79** (rule **R-RET-01**: the order was delivered, so R-REF-03 "not delivered" doesn't fit, and
    R-DMG-01 needs a photo; date = delivery + 2–6 days, inside the 14-day window). **7 are above 300 TND**.
  - Review scores 1–5: 239 / 60 / 185 / 398 / 1,114 (1,996 reviews; 12 orders without a review; latest review of an
    order = the refund signal).
  - Users **1,998**. Repeat buyers: only **2** (max 2 orders each). Cities: Tunis 867, Ariana 308, Ben Arous 289,
    Sousse 142, Sfax 133, Monastir 101, Nabeul 96, Bizerte 62.
  - Products **1,178**. Total TND min / median / max: **6.97 / 53.50 / 1,983.63**.
  - Dates: orders 2026-07-11 … 2026-10-05; last delivery and last review 2026-10-09; nothing after `sim_today`.
    Promise length (order → promised): min / median / max **3 / 24 / 69 days**.
- **Sample file size: 1,708,103 bytes** (~1.7 MB, target was ~1 MB). The seeded DB is 1.1 MB.
- **Raw files not tracked:** `git status` shows nothing under `data/raw/` (git-ignored).
- **0 LLM/API calls:** the builder and seed are pure Python/CSV. No new file in `traces/` (the newest is still
  `run_20261028_200716…`); the tests run offline as always. `.env` was not read and not staged.

## 4. Problems
- **The stop:** total ≠ sum of items for 1,974 / 2,000 real orders, because of freight (see Evidence).
- **Olist promises don't look like ShopNova's.** Real Olist promises are 24 days (median), while
  `company_profile.json` says 3–6 days. Deliveries are usually 12 days early, so only 5.9% are late.
- **The status mix has no "live" orders.** There are no `shipped`/`out_for_delivery` orders, and all 18
  `processing` orders are 3–63 days past their promise. This comes from placing each order at random in the 90-day
  window (item 6): Olist's open orders are old, so after the shift they all look stuck.
- **Real repeat buyers almost vanish:** 2 out of 1,998 users. Random sampling by order rarely picks both orders of
  the same person (item 10 kept them, but the sample removes them).
- **1,178 products for 2,000 orders**, mostly sold once, with names like "Watch item 0187". That's a big, faceless
  catalogue for a small shop. `company_profile.json` still lists the 6 scripted products under `sells`.
- **Agents will see the new columns.** `get_order`/`get_user` use `SELECT *`, so `source`, `source_id` (Olist hash)
  and `city` show up in tool results, the same way `ai_generated`/`scripted` already do. The tool code is unchanged.
- `reports.summary()` still calls the non-scripted orders "generated_orders"; I didn't touch it (code outside the
  task's list). It also runs `get_tracking` once per order (2,000 small queries). The server test still passed in
  time.
- The test suite took 184 s, because each test reseeds 2,000 orders (0.23 s each).

## 5. Questions for the Brain
1. **Freight (blocks step 6).** ⭐ (a) Add one real line per order, `{"product_id": null, "name": "Delivery",
   "qty": 1, "price": <Olist freight, TND>}`, so items + delivery = total for 1,997 / 2,000 orders. The test would then
   allow the 3 voucher/instalment orders a small tolerance, or I list them. (b) Keep item 7 as written and limit the
   consistency check to the scripted orders, adding "total ≥ items" for real orders. (c) Define total = items only
   and drop freight (then total ≠ what the client paid).
2. `tests/test_tools.py::test_labels_on_seed_data` says "every seed row is ai_generated = 1", which item 3 makes
   false by design. May I update it like the count tests, with a comment?
3. `tests/test_seed_data.py::test_status_mix_and_cash_on_delivery` expects all 7 statuses. The real sample has no
   `shipped`/`out_for_delivery`. Should the new test check the real Olist mix instead? Or should item 6 change, for
   example placing open (not delivered) orders closer to `sim_today` so some stay `shipped` on time?
4. Promise length 24 days vs profile 3–6 days: should we accept it and update `company_profile.json`
   (`delivery_promise_days`, `sells`), or rescale promised durations (that would change "real durations")?
5. Repeat buyers: sample by person (`customer_unique_id`) instead of by order, so real repeat buyers stay?
6. Sample is 1.7 MB, not ~1 MB. Is that OK? I can drop the per-row label keys, which the seed could add by table
   (~0.25 MB).
7. `dev_decisions.json` (SLM) names orders 5042 / 5017. Should I rename them to real or scripted order ids (cosmetic)?

## 6. Next step
After your answers, I'll finish step 6: update the 4 count/label tests with comments, resolve the freight question,
and add the new tests (sample loads, ids 10001+, no date after `sim_today`, `source = 'olist'` + `source_id`,
refunds only on late orders with score 1–2, scripted rows unchanged). Then step 3/4 docs (`platform_contract.md` §2
real vs generated columns per table, README), `DATA_LICENCES.md`, the step 8 sanity print (4512, 4515, one on-time,
one late, one stuck real order), and a re-run of the full suite.

---

## Follow-up (2026-10-29, after the Brain's answers approved by Yassine at 09:42) — T15 finished

### 1. In plain words
I applied the 10 answers and finished T15. Each real order now has a "Delivery" line (the real Olist shipping fee),
so its lines add up to its total, except 8 orders where the client paid a little more or less (voucher or
instalment interest). Those 8 are listed below. The sample is now drawn by client, so 31 real repeat buyers keep
all their orders, and no refund goes above 300 TND. All 332 tests pass. The suite now takes 53 s instead of
184 s, because the database is built once and copied for each test.

### 2. Done
- **Builder** `scripts/build_shopnova_sample.py`:
  - Delivery line `{"product_id": null, "name": "Delivery", "qty": 1, "price": <freight TND>}` (item 1).
    Total = sum of the converted lines when the Olist payments = items + freight; otherwise total = the converted
    payment.
  - Sampling by client (item 5).
  - No refund above 300 TND (item 8).
  - Writes `delivery_promise_days` and `sells` into `company_profile.json`, everything else kept, same layout
    (item 4). The new `delivery_promise_days` keeps `min`/`max` and adds `median` (`scripts/data_summary.py` reads
    `min`/`max`).
  - The status mix is unchanged and open orders were not moved (item 3).
- **Tests updated**, each with a T15 comment:
  - `test_seed_data::test_counts_and_labels`: real ids 10001+, 11 + 2,000 orders.
  - `::test_status_mix_and_cash_on_delivery`: the real mix, with no `out_for_delivery`.
  - `::test_totals_and_refunds_are_consistent`: allows exactly the 8 ids below.
  - `test_server::test_orders_filters_and_summary`: 11 + 2,000; limit 500 is now reached.
  - `test_tools::test_labels_on_seed_data`: real rows may be `ai_generated = 0`; scripted and generated rows may not.
- **New tests** (7, in `tests/test_seed_data.py`):
  - `test_real_sample_loads`
  - `test_real_ids_start_at_10001_1001_101`
  - `test_no_date_after_sim_today`
  - `test_real_rows_have_source_and_source_id`
  - `test_refunds_only_on_late_orders_with_score_1_or_2`: also checks the reverse (every late order with a 1–2 star
    review is refunded if ≤ 300 TND, and stays `delivered` if above).
  - `test_scripted_rows_unchanged_since_main`: md5 of the old-column dump taken from `main` 7164f54, plus
    `source = 'scripted'`.
  - `test_delivery_line`
- **Test setup** `tests/conftest.py` (item 9): a session fixture seeds once into a template file, and each test
  gets a `shutil.copyfile` of it. No test file needed a change for this.
- **Docs:**
  - `docs/platform_contract.md` §2: both kinds of seed data, the schema additions, a real-vs-generated column table
    per table, and every conversion rule (categories, sample, dates, status, money, payment, the state → city table,
    the profile fields).
  - `README.md` "Data" section rewritten (incl. how to rebuild the sample).
  - New `DATA_LICENCES.md`: Olist, CC BY-NC-SA 4.0, link, credit line, the derived sample keeps the licence,
    non-commercial university use.
- **Not touched:** the tools (item 10), `callverse/slm/dev_decisions.json` (item 7), agents, prompts, Coordinator,
  policies, Intake, SLM.

### 3. Evidence
- **Tests: 332 / 332 pass** in **53.4 s** (before: 325 tests in 184 s). 7 new tests.
- **New sample** (builder output; two runs give the same file, md5 `10dda77f…`):
  - **Orders: exactly 2,000** (the client that crossed the line landed on 2,000). Eligible 20,808 (left out
    beforehand: 12 "story > 90 days", 3 "delivered without a delivery date").
  - **Users 1,969; repeat buyers 31** (2 orders each; was 2 with sampling by order).
  - Categories (products | order lines): computers_accessories 365 | 648, watches_gifts 287 | 557,
    telephony 285 | 423, electronics 130 | 231, consoles_games 87 | 120, fixed_telephony 21 | 22, audio 18 | 28,
    computers 10 | 18, tablets_printing_image 4 | 8, pc_gamer 1 | 1.
  - Status Olist → ours:
    - delivered → delivered 1,859 · delivered → refunded 90
    - shipped → stuck_at_depot 19 · shipped → shipped 1 (promise still ahead)
    - invoiced → processing 15 · processing → processing 10
    - canceled → cancelled 6
  - Late share (delivered after promised): **147 / 1,949 = 7.5%**.
  - **Stuck: 19** (4–80 days late). Processing: 25, of which 23 are past their promise.
  - Cash on delivery: 434 (8 unpaid now).
  - **Refunds: 90** (R-RET-01, all ≤ 300 TND, max 221.20, sum 5,892.43 TND). **5** late orders with 1–2 stars above
    300 TND stay `delivered`.
  - Review scores 1–5: 269 / 59 / 178 / 383 / 1,100 (1,989 reviews; 21 orders without one).
  - Products 1,208. Total TND min / median / max: 6.97 / 52.22 / 2,026.39. Delivery line min / median / max:
    0.00 / 9.02 / 146.27.
  - Order dates 2026-07-11 … 2026-10-07; last delivery and last review 2026-10-09.
  - Cities: Tunis 816, Ariana 336, Ben Arous 283, Sousse 143, Sfax 130, Monastir 107, Nabeul 101, Bizerte 53.
  - Profile now: `delivery_promise_days {"min": 3, "median": 25, "max": 66}`; `sells` = the 10 categories in
    English, most sold first ("computers accessories", "watches gifts", "telephony", …).
- **The 8 orders where payments ≠ items + delivery** (voucher / instalment interest), as (id, Olist order_id,
  lines TND → total TND):
  - 10261 `91fe2d04…` 30.46 → 34.42
  - 10359 `ddad987b…` 59.16 → 64.00
  - 11014 `ee9dfabe…` 172.97 → 192.44
  - 11631 `bc2c82b0…` 136.14 → 170.45
  - 11644 `5af817dc…` 24.80 → 25.55
  - 11705 `abf1130b…` 258.40 → 279.50
  - 11750 `a800ac03…` 39.59 → 45.73
  - 11914 `f1c86b91…` 31.39 → 32.40

  Your answer said 3. That count was for the old sample (by order); sampling by client gives these 8. The test
  allows exactly these ids.
- **Scripted rows identical: yes.** `cmp` of the before/after dumps is identical, and the new test pins the md5
  (`bab2634b…`) of `main`'s dump.
- **Step 8 sanity** (temporary DB, read tools only):

  | Order | Kind | Lines | Paid | Status | Promised → delivered | days_late | User | Refunds |
  |---|---|---|---|---|---|---|---|---|
  | 4512 | scripted | Wireless Earbuds 59.90 | 59.90 | stuck_at_depot | 2026-10-03 → — | 6 | Sara Ben Ali, `source scripted`, city null | none |
  | 4515 | scripted | 2 × Smart Watch 189.00 | 378.00 | stuck_at_depot | 2026-10-01 → — | 8 | Youssef Trabelsi | none |
  | 10001 | real, on time | Watch item 0001 87.73 + Delivery 7.73 | 95.46 | delivered | 2026-08-03 → 2026-07-23 | 0 (days_since_delivery 78) | Sirine Zouari, Tunis | none |
  | 10055 | real, late | Watch item 0014 86.57 + Delivery 7.73 | 94.30 | delivered | 2026-07-26 → 2026-08-11 | 16 | Anis Baccouche, Tunis | none (its review is not 1–2) |
  | 10012 | real, stuck | Watch item 0006 1,209.38 + Delivery 18.65 | 1,228.03 | stuck_at_depot | 2026-07-21 → — | 80 | Sirine Tlili, Tunis | none |
  | 10018 | real, refunded | Computer accessory item 0003 47.75 + Delivery 6.80 | 54.55 | refunded | 2026-08-07 → 2026-08-15 | 8 | Firas Ben Youssef, Tunis | refund id 2: 54.55, completed, R-RET-01, 2026-08-18, `source generated` |

  The tool results now also carry `source`, `source_id` and `city` (item 10: left for T14).
- **Sizes:** sample file 1,828,350 bytes (was 1,708,103: the Delivery lines; item 6 OK). Seeded DB 1.26 MB.
- **Raw files not tracked:** `git ls-files data/raw` = 0.
- **0 LLM/API calls:** builder, seed and tests are offline; no new file in `traces/`. `.env` not read.

### 4. Problems
- **Correction to my first report:** "nothing after `sim_today`" was true for events (order, delivery, review,
  refund dates) but **not for promised dates**. 309 real *delivered* orders (delivered early) and 3 open real
  orders have a promise after 2026-10-09 (latest 2026-11-21). This follows from keeping real durations, and the
  scripted 4510 does the same. The new date test checks events only, with a comment.
- Olist reuses a few `review_id`s across orders (11 ids appear twice), so `reviews.source_id` is not unique. The
  test checks uniqueness only for orders, users and products.
- The profile's `description` still lists earbuds, phone cases, … (kept, as item 4 said), while `sells` now lists
  categories like "watches gifts" or "tablets printing image" (Olist's literal English names).
- Open real orders look old: stuck orders are up to 80 days late, and 23 of 25 `processing` orders are past their
  promise. That's the real mix kept on purpose (item 3).
- A repeat buyer's two orders are placed in the window independently, so their real order (first/second purchase)
  and the gap between them are not kept. Only each order's own durations are.
- Yassine's local `callverse/data/shopnova.db` (git-ignored) still has the old schema. After the merge, run
  `python -m callverse.data.seed` once (connect() only seeds when the file is missing). Tests use their own copy.
- `reports.summary()` still calls the real orders "generated_orders" (not in this task's file list).

### 5. Questions for the Brain
1. `sells` uses Olist's literal English category names. Should T14 (or a profile task) reword them ("computer
   accessories", "watches") and the `description`?
2. The 8 payment ≠ lines orders (not 3): is listing them by id in the test OK, as done?

### 6. Next step
Review and merge `feature/shopnova-real-data` (Yassine + Dali), then reseed the local DB. T14: hide `source`,
`source_id` and `city` from tool results (item 10), plus the core fixes already planned.
