# UI replacement — step 5 report (for Yassine)

Branch `feat/ui-react` · after the step-4 evidence correction `b4ec97b` · folder `webui/` · 2026-11-01 · Dali's lane.
`callverse/` unchanged, Streamlit apps unchanged, no merge into `main`. No Atlas admin dashboard (charts: step 6
with the other dashboards), no step 6.

## 1. In plain words

Atlas Travel now has its pages in the new UI, built on the same pieces as ShopNova's: a customer sees **My
bookings** (flights with their situation, hotel stays with their room and deposit, each with its refunds and
compensation), a **Booking detail** with what Atlas knows about it (the agents' own read, internal fields
removed), and the **Help chat** with "Ask about this booking" (the same worker + live steps as ShopNova's, the
booking number given to the channel as the core expects). The Atlas admin gets the **Approvals** queue (refunds
above the limit and every compensation; the code's confirmation decision shown; approve / refuse with a reason
through the same `approvals.decide`, with the same recovery behaviour as step 4, and a compensation reported as
a compensation, never as a refund) and the read-only **Records** tables with search and pages. The company
always comes from the account, never from the browser: Hedi (Atlas user 1) and Sara (ShopNova user 1) share a
number and can never see each other's data, chats or queues. Checked in the browser with the fake channel and
fake reply writer (replies marked `[TEST DATA]`); no Groq, no real money.

## 2. Done

- **API** (`app.py` rewritten around company-parametrised guards; the step 1–4 routes unchanged):
  `customer_of(company)` / `admin_of(company, permission)` on `accounts.check_role` / `check_permission`;
  `data_ready(company)` (503 before any read when `shopnova.db` / `atlas.db` is missing; nothing seeded).
  New: `GET /api/atlas/bookings`, `GET /api/atlas/bookings/{flight|hotel}/{id}` (`webui/api/atlas_reads.py` over
  `atlas_app_reads.my_bookings`, `reads.get_flight_booking` / `get_hotel_booking`, `get_refunds`,
  `get_compensations`; ownership AND type checked, one 404 for every miss); the chat routes registered twice
  (`register_chat`: `/api/shop/chat…` and `/api/atlas/chat…`, `about_booking` → the channel's `about_order`,
  context ownership via `atlas_reads.owned_any`, jobs keyed by company + user id); the approval routes registered
  twice (`register_admin`: `/api/admin/approvals…` and `/api/atlas/admin/approvals…`); `admin.py` takes the
  company everywhere (Atlas facts from `atlas_app_reads.approval_facts`, the proposal from atlas
  `writes.get_proposal`, the evidence's money row = the refund OR the compensation of the booking by the
  approval's `action`, decisions and in-flight keyed by company); `GET /api/atlas/admin/records/{table}`
  (`view_dashboard`). The channel and the pipeline stay lazily imported.
- **Frontend**: `COMPANIES` + `chatScope` / `adminScope` in `api.js`; `Chat` and `AdminApprovals` take a
  `company` prop (words: order / booking, action named from the row, compensation in the result); new screens
  `MyBookings`, `BookingDetail`, `Records`; Atlas theme (`data-theme="atlas"`); shell areas `atlas` and
  `atlas-admin`; routes `/atlas/bookings`, `/atlas/bookings/:kind/:id`, `/atlas/chat`, `/atlas/admin/approvals`,
  `/atlas/admin/records`; login homes for Atlas accounts. The demo fixture seeds `atlas.db` and one pending
  compensation (test data) and the fake channel says "booking" at Atlas.
- **Tests**: `webui/api/tests/test_atlas.py` (11) and `src/test/Atlas.test.jsx` (4).

## 3. Numbers / evidence

| Check | Result |
|---|---|
| `python -m pytest webui/api/tests -q` (steps 1–5) | **69 passed** |
| `npm --prefix webui/frontend test` (steps 1–5) | **43 passed** (10 files) |
| `npm --prefix webui/frontend run build` | OK, JS 246.8 kB (75.6 kB gzip) |
| sara / admin / supervisor / atlas_admin / hedi on the Atlas customer and admin routes; hedi and atlas_admin on ShopNova's | 401 without login; 403 with the right code and "Atlas" in the words |
| hedi: hotels 7001, 7011 and flight 7005 only; `flight/7005` with facts (no `payment_method`, no `source`); `hotel/7001`; `hotel/7005` (wrong type), `flight/7004` (nizar's), `flight/9999`, `train/7005` → 404 | passed |
| sara on `/api/atlas/bookings/hotel/7001` → 403; hedi on `/api/shop/orders/4505` → 403 | passed |
| Atlas chat: the channel gets `(user 1, "atlas", text, ticket, about=7005)`; 7004 / 9999 as context → 404 before the channel; sara's `/api/shop/chat` shows no job and no ticket, the Atlas ticket is 404 for her, the same `client_id` at ShopNova is a new job | passed |
| Atlas queue: only Atlas rows, `action=compensation`, `booking_type=flight`, 839.50 TND, rule AT-FLT-03, "yes (compensation request + quote found)"; a ShopNova approval → 404 there and the Atlas one → 404 for the ShopNova admin | passed |
| approve: `decide(…, company="atlas")` with `atlas_admin`; the compensation row written, no refund; evidence `action=compensation`, money = the compensation; nizar's chat shows the reply and the notice; same `client_id` again → recorded, one compensation | passed |
| refuse: blank reason 400; with reason → `layer3_refused`, nothing paid, reason stored | passed |
| same `client_id` with another choice → 409 `client_id_reused`; `close_approval` raising after the transaction → 500 `decision_uncertain`, stage `company_written_approval_pending`, money = the compensation; retry refused by the core, one compensation | passed |
| an Atlas decision in flight is not seen on the ShopNova approval with another id | passed |
| records: 5 tables + log, search "7001", bad table 404, ShopNova admin 403 | passed |
| missing `atlas.db` → 503 on customer and admin routes, file not created | passed |
| Browser (fake channel, desktop): hedi → My bookings (flight 7005 "cancelled (the airline)", hotels 7001 / 7011; screenshot 50); flight detail with facts (51); `hotel/7005` → "not one of your bookings"; chat with "About booking 7005" → `[TEST DATA]` reply (52); atlas_admin → Approvals with the compensation, confirmation by code (53) → confirm dialog naming the action (54) → approved, "compensation 839.50 TND written" (55); Decided tab (56); Records 2006 hotel bookings, 50 per page | ✔ |
| Browser, phone 375×812: Records and Approvals, `scrollWidth` 375 = `clientWidth` (57, 58) | ✔ |
| Real model / money | none (fake channel, fake reply writer, temp databases) |

## 4. Problems and limitations

- **Atlas admin dashboard** (rates, charts) is not in this step: the brief puts dashboards in step 6.
- (closed in the correction commit) A pending Atlas refund above 1,500 TND IS in the seeded sample: sonia's
  flight 7006 (1,900 TND, departure delay of 5 h or more) under AT-FLT-04; the Atlas Coordinator answers
  `layer3_pending` for it. The refund path is now tested like the compensation one (below, section 7).
- The ShopNova-side test helper and the Atlas one build pending cases through the Coordinators (`review`), not
  through `web_chat.send` (that would load the local models); the approval rows are exactly what the channel
  creates.
- **Browser checks not performed**: an Atlas refusal, the uncertain / in-flight boxes at Atlas (same component
  and code as ShopNova's, covered by tests), the phone layout of the Atlas chat (same component as ShopNova's,
  checked in step 3), the "disconnect" during an Atlas chat.
- The fake channel's reply does not say "booking" in its text (it marks the message "(booking N)" now; the
  reply itself is a fixed test sentence).

## 5. Questions / core blockers for the Brain

1. (step 4, still open) `approvals.finish(approval_id)` in the core, to close a partial decision; now also
   needed for Atlas compensations (same shape).
2. Should the Atlas Approvals screen show the code's confirmation reason more prominently (today one row,
   "yes (compensation request + quote found)")?
3. Step 6: Console Dashboard / Agents / Satisfaction + the two admin dashboards (ShopNova `admin_reads.dashboard`,
   Atlas `atlas_app_reads.dashboard`). Plan: read-only routes + one chart component (no new library; SVG bars).
   OK?

## 6. Next step

Step 6 of the brief (dashboards: Console Dashboard, Agents, Satisfaction, Groq today; the two admin dashboards).
After your review of this step.

## 7. Correction (second step-5 commit)

1. **`BookingDetail.jsx` read `compensations.total`**; the core's `reads.get_compensations` returns
   `compensated_total`. Fixed; the screen test now uses the exact API shape (`refunded_total`,
   `compensated_total`, the compensation rows) and asserts a nonzero "compensation so far: 250.00 TND".
2. **Atlas refund coverage** (`pending_atlas_refund()` in the test conftest: flight 7006, 1,900 TND, AT-FLT-04,
   through the Atlas Coordinator, no core change, no model): the queue row says `action=refund`; approve writes
   the REFUND row (1,900 TND) and no compensation, the evidence names `action=refund` with that money row, the
   customer (sonia) gets the reply and the notice; refuse needs a reason and pays nothing; the same request id
   again is recorded, the same id with another choice is 409 `client_id_reused`, a new decision is 409
   `already_decided`; `close_approval` raising after the transaction gives 500 `decision_uncertain`, stage
   `company_written_approval_pending` with the refund as the money row, and the retry is refused by the core
   with one refund row.

Results: API **71 passed**, vitest **43 passed**, build OK.
