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
