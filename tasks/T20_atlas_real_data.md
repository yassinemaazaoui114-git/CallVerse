# T20 — Atlas Travel: company data on real datasets (hotels + flights)

## Why
The brief needs **at least 2 sectors**. ShopNova (e-commerce) runs on real Olist data (T15). Atlas Travel (hotel stays +
flights) does not exist in the code yet. T20 builds **Atlas's company data only**: its own database, real + scripted
data, company profile, rules file, read functions and tests. No app, no agents, no routing by company (later tasks).
Research: `claude/company_data_research.md` (Brain). All details approved by Yassine on 2026-10-30 (18 build items +
13 rules + 3 rule choices + the Brain's implementation choices, all ⭐).

## Hard limits
- **No change** to ShopNova's data, schema, rules, tools, agents, prompts, Coordinator, Intake, SLM, apps. All 510
  existing tests must still pass unchanged.
- **Raw files never go into git** (`data/raw/atlas/`, already covered by `data/raw/` in `.gitignore`). Yassine
  downloads them by hand. Never read or stage `.env`. No API calls (this task needs no LLM at all).
- Every generated value is labelled (`ai_generated = 1`) and documented in the builder script; real rows keep a
  `source` + `source_id`.

## Inputs (downloaded by Yassine)
- `data/raw/atlas/hotel_bookings.csv` — **Hotel Booking Demand** (Antonio, Almeida, Nunes 2019, *Data in Brief*,
  DOI 10.1016/j.dib.2018.11.126; Kaggle `jessemostipak/hotel-booking-demand`), **CC BY 4.0**.
- `data/raw/atlas/flights.csv`, `airlines.csv`, `airports.csv` — **2015 Flight Delays and Cancellations** (US DOT /
  BTS; Kaggle `usdot/flight-delays`), **CC0**.
If a file is missing or its columns differ from what is described below: stop and report.

## What to do
0. **Git.** `git fetch`, `git checkout main`, `git pull` (must be **4580146** or later). Branch
   `feature/atlas-real-data`. Commit this task file + `tasks/NEXT.md` (IN PROGRESS) first.

1. **Where the code lives** (same patterns as ShopNova): `callverse/data/atlas/` with `schema.py` (tables + allowed
   codes), `seed.py` (`python -m callverse.data.atlas.seed` builds `callverse/data/atlas.db`, git-ignored by `*.db`),
   `db.py` (`connect()`, `use_db(path)` for tests, seeds if missing), `reads.py` (read functions only);
   `callverse/data/atlas_profile.json`; `callverse/kb/policies_atlas.json`; builder script
   `scripts/build_atlas_sample.py` → processed sample `callverse/data/real/atlas_sample.json` (committed, a few MB,
   fixed seed **2026**, same output on every run).

2. **Tables** (`atlas.db`; every table has `source`, `source_id`, `ai_generated`, `scripted` like ShopNova):
   `users` (id, name, email, phone `+216 XX XXX XXX`, city) · `hotels` (2 rows: **Atlas City Hotel — Lisbon** and
   **Atlas Resort Hotel — Algarve**, from the data's "City Hotel" / "Resort Hotel") · `hotel_bookings` (id, user_id,
   hotel_id, booked_date, arrival_date, nights, adults, children, meal, room_reserved, room_assigned, deposit_type
   `no_deposit` / `refundable` / `non_refundable`, price_per_night_tnd, total_tnd, paid_tnd, status `confirmed` /
   `stayed` / `cancelled` / `no_show`, cancelled_date, special_requests) · `flights` (id, carrier, carrier_name,
   flight_number, origin, origin_city, destination, destination_city, distance_km, scheduled_departure,
   departure_delay_min, arrival_delay_min, cancelled 0/1, cancellation_reason `carrier` / `weather` / `air_system` /
   `security` / NULL, main_delay_cause, status `scheduled` / `on_time` / `delayed` / `cancelled`) ·
   `flight_bookings` (id, user_id, flight_id, booked_date, seat_class `economy`, price_tnd, paid_tnd, status
   `confirmed` / `flown` / `cancelled`, notice_days) · `refunds` (id, booking_type `hotel` / `flight`, booking_id,
   amount, status, rule_id, proposal_id, created_at) · `compensations` (same shape, **empty at seed**) ·
   `assistance_requests` (id, flight_booking_id, kind, status, created_at) · `proposals` (same columns as ShopNova's,
   for the Coordinator later; empty at seed).

3. **Hotels (real):** 2,000 bookings drawn at random (seed 2026) from both hotels, **keeping the real mix** of
   cancellations, deposit types, room changes and no-shows. Ids **20001+**, `source = 'hotel_booking_demand'`,
   `source_id` = the CSV row number.
   - **Money:** `adr` (EUR / night) × **3.358** TND (Wise, 2026-10-30) → `price_per_night_tnd`; total = per night ×
     nights (weekend + week nights). **Payment (choice b):** `no_deposit` → paid 0 (pays at the hotel);
     `refundable` and `non_refundable` → paid = total at booking.
   - **Dates:** shift so the sample's arrivals fall in **2026-07-11 → 2026-12-31**, keeping each booking's real lead
     time and stay length. **Status must be possible on 2026-10-09** (sim today): an arrival after today becomes
     `confirmed` (it was "Check-Out" in 2015-2017); `no_show` only for past arrivals; a cancellation keeps its shifted
     cancellation date only if it is on or before today, otherwise the booking is `confirmed`.
4. **Flights (real):** 2,000 flights drawn at random (seed 2026) from `flights.csv`, **keeping the real mix** of
   on-time / delayed / cancelled, with names from `airlines.csv` / `airports.csv`. Ids = **numbering from 1**,
   `source = 'usdot_2015'`, `source_id` = carrier + flight number + original date.
   - **Dates:** all sampled flights shifted into the **60 days before sim today** (past flights keep their real
     delays / cancellations). Future trips come only from hotel bookings and the scripted bookings.
   - `distance_km` = `DISTANCE` (miles) × 1.609. `cancellation_reason`: A → carrier, B → weather, C → air_system,
     D → security. `main_delay_cause` = the largest of AIRLINE_DELAY / LATE_AIRCRAFT_DELAY (carrier side) vs
     WEATHER_DELAY / AIR_SYSTEM_DELAY / SECURITY_DELAY (extraordinary side). Status: cancelled; delayed if arrival
     delay ≥ 15 min; else on_time.
5. **Flight bookings (generated on real flights):** one booking per sampled flight, ids **30001+**,
   `ai_generated = 1`, one generated Tunisian user each. `booked_date` = flight date − a lead time drawn from the
   real hotel lead-time distribution (documented); `notice_days` = 0 for real cancellations (the file has no notice
   date). **Price:** $377 (BTS 2015 average domestic fare) × (distance ÷ the sample's average distance), kept between
   0.5× and 2.5×, × **3.005** TND per USD (Wise, 2026-10-30); paid in full at booking.
6. **Users:** one generated Tunisian user per hotel booking and per flight booking (names, emails, phones, one of
   ShopNova's 8 cities), ids **101+**; plus **5 scripted Atlas users ids 1–5** with new fictional Tunisian names
   (not ShopNova's).
7. **Scripted demo bookings 7001–7010** (`source = 'scripted'`, `scripted = 1`), dates around 2026-10-09:
   7001 hotel, no deposit, cancelled before arrival (free) · 7002 hotel, non-refundable, cancelled (no refund) ·
   7003 hotel, stayed, room assigned ≠ reserved (20 % rule) · 7004 flight delayed 3 h 20 min on arrival, carrier cause
   (compensation) · 7005 flight cancelled, carrier cause, told the same day (refund or new flight + compensation) ·
   7006 flight departed 5 h 30 min late (refund right) · 7007 flight 1 h late (no compensation) · 7008 flight cancelled
   for weather (refund or new flight, no compensation) · 7009 hotel refundable stay **above 300 TND** cancelled 5
   days before arrival (finance) · 7010 future flight with a **wheelchair assistance** request (for agent C later).
   Each scripted booking is pinned by a test (ids, amounts, statuses never change silently).
8. **Generated refunds (item 14):** a refund row (status `completed`) for every real cancellation **that the rules
   allow** and that is **≤ 300 TND** (refundable hotel deposits cancelled ≥ 2 days before arrival; carrier-cancelled
   flights); larger or not-allowed cases have no refund (open cases for later demos). `ai_generated = 1`.
   No compensation rows at seed. No reviews.
9. **Rules file `callverse/kb/policies_atlas.json`** (same format as ShopNova's: id, title, text, condition), ids
   prefixed `AT-` (choice c). Approved list (EUR → TND at 3.358):
   - **AT-FLT-01** Cancelled flight: the user chooses one — a full refund of the ticket, or a new flight (the next one
     or a later date).
   - **AT-FLT-02** Compensation for a cancellation: 839.50 / 1,343.20 / 2,014.80 TND for ≤ 1,500 km / 1,500–3,500 km /
     > 3,500 km; not paid if told 14 or more days before, or for an extraordinary cause (AT-FLT-06).
   - **AT-FLT-03** Compensation for a long delay: arrival 3 h or more late → the same amounts; for > 3,500 km:
     1,007.40 TND for 3–4 h, 2,014.80 TND for 4 h or more; not paid for an extraordinary cause.
   - **AT-FLT-04** Delay of 5 h or more at departure: the user may cancel the trip and get a full refund.
   - **AT-FLT-05** Meals while waiting: a meal voucher after 2 h (≤ 1,500 km) / 3 h (1,500–3,500 km) / 4 h (> 3,500 km)
     of delay; a hotel night if the new departure is the next day.
   - **AT-FLT-06** Extraordinary causes (weather, air traffic control / air system, security): no compensation;
     refund or a new flight still apply. Decided from the real cause codes (step 4).
   - **AT-AST-01** Special assistance (e.g. wheelchair): free, requested at least 48 h before departure.
   - **AT-HOT-01** No deposit: pay at the hotel; cancelling before arrival is free (nothing to refund).
   - **AT-HOT-02** Refundable deposit: full refund if cancelled at least 2 days before arrival; no refund after that.
   - **AT-HOT-03** Non-refundable: no refund after cancelling.
   - **AT-HOT-04** Room different from the one booked: 20 % of the stay refunded.
   - **AT-HOT-05** No-show: no refund.
   - **AT-REF-01** A refund or compensation can never be more than paid − already refunded (refunds only).
   - **AT-ESC-01** Any refund **or compensation** above 300 TND needs finance approval (Layer 3). (So every
     compensation goes to finance: choice a.)
   Conditions are written with the same `check_condition` mini-language as ShopNova (no eval), on facts the read
   functions return (e.g. `cancelled`, `cancellation_reason`, `arrival_delay_min`, `distance_km`, `notice_days`,
   `deposit_type`, `days_before_arrival`). Add rule tests on the scripted bookings (each rule true / false where
   expected). The policy-search index for Atlas is **not** built in this task (routing task).
10. **Company profile `atlas_profile.json`:** name Atlas Travel, domain travel, description (agency in Tunis selling
    hotel stays in Portugal and flights in the US, for Tunisian travellers; AI customer center), hotels, airlines in
    the sample, currency TND, payment methods (card; pay at hotel), support channels and languages like ShopNova,
    `ai_generated: true`. Facts (delay rates, cancellation rates, average prices) **computed from the sample**.
11. **Read functions** (`reads.py`, read-only, never in an agent allow-list yet): `get_user`, `get_hotel_booking`,
    `get_flight_booking` (with its flight's facts), `get_flight`, `get_refunds(booking_type, id)`,
    `user_bookings(user_id)`, `summary()` (counts by status, delay / cancellation rates, money totals). Tool results
    must **not** expose `source`, `source_id`, `city` or payment details (T14 rule, applied from the start here).
12. **`DATA_LICENCES.md`:** add both datasets with full credit (authors, DOI, CC BY 4.0; US DOT / BTS, CC0), what was
    taken, what was generated, the two rates and the fare source (BTS, 2015 average domestic fare $377).
13. **Tests (offline, all pass, 0 API):** schema + allowed codes; counts (2,000 hotel, 2,000 flights, 2,000 flight
    bookings, 10 scripted, 5 scripted users); real vs generated labels; every date inside its window; every status
    possible on 2026-10-09; money (rates, totals = per night × nights, paid rules, fare formula bounds); rules on the
    scripted bookings; generated refunds only where the rules allow and ≤ 300 TND; `reads` never return
    source / source_id / city / payment; the builder gives the same sample twice; ShopNova's 510 tests unchanged.
14. **README (CLAUDE.md rule 8):** Atlas section (what data, how to download, how to build), folders, task history.

## Checks (with numbers)
- Tests x/y (all pass). Sample file size. Raw files not tracked (`git status`).
- Real mix kept: % cancelled / no-show / room changed / each deposit type (hotel sample vs full file); % cancelled /
  delayed ≥ 15 min / each cancellation reason (flight sample vs full file).
- Money: average hotel stay TND, average flight price TND, min / max; number and total of generated refunds.
- The 10 scripted bookings listed with the rule each one is for, and the rule tests' result.

## Time box and stop rule
**1.5 h.** Stop and report if: main is not at 4580146 or later, a raw file is missing or different, a ShopNova test
fails, anything outside Atlas would need a change, or a secret would end up in git.

## Git (approved by Yassine, 2026-10-30)
Commit and push `feature/atlas-real-data`. **No merge into `main`.** Write `tasks/T20_report.md` (In plain words ·
Done · Evidence · Problems · Questions for the Brain · Next step) and set `tasks/NEXT.md` to WAITING FOR REVIEW.
