# T21 — Routing by company, part A: Atlas Travel goes through the same center

## Why
CallVerse is one shared center for two companies (decision 2026-10-23). ShopNova works end to end; Atlas Travel has
real data (T20) but no way in. T21 makes a message **for Atlas** go through the same pipeline — Intake → router →
agents A / B → Coordinator → writes → reply writer → tickets / Console — with Atlas's own reasons, tools, rules and
money logic. Tested through `web_chat.send(company="atlas")`; the Atlas app is part B (T22). All details approved
by Yassine on 2026-10-30 (19 items + the Brain's implementation choices, all ⭐).

## Hard limits
- **ShopNova must behave exactly as before.** ShopNova's agent prompts, reply-writer prompt text, Intake examples,
  threshold, routes, rules, tools, allow-lists and Coordinator logic do not change. Where shared code becomes
  company-aware, the ShopNova path must produce the **same text / same result** as today (add tests that the
  ShopNova prompts are byte-identical). All 640 existing tests pass (only tests that check a renamed internal may be
  updated, listed in the report).
- **The company comes from the channel** (`company` argument), never guessed from the message text.
- Every Atlas write goes through a new `callverse/data/atlas/writes.py` with safety nets; no write function is in
  any agent allow-list. Agents only PROPOSE.
- **Amounts for Atlas are computed by code** from the rules, never taken from the agent (item 11).
- No secrets; never read or stage `.env`; tests 0 API calls (fake LLM); never run `tests/data/*`; 127.0.0.1 only.
- Before the live runs: Yassine restarted the PC; stop if free RAM < 300 MB.

## What to do
0. **Git.** `git fetch`, `git checkout main`, `git pull` (must include the T20 merge **6f75551** and the T20 NEXT.md
   DONE commit). Branch `feature/t21-routing-by-company`. Commit this task file, `tasks/NEXT.md` (IN PROGRESS) and the
   two files the Brain placed (untracked) — `callverse/intake/data/reason_examples_atlas.json` and
   `tests/dev/atlas_practice_messages.json` — unchanged, first.

1. **Company setting (items 1, 18).** One small registry of companies (e.g. `callverse/companies.py` reading
   `config.yaml companies:`): for each company its name, data module, reads, rules file, profile file, reason list +
   examples file, routes, allow-lists, finance limit source, Coordinator allowed rules. `shopnova` = today's values;
   `atlas` = the new ones below. `console.companies` gets `atlas`. The company travels on the ticket
   (`ticket["company"]`) from the channel to every step; a missing company = `shopnova` (old callers keep working).

2. **Two scripted Atlas bookings for the cancel action (implementation choice, approved).** Add to
   `callverse/data/atlas/seed.py` (and its pinned tests; existing scripted values unchanged):
   **7011** user 1 (Hedi), hotel 1, booked 2026-09-25, arrival **2026-10-20**, 2 nights, 2 adults, BB, room A/A,
   **refundable**, 110.00 / night, total **220.00**, paid **220.00**, **confirmed**;
   **7012** user 2 (Sonia), hotel 2, booked 2026-09-15, arrival **2026-10-25**, 4 nights, 2 adults, HB, room D/D,
   **non_refundable**, 100.00 / night, total **400.00**, paid **400.00**, **confirmed**.

3. **Intake for Atlas (items 2, 4, 5, 6).**
   - `extract`: also reads "booking N", "reservation N", "flight booking N" (and "order N" stays). For Atlas the id
     is looked up in `atlas.db`: it decides `booking_type` = hotel / flight (the scripted ids 7001–7012 are unique
     across the two tables; real hotel 20001+, real flight bookings 30001+).
   - **Atlas reasons (8):** `booking_status`, `delay_disruption`, `cancellation`, `refund_request`,
     `compensation_request`, `rebooking`, `special_assistance`, `other`, matched by meaning with the same model and
     method as ShopNova, on the Brain's examples file `reason_examples_atlas.json` (own vector cache).
     **Threshold for Atlas** chosen by leave-one-out **on these examples only** (like T03; report the numbers).
     Main-reason order for Atlas: special_assistance, rebooking, compensation_request, refund_request, cancellation,
     delay_disruption, booking_status, other.
   - LLM fallback: company-aware reason list and company name (ShopNova's prompt text unchanged).
   - Facts for Atlas: read with the Atlas reads (booking + its flight), never writes.
   - **Priority for Atlas:** severity base special_assistance 0.7, rebooking 0.6, delay_disruption 0.5,
     refund_request 0.5, cancellation 0.4, compensation_request 0.4, booking_status 0.2, other 0.2; **time pressure =
     1.0 if departure / arrival is within 24 h, 0.5 within 72 h, else 0** (past trips 0); same weights and labels as
     ShopNova.

4. **Routing (item 7):** Atlas routes: booking_status, delay_disruption, other → **A**; refund_request,
   compensation_request, cancellation → **B**; rebooking, special_assistance → **escalate** (ticket "Escalated",
   reply via the escalate decision: "Your request has been passed on to a colleague who will help you with it." —
   no agent call) until agent C exists.

5. **Agents (items 8, 9).** Same classes A and B, **company-aware**: ShopNova keeps today's prompts exactly; Atlas gets
   its own short prompts (same style and safety lines: facts only from tools, plain text, never promise money, cite
   the rule id, call the proposal tool before answering when a rule applies, Atlas never gives amounts).
   Allow-lists per company (registry keyed by company + agent):
   - **Atlas A:** `get_user`, `get_hotel_booking`, `get_flight_booking`, `get_flight`, `get_company_profile`
     (Atlas profile), `search_policy` (Atlas index).
   - **Atlas B:** `get_hotel_booking`, `get_flight_booking`, `get_refunds`, `search_policy`, `propose_refund`,
     `propose_compensation`, `propose_hotel_cancellation`, `ask_agent` (asks Atlas A).
   - Atlas proposal tools take: booking_type, booking_id, rule_id, facts_used, user_confirmed, user_quote — **no
     amount**.

6. **Rule search per company (item 10):** one index per company (own cache file per rules file + model);
   `search_policy` searches only the ticket's company. ShopNova's index and results unchanged.

7. **Coordinator for Atlas (items 11, 12, 13).** Company-aware: rules file, allowed rules, facts and limit per company;
   ShopNova path unchanged. For Atlas, after the usual checks (known action, booking exists and belongs to the case,
   rule exists + fits the action + its condition holds on re-read facts, user confirmed):
   - **Amounts by code:** AT-FLT-01 / AT-FLT-04 / AT-HOT-02 refund = paid − refunded_total; AT-HOT-04 refund = 20 % of
     total (rounded to 2 decimals), capped by AT-REF-01; compensation AT-FLT-02 / AT-FLT-03 = the band amount from the
     rule text (839.50 / 1,343.20 / 2,014.80 TND by distance; > 3,500 km delay: 1,007.40 for 3–4 h, 2,014.80 for
     4 h or more), only if AT-FLT-06 (extraordinary) is false and notice_days < 14.
   - **Hotel cancellation by the user:** booking must be `confirmed` and arrival after today → booking `cancelled`
     (`cancelled_date` = sim today) + refund by deposit type: no_deposit → nothing; refundable and ≥ 2 days before
     arrival → paid − refunded; otherwise / non_refundable → nothing (AT-HOT-01 / 02 / 03).
   - **Finance limit (item 13): change AT-ESC-01** in `policies_atlas.json` to "a refund above **1,500 TND**, and
     **every compensation**, needs finance approval" (condition and text; update T20's pinned rule test on 7009,
     which is now below the limit). A refund of exactly 1,500.00 is automatic ("above").
   - Over the limit, in queue mode → `layer3_pending` (same as ShopNova); stub mode for Atlas: refund ≤ stub max
     approved, compensation refused by the stub (tests only).
   - Meals (AT-FLT-05) and AT-FLT-06: information only (no action).

8. **Atlas writes (item 14):** `callverse/data/atlas/writes.py`: `record_proposal`, `record_decision`,
   `create_refund(booking_type, booking_id, amount, rule_id, proposal_id)`, `create_compensation(...)` (status
   `approved`), `cancel_hotel_booking(booking_id, proposal_id)`, each with safety nets: an approved proposal of the
   same action / booking / amount, used once; refund ≤ paid − refunded; compensation once per booking; the hotel
   cancel + its refund in **one transaction**. The approvals table (`callverse.db`) gets `company`, `booking_type`,
   `action` (refund / compensation), added on connect if missing; `approvals.decide` handles Atlas (one transaction,
   re-check on fresh data, like T18). ShopNova rows keep working (company default `shopnova`).

9. **Replies (item 15):** `user_words` per company: Atlas sentences (e.g. "Your refund of X TND for booking N is
   approved.", "Your compensation of X TND for booking N needs approval from our finance team.", "Your hotel booking N
   is cancelled.", meals information from AT-FLT-05, no-compensation cases = the status only until T14). The reply
   writer gets the company name and a one-line company description; **ShopNova's prompt text stays identical**.
   Off-topic answer per company ("I can help with your Atlas Travel bookings: flights, hotel stays, refunds and
   compensation.").

10. **Channel + tickets:** `web_chat.send(user_id, company, ...)` already takes the company: identity check uses the
    company's data (the booking must be this user's); the pending-approval guard is per company and booking; tickets
    keep `company`. The Console shows Atlas tickets (company filter, timeline) with no other change.

11. **Tests (offline, all pass, 0 API):** ShopNova prompts byte-identical; ShopNova routes / reasons unchanged; Atlas
    extract (booking ids, type lookup); Atlas reason matcher on its examples (leave-one-out numbers); Atlas routes incl.
    escalate for rebooking / assistance; allow-lists (Atlas tools never visible to ShopNova agents and back); amounts by
    code for every rule (scripted bookings); compensation blocked by AT-FLT-06 and by notice ≥ 14; finance limit 1,500
    (1,500.00 automatic, 1,500.01 pending, every compensation pending); hotel cancel in one transaction; Atlas writes'
    safety nets; approvals for Atlas (approve / refuse, re-check); channel with a fake LLM for each practice message's
    path; Console reads show both companies.

12. **Live proof (item 17), once, after Yassine restarted the PC** (app settings: Intake + A + SLM local, B on Groq,
    queue mode):
    - **ShopNova unchanged:** practice messages **d05, d17, d20** from `tests/dev/live_dev_messages.json` → same
      outcomes as before (d05 refund 59.90; d17 Layer 3 → pending in queue mode; d20 its usual result). Reset first.
    - **Atlas:** the **12 messages of `tests/dev/atlas_practice_messages.json`** in order on a fresh `atlas.db`
      (reset once). Score each against its `expect`; for a02 then call `approvals.decide(approve)` and show the
      compensation row (839.50) + the new message. Report x/12 with every miss explained (no fixes to prompts for one
      message: fixes go into code, rule of 2026-10-24).
    - Groq tokens (about 50,000 expected), 0 Gemini. Then reseed both DBs and delete `callverse.db`.

13. **README (rule 8):** Atlas through the center (what works, how to try it with `web_chat.send`), task history.

## Checks (with numbers)
- Tests x/y; new tests listed; Atlas threshold + leave-one-out numbers.
- ShopNova: the 3 practice messages, same outcomes as T16/T19 (say any difference).
- Atlas: x/12 with a table (message, outcome, writes, reply), tokens, seconds per message.
- `git status`: no secrets, no DBs tracked.

## Time box and stop rule
**3 h.** Stop and report if: main lacks the T20 merge, a ShopNova test fails or a ShopNova prompt would change, an
Atlas amount would come from the agent, a secret would end up in git, free RAM < 300 MB, or Groq's daily limit
answers (then report the live part as unfinished, with what ran).

## Git (approved by Yassine, 2026-10-30)
Commit and push `feature/t21-routing-by-company`. **No merge into `main`.** Write `tasks/T21_report.md` (In plain
words · Done · Evidence · Problems · Questions for the Brain · Next step) and set `tasks/NEXT.md` to WAITING FOR
REVIEW. Last line for Yassine (to tell Dali): companies registry, approvals columns `company` / `booking_type` /
`action`, Atlas bookings 7011–7012, AT-ESC-01 now 1,500 TND + every compensation.
