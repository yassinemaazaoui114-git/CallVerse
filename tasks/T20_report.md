# T20 report — Atlas Travel: company data on real datasets

## In plain words
Atlas Travel, our second company, now has its own data. It holds 2,000 real hotel bookings and 2,000 real flights,
moved to 2026 and priced in dinars. It also has generated Tunisian clients, 10 hand-written demo cases and 14 rules.
Nothing uses this data yet: no app, no agent, no routing, and ShopNova is unchanged. Two results need a decision: the
refund step produced **0 refunds**, because every real case is either not allowed or above 300 TND, and the 20 % room
rule can't pay anything on real bookings, because those clients are recorded as having paid 0.

## Done
- `callverse/data/atlas/`: `schema.py` (9 tables, allowed codes), `seed.py` (scripted data, builds `atlas.db`), `db.py`
  (`connect()`, `use_db()`, seeds if missing), `reads.py` (the 7 read functions).
- `scripts/build_atlas_sample.py` → `callverse/data/real/atlas_sample.json` + `callverse/data/atlas_profile.json`.
- `callverse/kb/policies_atlas.json`: 14 rules `AT-…`, using ShopNova's `check_condition` (no change to it).
- `tests/test_atlas_data.py`: 123 tests. They run offline; the builder is tested on tiny fake raw files.
- `DATA_LICENCES.md` (both datasets, what was generated, the two rates, the fare source) and `README.md`.
- No ShopNova file changed. Git: branch `feature/atlas-real-data`, pushed, no merge into `main`.

## Evidence
- **Tests: 633/633** (510 existing, unchanged + 123 new); 0 API calls.
- **Sample file:** 2,854,384 bytes (2.85 MB). Built in 33 s. Rebuilt a second time: same SHA-256 for the sample
  (`6B9A108C…FA71C4`) and the same for the profile.
- **Raw files not tracked:** `git ls-files data/raw` = 0 files; `atlas.db` and `data/raw/` are ignored by `.gitignore`.

**Real mix, hotels** (sample of 2,000 vs full file of 119,390)

| | Sample | Full file |
|---|---|---|
| Cancelled | 37.45 % | 36.03 % |
| No-show | 1.50 % | 1.01 % |
| Room changed | 12.00 % | 12.49 % |
| No deposit | 87.05 % | 87.65 % |
| Refundable | 0.15 % | 0.14 % |
| Non-refundable | 12.80 % | 12.22 % |

Status in the sample: stayed 842, cancelled 749, confirmed 379, no-show 30.

**Real mix, flights** (sample of 2,000 vs full file of 5,819,079; 5,318,560 usable)

| | Sample | Full file |
|---|---|---|
| Cancelled | 1.80 % | 1.54 % |
| Delayed ≥ 15 min | 18.95 % | 18.28 % |
| Cancelled: carrier | 0.50 % | 0.43 % |
| Cancelled: weather | 0.95 % | 0.84 % |
| Cancelled: air system | 0.35 % | 0.27 % |
| Cancelled: security | 0 % | 0.0004 % |

Status in the sample: on time 1,585, delayed 379, cancelled 36.

**Money:** hotel stay min / average / max = 6.72 / 1,225.41 / 11,776.60 TND. Flight price min / average / max =
566.44 / 1,156.74 / 2,832.21 TND. **Generated refunds: 0, total 0.00 TND.**

**The 10 scripted bookings** (rule tests: all pass)

| Id | Case | Rules that hold (tested) |
|---|---|---|
| 7001 | Hotel, no deposit, cancelled 9 days before, paid 0 | AT-HOT-01 |
| 7002 | Hotel, non-refundable, cancelled, paid 380.00 | AT-HOT-03 |
| 7003 | Hotel, stayed, room A instead of D, paid 360.00 → 72.00 | AT-HOT-04, AT-REF-01 |
| 7004 | Flight 3 h 20 late, carrier, 1,190.7 km | AT-FLT-03, AT-FLT-05 |
| 7005 | Flight cancelled, carrier, told the same day | AT-FLT-01, AT-FLT-02 |
| 7006 | Flight left 5 h 30 late, air system cause | AT-FLT-04, AT-FLT-05, AT-FLT-06 |
| 7007 | Flight 1 h late | none (no compensation) |
| 7008 | Flight cancelled for weather | AT-FLT-01, AT-FLT-06 |
| 7009 | Hotel refundable, 450.00, cancelled 5 days before | AT-HOT-02, AT-ESC-01 |
| 7010 | Future flight with a wheelchair request | AT-AST-01 |

**How often the rules hold on the real rows:** AT-FLT-01: 36, AT-FLT-02: 10, AT-FLT-03: 11, AT-FLT-04: 9, AT-FLT-05: 41,
AT-FLT-06: 147, AT-HOT-01: 484, AT-HOT-02: **0**, AT-HOT-03: 253, AT-HOT-04: 171, AT-HOT-05: 30.

## Problems
1. **0 generated refunds (step 8).** The code and its tests work, but no real row qualifies. The cheapest fare is
   566.44 TND (0.5 × $377 × 3.005), so a flight refund can never be ≤ 300 TND. The 3 refundable hotel bookings in the
   sample were not cancelled. The test on the database passes only because it has nothing to check, so the refund
   logic is tested directly instead.
2. **AT-HOT-04 cannot pay on real rows.** All 171 real cases are no-deposit stays with `paid_tnd = 0` (choice b), so
   AT-REF-01 allows 0 TND. This is why I gave scripted case 7003 a paid deposit.
3. **AT-HOT-02 has no real case;** only 7009 tests it, and 2 of 117,182 usable rows in the whole file would qualify
   for a refund ≤ 300 TND.
4. **Data quirks left out before drawing, all documented in the builder:** 2,208 hotel rows (0 nights, price of 0 or
   less, or 0 adults), October 2015 flights (486,165 rows: numeric airport codes unknown to `airports.csv`) and diverted
   flights (15,187 rows: no arrival delay). October had fewer delays and cancellations than other months.
5. **Odd real data kept:** 253 of 256 non-refundable bookings are cancelled (the full file has the same pattern).
   One stay is 6.72 TND and one is 11,776.60 TND. No-shows are slightly high in the sample by chance (1.50 % vs 1.01 %).
6. **Rule conditions check who qualifies, not how much.** The compensation bands and the "hotel night if the new
   departure is the next day" part of AT-FLT-05 are only in the rule text; the Coordinator task must compute them.
7. **AT-AST-01 is an approximation:** `hours_before_departure` counts from the start of today, not from the moment of
   the request. `reads.py` uses the shared `sim_today()`, so it reads ShopNova's clock.

## Questions for the Brain
1. **Refunds:** keep 0 generated refunds? I recommend yes: those cases stay open for demos, and the numbers are honest.
   If you want rows, the limit or the fare floor must change, and that is a rule decision.
2. **AT-HOT-04:** should a finished no-deposit stay count as paid (`paid_tnd = total_tnd`), since the client paid at the
   hotel? I recommend yes; otherwise the rule works only for deposits. It would change `paid_tnd` on 839 real stays
   and the paid-rule test.
3. **Please check these 5 choices where the task was unclear or did not fit the data:**
   - **Arrival dates:** one shift cannot fit 2 years of arrivals into a 6-month window, so each booking gets its own
     random arrival date, limited so that nothing happens after today. Cancellations and no-shows therefore keep their
     status, and the task's "otherwise confirmed" case for cancellations can never happen, so there is no code for it.
     Seasons are lost.
   - **Stays still running on 2026-10-09** are `confirmed`, not `stayed`. The task only named arrivals after today.
   - **AT-REF-01** says "refund or compensation" and also "(refunds only)". I applied it to refunds only, because a
     fixed compensation can be more than the ticket. The rule text says so.
   - **`proposals`** has ShopNova's columns, so no `source` / `source_id`. The task says both "every table has them"
     and "same columns as ShopNova's".
   - **`main_delay_cause`** uses the same 4 codes as `cancellation_reason`; a tie goes to the carrier, so the client
     keeps the right.
4. **Rule count:** `tasks/NEXT.md` says 13 rules, but the approved list in the task has 14. I built the 14.

## Next step
Review and merge `feature/atlas-real-data` (Yassine + the Brain), after answering questions 1 and 2. Then the routing
task can connect Atlas: its tools and allow-lists, its policy-search index, and routing by company.
