# Platform report — P01 + P02 (ShopNova)

**For:** Yassine · **From:** Dali · **Date:** 2026-10-20 · **Branch:** `platform` (pushed, not merged into `main`)
Commits: `70a0e41` + `3874226` (P01), `95d3c2b` + `1797a62` (P02). Full reports: `tasks/P01_report.md`, `tasks/P02_report.md`.

## In one paragraph
The ShopNova platform now has everything that scenarios S1, S2 and S3 need on the company side:
- the 8 policies, written in one file that the code can check;
- a database that records refunds (with the rule that justified them), notification subscriptions and order events;
- write functions that only the Coordinator can call;
- a Layer 3 finance stub;
- a demo script that plays S1-S3 without any LLM.

Agents A and B, the Coordinator and the notifier are untouched. They stay in your core tasks.

## What was built

| Part | Where | What it does |
|---|---|---|
| Policies | `callverse/kb/policies_shopnova.json`, `callverse/kb/policies.py` | 8 rules (`id, title, text, condition, ai_generated`). `load_policies()`, `get_policy()`, `check_condition(condition, facts)`; the checker uses Python's parser (`ast`), **no `eval()`** |
| DB access | `callverse/data/db.py` | One place opens the DB. Tests switch it to a temporary file. |
| Schema | `callverse/data/seed.py` | `ai_generated` / `scripted` on all tables. `refunds` + `rule_id, proposal_id, created_at`. Status codes: `processing, shipped, stuck_at_depot, out_for_delivery, delivered, refunded, cancelled`. New tables `subscriptions`, `events`. |
| Read tool | `callverse/tools/shopnova_tools.py` | `get_refunds(order_id)` → `{order_id, refunds, refunded_total}`. **Not on any allow-list yet**: add it to B in your task. |
| Writes (Coordinator only) | `callverse/data/writes.py` | `create_refund` (status `approved`), `create_subscription` (status `waiting`, R-NOT-01 events only), `set_order_status` (adds an `events` row for notification events; sets `delivered_date` on `delivered`). Outside `tools/`, on no allow-list (tested). Each call traced as `db_write` / `db_write_refused`. |
| Layer 3 stub | `callverse/data/layer3.py` | `layer3_decide(order_id, amount, reason)`: ≤ 300 `not_required`, ≤ 500 `approved` by finance, > 500 `refused`. 300 is read from R-ESC-01, 500 from `config.yaml`. No DB write. |
| Demo | `scripts/demo_platform.py`, `scripts/advance_status.py` | Plays S1, S2, S3 + extras with no API key. This is the backup if Groq is down on demo day. |
| Contract | `docs/platform_contract.md` | §2, §3, §4, §5, §7 updated to match. |

## Evidence (checked again by me, not only by the builder)
- Tests: **42 / 42 pass** (were 14 before P01).
- The real `callverse/data/shopnova.db` is **unchanged** after the test suite and after the demo (same MD5).
- `.env` and `.db` files are not committed.
- Demo output with no API key (exit 0):
  - S1: 4512 refund of 59.90 TND **APPROVED** under R-REF-03 (Layer 3 not required).
  - S2: 70.00 **SENT BACK** by R-REF-05; corrected 59.90 **PASSES**.
  - S3: subscription `delivered` → order moves `out_for_delivery` → `delivered` → **1 notification ready**.
  - Extra: second refund on 4506 **REFUSED** (R-REF-05); Layer 3: 350 **approved**, 600 **refused**.
- Safety check of `check_condition`: `__import__("os")`, attribute access and function calls are all refused.

## Changes you should know about
1. **4512 status is now `stuck_at_depot`** (it was `stuck at depot`), and the old test was updated. Agent A was not
   run live with the new code, so check that its answer still reads well.
2. **R-REF-05 condition** is now `amount <= paid - refunded_total` (it was `amount <= paid`). Without this, 4506
   could be refunded twice.
3. **Old local DB files** have no `events` / `subscriptions` tables. Run `python -m callverse.data.seed` once after pulling.
4. **Tests no longer reset the real DB.** Each test uses its own temporary file.

## Decisions needed from you
1. **Policy wording**: review the 8 texts in `callverse/kb/policies_shopnova.json`, including the new R-REF-05 text.
2. **Coordinator**: should it reuse `check_condition()` from `callverse/kb/policies.py`? I recommend yes, so the
   conditions stay written only in the policy file.
3. **`create_refund` checks**: today it only checks that the order exists and the amount is > 0. The R-REF-05
   amount check is left to the Coordinator. Do you want a second check inside `create_refund` as a safety net?
4. **`set_order_status`**: should it refuse backwards jumps (e.g. `delivered` → `shipped`)? Today it only refuses unknown codes.
5. **4506 refund row** has `scripted = 1`, because it is part of scripted case 4506. Is that OK?
6. **Layer 3 demo extra** uses order 4513 with 350 / 600 TND, more than its 189 paid. That's fine to test the stub,
   but don't present it as a story. A real > 300 TND case would need a scripted order above 300.

## For your core task (Agent B + Coordinator)
- Add `get_refunds` to B's allow-list in `registry.py`.
- Coordinator flow: read facts with the platform tools → `check_condition` → `layer3_decide` when amount > 300 →
  `create_refund` / `create_subscription` on approve.
- Notifier: read `events` rows that match `waiting` subscriptions (same query as the S3 demo) and mark them `sent`.

## How to check it yourself
```bash
git fetch && git checkout platform
python -m callverse.data.seed
python -m pytest -q
python scripts/demo_platform.py
```

## Next
P03 (approved with your notes): company profile, 120 generated orders (5001-5120), `days_since_delivery`,
data summary script. It starts after your review of P01.
