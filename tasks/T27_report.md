# T27 report — Missing UI screens (Promotions, Hotel deals, Check now, urgent flag, C/D outcomes)

**Top line:** done. The admin can now handle Agent D's proposals in the web UI: Promotions (ShopNova), Hotel deals
(Atlas) and "Check now" on both dashboards, all checked in a real browser. The Urgent badge and Agent C/D's outcomes
are built and tested. In the live run no case was marked urgent, so the badge is shown by the tests only (see Problems).
Branch `feat/t27-ui-screens`, pushed. Full suite **1781 / 1781** (1767 on main + 14 new).

## 1. In plain words
The owner of each company can now see the discounts Agent D proposes and approve or refuse them in the new website,
not only in the old Streamlit apps. A "Check now" button lets Agent D look at the stock (ShopNova) or the empty hotel
rooms (Atlas) and shows what it found. The supervisor's ticket page now says in plain words what Agents C and D did
(replacement made, item kept, passed to a colleague, new flight, wheelchair, waiting for the user's yes, stock warning).
A case Agent C marks urgent gets a red "Urgent" badge and goes to the top of the approvals.

## 2. Done
- Step 1 design pass with the `ui-ux-pro-max` plugin: `webui/reports/step-8.md` (one page, layout sketch).
- API (`webui/api/owner.py` + routes in `webui/api/app.py`), thin wrappers of the existing functions
  (`approvals.promotions`, `decide_promotion`, `atlas_deals`, `decide_atlas_deal`, `run_stock_scan`):
  - `GET /api/admin/promotions?status=pending|decided`, `POST /api/admin/promotions/{id}/decision`, `POST /api/admin/stock-check`
  - `GET /api/atlas/admin/deals?status=`, `POST /api/atlas/admin/deals/{id}/decision`, `POST /api/atlas/admin/room-check`
  - permission `approve_refunds` of the right company (same as the Streamlit pages); CSRF header on POST;
  - decisions reuse `admin.Decisions` (the approvals' idempotency/lock): one decision at a time per row, same
    `client_id` = the recorded answer, decided row = 409 `already_decided`, refuse without reason = 400;
  - one scan at a time per company (409 `scan_in_progress`, crash = 500 `scan_failed`).
  - Console reads: `urgent` on each ticket row and on the ticket detail (`console_reads.urgent_ticket_ids`: an
    approval with `urgent = 1`, or Agent C's "urgent refund" handover step). Read only.
- Frontend (same tokens, Shell, States, Icon; no new npm dependency):
  - `screens/OwnerProposals.jsx`: Promotions (`/admin/promotions`) and Hotel deals (`/atlas/admin/deals`), menu
    entries in `Shell.jsx`, routes in `App.jsx`. Cards with the facts (stock, sold in 30 days, days of cover /
    nights, lowest occupancy of N rooms), Agent D's note, Approve / Refuse with confirmation, who/when after.
  - `components/CheckNow.jsx` on `ShopAdminDashboard` and `AtlasAdminDashboard`: disabled + spinner while running,
    three counts, link to the page, error with Retry.
  - `components/Outcomes.jsx`: `UrgentBadge` (icon + word, not colour alone) on LiveTickets, TicketDetail and
    AdminApprovals (urgent first); "What was done" panel in TicketDetail.
  - Chat: checked, no fix needed. Agent C's question is a normal assistant message, and the user can still type.
  - 3 new icons in `Icon.jsx` (tag, swap, hand).
- Docs: `docs/DEMO_RUNBOOK.md` (F7 now in the web UI, known limit removed), `webui/README.md` (step 8 + routes),
  `README.md` (T27 line).

## 3. Evidence
- Full suite: `python -m pytest -q` → **1781 passed** (225 s).
- Web API: `pytest webui/api/tests -q` → 96 passed. New `test_owner.py` has 14 tests: roles (401 / 403 for sara, hedi,
  supervisor, the other company's admin; CSRF), empty list, real scan → rows with facts (both companies), approve →
  second decision 409, same client_id → recorded answer, reused id 409, refuse needs a reason, two clicks at the
  same time → 200 + 409 and one write, scan twice at once → 409, scan crash → 500 and the guard released, urgent flag.
  One old test (`test_api.py`) got `urgent` added to the expected row keys.
- Vitest: `npm --prefix webui/frontend test` → **61 passed** (51 + 10 in `src/test/T27.test.jsx`). Build OK.
- Live check (real models, headless Edge, fixture data): ShopNova Check now → 42 short, 504 overstocked,
  3 promotions proposed; promotion approved ("approved by admin on 2026-10-09"). Atlas Check now → 2 deals proposed;
  deal 1 approved. A second scan made no duplicates. sara and hedi get **403** on all 4 owner routes.
  F5 (sara, 4512): C asks (46 s), "Yes" → "Replacement created: new order 12001" in Ticket detail (44 s).
- Screenshots `webui/reports/screenshots/step-8/`: 01 ShopNova Check now · 02 Promotions waiting · 03 promotion
  approved (Decided tab) · 04 Atlas Check now · 05 Hotel deal approved · 06 Console Live tickets · 07 Ticket detail
  T-0001 (F5 replacement) · 07 Ticket detail T-0009 (passed to a colleague). That is 8, two more than the 4–6 asked.
- `git diff main -- callverse/`: **no change**. No secrets, `models/` or `data/raw/` in the diff.

## 4. Problems
- **Urgent badge not seen live.** Two tries did not mark a case urgent. "…I want my money back" goes from Intake
  straight to Agent B, so C's "urgent refund" link never runs. An urgency message without money words went
  A → C → escalate. The flag needs A → C → [HANDOVER: B], which these messages did not trigger. The badge is
  covered by API and vitest tests only. Worth a scripted demo message for F5b (question below).
- **Live check deviation:** I did NOT run `scripts/reset_demo.ps1` + `Demo.bat`. The reset deletes the real
  `callverse/data/callverse.db`, and I do not know the real demo passwords (I never read the accounts file). I used
  `webui/api/dev_fixture.py` instead: temporary accounts (test password) and seeded temp DBs in the scratchpad, with
  the real API, the real chat (local models, queue mode) and Vite. The Chrome extension was not connected, so I
  drove headless Edge through its DevTools port with a throw-away scratchpad script. No project dependency was
  added. Login in that script used the API's login call in the page, not typing in the form.
- Days of cover shows **9,999 days** for a product with 0 sales: that is the core's value, shown as it is.
- The report is at `tasks/T27_report.md` (CLAUDE.md rule), not `out/T27_report.md` as the task file says.
- Time box: about 3 h, all steps done.

## 5. Questions for the Brain
1. Should the demo get a fixed message that reliably triggers C's "urgent refund" (A → C → B), so the Urgent badge
   can be shown live? Today none of the runbook flows triggers it.
2. Should 9,999 days of cover show as "no sales in 30 days"? That would be a small frontend change (or a core change).

## 6. Next step
Review, then Yassine merges:
`git checkout main; git pull; git merge --no-ff feat/t27-ui-screens` → run the tests → NEXT DONE → step 09.
