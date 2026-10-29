# T15 — ShopNova on real data: replace the 120 generated orders with 2,000 real Olist orders

## Why
Plan A (Yassine, 2026-10-28): build ShopNova and Atlas Travel as realistic companies on **real data** before the
benchmarks and T14. Research: `claude/company_data_research.md` (project knowledge). ShopNova = **Olist Brazilian
E-Commerce** (Kaggle `olistbr/brazilian-ecommerce`, **CC BY-NC-SA 4.0**): ~100k real orders with real promised vs real
delivery dates, statuses, payments, reviews. Today ShopNova has 11 scripted demo orders (4505–4515) + 120 AI-generated
placeholder orders (5001–5120). The generated ones are replaced by real ones; the scripted ones stay exactly as they are.
All details were agreed with Yassine on 2026-10-29 (20 + 4 items, all the Brain's ⭐). Dali (platform lane) said OK.
T14 stays reserved for the core fixes (cancellation rule, etc.).

## Hard limits
- **0 LLM / API calls** (pure data work). Never run or read `tests/data/*` (held-out). Never read or stage `.env`.
- **Raw Olist files never go into git** (`data/raw/olist/`, added to `.gitignore`). Yassine downloads them by hand.
- **Scripted data stays byte-identical:** the 11 orders 4505–4515, users 1–5, products 1–6, refund 1 (order 4506),
  `scenario_timeline.json`, all scripted flags. Prove it (step 7).
- No change to agents, prompts, Coordinator, policies, Intake, SLM, tools' behaviour. Only: data builder, `seed.py`,
  schema additions, `config.yaml` (rate), docs, tests about the seed data.
- If a needed Olist file is missing or its columns differ from below: stop and report.

## Inputs (Yassine puts them in place before the run)
`data/raw/olist/` with the 9 CSV files of the Kaggle zip: `olist_orders_dataset.csv`, `olist_order_items_dataset.csv`,
`olist_order_payments_dataset.csv`, `olist_order_reviews_dataset.csv`, `olist_customers_dataset.csv`,
`olist_products_dataset.csv`, `olist_sellers_dataset.csv`, `olist_geolocation_dataset.csv`,
`product_category_name_translation.csv`.

## What to do
0. **Git.** `git fetch`, `git checkout main`, `git pull` (main = 7164f54 or later). Branch `feature/shopnova-real-data`.
   Commit this task file and `tasks/NEXT.md` (IN PROGRESS) first. Add `data/raw/` to `.gitignore`.
1. **Check first (report it):** grep the repo (code, tests, docs, `tests/dev/`) for anything that depends on the
   generated orders 5001–5120 or generated users 6–25 (ids, counts). Known: `tests/test_seed_data.py` lines ~47–58.
   The practice set `tests/dev/live_dev_messages.json` uses none (checked by the Brain). If code (not tests) depends on
   them, stop and report.
2. **Builder script** `scripts/build_shopnova_sample.py` (reads `data/raw/olist/`, writes the processed sample
   `callverse/data/real/shopnova_olist_sample.json`, ~1 MB; fixed random seed **2026**, same output on every run).
   Rules (approved items in brackets):
   - **Categories (4):** only orders whose items are **all** in electronics-shop categories. Start list (Portuguese
     names; confirm with the translation file and list the final set + counts): `telefonia`, `telefonia_fixa`,
     `informatica_acessorios`, `eletronicos`, `audio`, `pcs`, `pc_gamer`, `tablets_impressao_imagem`,
     `relogios_presentes`, `consoles_games`.
   - **Sample (3):** **2,000** orders drawn at random (seed 2026) from those orders. Keep Olist's real status mix
     (report it; do not force more late/stuck orders).
   - **Ids (5):** orders get new numbers from **10001**, the Olist `order_id` kept in a new `source_id` column.
     Users from **1001**, products from **101** (new numbers; Olist ids in `source_id`).
   - **Users (10 + extra 3):** **one generated user per real Olist user** (`customer_unique_id`), so real repeat buyers
     stay. Name = generated Tunisian name, email/phone generated like today's seed; `ai_generated = 1` for the user row.
   - **Places (8):** Brazilian state → one of the 8 cities in `company_profile.json` (`cities_served`), by a fixed,
     documented table (e.g. by state population rank). Stored in a new users `city` column.
   - **Dates (6):** shift each order so it sits in the **90 days before `sim_today` (2026-10-09)**, keeping its real
     durations (purchase → estimated delivery → delivered). No date after `sim_today`. Promised date = Olist
     `order_estimated_delivery_date` (shifted). Document the method.
   - **Statuses (11):** `delivered` → delivered; `shipped` → shipped, or **`stuck_at_depot` if its shifted promised
     date is before `sim_today`**; `canceled` / `unavailable` → cancelled; `created` / `approved` / `invoiced` /
     `processing` → processing. `out_for_delivery`, `refunded` only as rules below create them.
   - **Money (7):** one fixed rate **1 BRL = 0.5625 TND** (Wise mid-market, read by the Brain on 2026-10-29), saved
     in `config.yaml` with its date and source; no live lookup. Order total = sum of the Olist `payment_value` of the
     order, converted, rounded to 0.01. Item prices converted the same way.
   - **Payment (12):** Olist `boleto` → cash on delivery; `credit_card`, `debit_card`, `voucher` → card. Same rules as
     today's seed: cash on delivery shows `paid = 0` until delivered; cancelled orders `paid = 0`.
   - **Products (9):** one products row per Olist product used; name generated from its English category (e.g.
     "Audio item 0042"), price = its median item price in the sample (TND); `ai_generated = 1` on the name only
     (documented).
   - **Reviews (13):** new `reviews` table: `id`, `order_id`, `score` (1–5), `created_at` (shifted). **No review text**
     (Portuguese). Real rows: `ai_generated = 0`.
   - **Gaps (14), generated from real signals and marked `ai_generated = 1`:** carrier (Aramex / Rapid-Poste) and
     tracking number as in today's seed for orders past processing; stock per product; **refunds only on real signals:**
     a delivered order that arrived after its promised date **and** has a real review score of 1–2 gets one completed
     full refund under the policy rule that fits it (pick the rule id from `callverse/kb/policies_shopnova.json`, say
     which and why); its order status becomes `refunded`. No other refunds.
3. **Labels:** real-data rows get `ai_generated = 0`, `scripted = 0`, plus a new `source` column (`olist` /
   `generated` / `scripted`). Write in `docs/platform_contract.md` (section 2) exactly which columns are real and
   which are generated, per table.
4. **`seed.py`:** loads the scripted data exactly as today, then the real sample from
   `callverse/data/real/shopnova_olist_sample.json`. The old generator (`generate_data`, users 6–25, orders
   5001–5120) is **removed** (one source). Schema additions (new columns `source`, `source_id`, users `city`, table
   `reviews`) also written into `docs/platform_contract.md`. Scripted rows get `source = 'scripted'`.
5. **Licence:** `DATA_LICENCES.md` at the repo root: Olist, CC BY-NC-SA 4.0, link, credit line, "the processed
   sample in `callverse/data/real/` is derived from Olist and keeps the same licence; non-commercial university use".
   Also a short note at the top of the sample file.
6. **Tests:** run the full offline suite: **all must pass**. Update only tests that counted the old 120 orders /
   20 users (`tests/test_seed_data.py`), with a comment why. Add tests: sample loads; ids 10001+; no date after
   `sim_today`; every real order has `source = 'olist'` and a `source_id`; refunds only on late orders with score 1–2;
   scripted rows unchanged.
7. **Proof the scripted data did not change:** dump the scripted rows (orders 4505–4515, users 1–5, products 1–6,
   refund 1) before (from `main`) and after, compare (ignore only the new `source` column). Must be identical.
8. **Quick sanity (no LLM):** with the new database, call the read tools / helpers the agents use (`get_order` etc.)
   on 4512, 4515 and 3 real orders (one delivered on time, one late, one stuck) and print the results.

## Checks (with numbers)
- Tests x/y (all pass); new tests listed.
- Sample: 2,000 orders; final category list + counts; status counts (Olist original → ours); late share
  (delivered after promised); stuck count; cash-on-delivery count; refunds count; review score counts 1–5;
  users count and repeat buyers; products count; total TND min / median / max; date range.
- Scripted rows identical: yes/no.
- Sample file size; raw files not tracked (`git status` clean of `data/raw/`).
- 0 `llm_call` lines; `.env` not read.
- One sentence each: does the real data look like a believable Tunisian electronics shop? what looks odd?

## Time box and stop rule
1.5 h. Stop and report if: an Olist file is missing or different, code (not tests) depends on orders 5001–5120,
a scripted row changes, a test fails that is not a seed-count test, or any LLM/API call happens.

## Git (approved by Yassine, 2026-10-29)
Commit and push `feature/shopnova-real-data` (builder script, sample file, `seed.py`, schema/doc changes,
`DATA_LICENCES.md`, `config.yaml` rate, tests, `.gitignore`, task file, report, `tasks/NEXT.md`). **No merge into
`main`** (merge needs Yassine's and Dali's OK after review). Write `tasks/T15_report.md` (In plain words · Done ·
Evidence · Problems · Questions for the Brain · Next step) and set `tasks/NEXT.md` to WAITING FOR REVIEW.
