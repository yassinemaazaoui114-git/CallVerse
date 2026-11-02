# CallVerse web UI — acceptance walkthrough (for Yassine, with Dali)

Branch `feat/ui-react`, folder `webui/`. Nothing here is accepted until Yassine says so; the merge into `main` is
his. Fill the **Result** columns during the walkthrough: `pass` / `fail` / `not run`, plus a note or a screenshot
name under `webui/reports/screenshots/` as evidence. The **Dali 2026-11-01** column is what Dali saw on a fresh
fixture with the fake models (part A); part B (real models) was **not run**.

Two kinds of checks, kept apart:

- **A. Fake-model checks** (demo fixture + `CALLVERSE_WEBUI_FAKE_CHAT=1`): no model, no Groq, no real database,
  no real money. Parts 1–5. The pending approvals are made by the real Coordinators in queue mode; the decisions
  run the real `approvals.decide` on the temp databases; only the chat channel and the reply writer are fakes.
- **B. Real integration checks** (part 6): the real `config/accounts.yaml`, the real `callverse/data/*.db`,
  Ollama up, the Groq key in `.env`. Never run through the new UI by Dali; they spend Groq quota and write real
  rows, so they are run together, once, bounded.

## 1. Startup (A)

From the repository root. Make a fresh fixture folder (any empty folder; delete it at the end):

```bash
python -m webui.api.dev_fixture C:\Temp\cv-demo
```

It prints the pending approvals it made (ids `#1 #2 #3` on a fresh folder). Then, **in the terminal of the
API** (PowerShell, copy-paste; change the folder if you used another one):

```powershell
$env:CALLVERSE_WEBUI_ACCOUNTS = "C:\Temp\cv-demo\accounts.yaml"
$env:CALLVERSE_WEBUI_TICKETS_DB = "C:\Temp\cv-demo\callverse.db"
$env:CALLVERSE_WEBUI_SHOPNOVA_DB = "C:\Temp\cv-demo\shopnova.db"
$env:CALLVERSE_WEBUI_ATLAS_DB = "C:\Temp\cv-demo\atlas.db"
$env:CALLVERSE_LAYER3_MODE = "queue"
$env:CALLVERSE_WEBUI_FAKE_CHAT = "1"
python -m webui.api.run
```

Second terminal:

```bash
npm --prefix webui/frontend run dev
```

Open the sign-in page of the account: <http://127.0.0.1:5173/shop/login> (ShopNova customers and `admin`), <http://127.0.0.1:5173/atlas/login> (Atlas travellers and `atlas_admin`) or <http://127.0.0.1:5173/console/login> (`supervisor`); <http://127.0.0.1:5173/login> lists them. An account signs in only on its own page. Password of every demo account in the fixture: `demo-only`.

**One approval cannot be both approved and refused.** The fixture gives three pending cases; the walkthrough
below approves two and refuses one. To see the ShopNova refusal too, run `dev_fixture` into a **second fresh
folder** (`C:\Temp\cv-demo-2`), point the API at it (same six lines) and refuse case `#1` there (part 4, last row).

| Check | Expected | Dali 2026-11-01 | Result | Evidence |
|---|---|---|---|---|
| `dev_fixture` | prints "Pending approvals (test data): ShopNova #1 youssef order 4515 refund 378.00 TND; Atlas #2 nizar flight 7004 compensation 839.50 TND; Atlas #3 sonia flight 7006 refund 1900.00 TND" | pass | | `test_dev_fixture.py` |
| API starts | "CHAT IS FAKE …" line, Uvicorn on 127.0.0.1:8610, `/api/health` → `{"ok": true}` | pass | | |
| Vite starts | login page on 127.0.0.1:5173 | pass | | |
| binds | both on 127.0.0.1 only | pass (`run.py`, `vite.config.js`) | | |

## 2. Accounts and roles (A)

What the fixture holds per customer (the scripted samples; everything else is real Olist / hotel / flight data):

| Account | Role / company | Lands on | Owns (scripted) | Must NOT see |
|---|---|---|---|---|
| `supervisor` | supervisor, no company | Console → Live tickets (8 tickets) | — | `/shop`, `/atlas`, `/admin` pages (403, "denied" box) |
| `admin` | ShopNova admin | Refund approvals: **#1** order 4515, 378.00 TND | — | Atlas approvals / records / dashboard, customer pages |
| `sara` | ShopNova customer 1 | My orders | orders 4509, **4512** (stuck at the depot, 59.90 TND); ticket T-0001 (refund 59.90 approved) | 4515 (youssef's) → not found |
| `youssef` | ShopNova customer 2 | My orders | orders 4505, 4510, **4515** (378.00 TND, 8 days late); tickets T-0002 (tracking 4510), **T-0006 waiting for finance** | Atlas pages |
| `amira` `karim` `leila` | ShopNova customers 3–5 | My orders | 4506 + 4511 / 4507 + 4513 / 4508 + 4514 (leila: T-0005 cancel 4514) | another customer's order |
| `atlas_admin` | Atlas admin | Approvals: **#2** flight 7004 compensation 839.50, **#3** flight 7006 refund 1,900.00 | — | ShopNova approvals / dashboard |
| `hedi` | Atlas customer 1 | My bookings | hotels 7001, 7011; flight 7005 (cancelled); ticket T-0003 (rebooking, escalated) | sara's data (same numeric id 1 at ShopNova) |
| `sonia` | Atlas customer 2 | My bookings | hotel 7002; **flight 7006**; ticket **T-0008 waiting for finance** | |
| `tarek` | Atlas customer 3 | My bookings | hotel 7003; flight 7007 | |
| `lobna` | Atlas customer 4 | My bookings | hotel 7009; flight 7008 (cancelled); ticket T-0004 (baggage, waiting for user) | |
| `nizar` | Atlas customer 5 | My bookings | **flight 7004**, flight 7010 (wheelchair request); ticket **T-0007 waiting for finance** | |

| Check | Expected | Dali 2026-11-01 | Result | Evidence |
|---|---|---|---|---|
| each account lands on its home | as the table | pass (API: `test_api.py`, `test_atlas.py`; browser: admin, atlas_admin, youssef, sonia, nizar, supervisor) | | |
| wrong password | "Wrong username or password", no detail | pass (test) | | |
| cross-company / cross-customer | 403 or the same 404 as missing | pass (`test_shop.py`, `test_atlas.py`, `test_admin.py`) | | |
| logout | back to login; reload stays on login | pass (test, browser) | | |

## 3. Customer flows (A: fake chat)

| Flow | Steps | Expected | Dali 2026-11-01 | Result | Evidence |
|---|---|---|---|---|---|
| ShopNova My orders | `sara` | orders 4509 and 4512 among her orders, newest first, "today 2026-10-09 (simulation clock)" | pass (step 2 browser; `test_shop.py`) | | |
| Order detail | `sara` → 4512 | 59.90 TND, stuck at the depot, promised 2026-10-03; "—" for missing values; 4515 → not found | pass (test: ownership) | | |
| Ask about this order | button on the detail | chat with "About order 4512…" placeholder | pass (step 3 browser) | | |
| Chat reply | send "where is my order" | live steps, then a reply starting `[TEST DATA]`, outcome as text | pass (browser, `Chat.test.jsx`) | | `desktop_31_chat_reply_test_data.jpg` |
| Chat busy | message containing `busy` | "Our assistant is busy right now … your message is saved", no red box | pass (test + browser) | | |
| Chat disconnect | message containing `slow`, reload within 20 s | "still being processed", Send disabled, Check status re-attaches; one reply after ~20 s | pass (browser, step 3) | | `desktop_33_chat_still_running_after_reload.jpg` |
| Chat failure | message containing `fail` | red box with the error's words, no invented reply | pass (test) | | |
| Atlas My bookings | `nizar` | flights 7004 and 7010 | pass (browser) | | |
| Booking detail | `hedi` → hotel 7001 | facts list; wrong type in the URL → not found | pass (browser, phone) | | `10_atlas_booking_detail_phone_final.jpg` |
| Unread reply after a decision | `youssef` / `nizar` / `sonia` after part 4 | notice "new reply" on the ticket, the finance reply as the last message | pass (API walkthrough + `test_dev_fixture.py`) | | |
| Phone 375 px | any customer page | no horizontal scroll; fact lists stack label / value | pass (browser) | | |

## 4. Admin flows (A) — the decisions, in this order

Each row is done once; the ids are those of a fresh fixture folder.

| # | Flow | Steps | Expected | Dali 2026-11-01 | Result | Evidence |
|---|---|---|---|---|---|---|
| 4.1 | ShopNova queue | `admin` → Refund approvals | one pending: **#1**, order 4515 · Youssef Trabelsi, 378.00 TND, rule R-REF-03 "Full refund for a delay of more than 5 days", proposal P-0001, facts: stuck at depot, paid 378.00, already refunded 0.00, 8 days late | pass (browser, exactly that) | | `desktop_40_admin_queue_4515.jpg` |
| 4.2 | Confirm dialog | reason "late and stuck", Approve | dialog repeats #1, 378.00 TND, refund, choice, reason; Tab / Shift+Tab stay inside; Escape closes; focus back | pass (browser + 2 tests) | | `07_shop_admin_dialog_keyboard_phone.jpg` |
| 4.3 | Approve #1 | Confirm approval | result: "Approval 1: approved. Outcome approve · ticket T-0006 is now Solved · refund 378.00 TND written · the customer got a new reply."; Waiting (0); order 4515 refunded | pass (browser, exactly that; evidence stage `complete`, notification `confirmed`) | | `desktop_42_admin_approved_result.jpg` |
| 4.4 | Double click | double-click Confirm | one POST (`client_id`), one refund | pass (test `submits once`) | | |
| 4.5 | Again | decide #1 again (another tab or a new request id) | 409 `already_decided`, nothing paid twice | pass (API walkthrough: 409 `already_decided`; `test_dev_fixture.py`) | | |
| 4.6 | Atlas queue | `atlas_admin` → Approvals | Waiting (2): **#2** flight booking 7004 · Nizar Haddad · compensation 839.50 TND · AP-0001 · AT-FLT-03 "Compensation for a long delay"; **#3** flight booking 7006 · Sonia Belhaj · refund 1,900.00 TND · AP-0002 · AT-FLT-04 "Delay of 5 hours or more at departure"; "Confirmed by code: yes" | pass (browser, exactly that) | | `desktop_53_atlas_admin_queue.jpg` |
| 4.7 | Approve #2 | reason "delay confirmed", Approve, Confirm | "Approval 2: approved. Outcome approve · ticket T-0007 is now Solved · compensation 839.50 TND written · the customer got a new reply."; one compensation on 7004 (Records → Compensation: one row, 839.5, approved, AT-FLT-03, AP-0001), no refund | pass (browser) | | `desktop_54_atlas_compensation_approved.jpg` |
| 4.8 | Refuse #3 | reason "airline already refunded", Refuse, Confirm | "Approval 3: refused. Outcome layer3 refused · ticket T-0008 is now Solved · nothing paid · the customer got a new reply."; Decided (2): #3 refused, #2 approved, both "decided by atlas_admin, 2026-10-09T09:00:00 (simulation clock)"; Records → Admin log: `refuse_refund` AP-0002 and `approve_compensation` 1 | pass (browser) | | `desktop_55_atlas_refund_refused.jpg`, `desktop_56_atlas_decided.jpg` |
| 4.9 | Customers told | `youssef`, `nizar`, `sonia`, `hedi`, `sara` → chat | youssef: unread T-0006, last message the finance reply; nizar: unread T-0007; sonia: unread T-0008 ("We are sorry, we cannot approve…"); hedi and sara: nothing unread | pass (API walkthrough, all five) | | |
| 4.10 | Atlas records | Records → Compensation, Admin log | "1 rows · 50 per page · page 1 of 1": the compensation on 7004; the log's two rows carry approval_id 2 and 3, the reasons, the amounts | pass (browser) | | |
| 4.11 | Denied | `admin` opens `/atlas/admin/approvals` | 403 `admin_only`, denied box with the API's words, no data | pass (API walkthrough: 403 `admin_only`; browser step 5) | | |
| 4.12 | **ShopNova refusal** (second fresh folder) | `admin`, reason "duplicate claim", Refuse #1 | outcome `layer3_refused`, refund none, ticket T-0006 Solved; Decided: #1 refused "duplicate claim"; order 4515 still `stuck_at_depot`, refunds empty; youssef: unread T-0006, last message "We are sorry, we cannot approve…" | pass (API walkthrough on folder 2, exactly that) | | |

Note on the reply the customer gets: the fake writer's sentence is checked by the core's SLM check (it must
carry the facts); it fails that check, so the core writes its **template** reply ("Your request has been
approved about your order 4515 … Your refund of 378.00 TND is approved after a check by our finance team"). Not
marked `[TEST DATA]`, but no model ran (the core's own fallback). The fake chat replies are marked.

## 5. Dashboards (A, then B): same data, same period, Streamlit next to the new UI

Run the Streamlit page and the new UI on the **same database files** and the **same period**; read the numbers
side by side. They must be equal (same functions underneath: `reads.dashboard`, `admin_reads.dashboard`,
`atlas_app_reads.dashboard`). For part A point the Streamlit apps at the fixture files too (their own
`CALLVERSE_*` settings, see the main README); for part B both read the real files.

| Dashboard | Period | Numbers to read in both | Dali 2026-11-01 (new UI on the fixture, before the decisions) | Result | Evidence |
|---|---|---|---|---|---|
| Console Dashboard (`supervisor`) | All, then Last 7 days (computer time) | tickets, solved by the AI %, escalated, money per company, Groq today (used / limit), tickets per day, by status | after 4.3–4.8: 8 tickets, 37.5 % solved by the AI alone, 12.5 % escalated, 37.5 % sent to finance, finance 2 / 1 (0 waiting), refunds paid 378.00 TND, compensation 839.50 TND, Groq today 5,490 of 200,000, money per company atlas 839.5 / shopnova 378 | | `desktop_60_console_dashboard.jpg`, `desktop_01_supervisor_live_tickets_after_decisions.jpg` |
| Console satisfaction | any | same average as Streamlit; note "all ShopNova review scores on file (any date, not this period)" | shown with the note | | |
| Console Agents | All | per agent: tickets, tokens, average seconds, models; Coordinator "rules (no LLM)"; "—" where nothing | pass (step 6) | | `desktop_62_console_agents.jpg` |
| ShopNova dashboard (`admin`) | 30 days, then 90 (simulation clock) | orders, sales TND, late, stuck, refunds paid, top products / categories, review average + count, low stock | pass (step 6; after 4.3 "refunds paid" includes 378.00) | | `desktop_63_shop_admin_dashboard.jpg` |
| Atlas dashboard (`atlas_admin`) | All, then 7 days | hotel / flight by status, cancellation and delay rates, refunds and compensation paid, upcoming until 2026-10-23 | pass (step 6; after 4.7 "compensation paid" includes 839.50) | | `desktop_64_atlas_admin_dashboard.jpg` |
| Period change that fails | stop the API, change the period | old numbers dimmed, "could not be loaded … the numbers below are those of <old period>"; Retry works after restart | pass (`Dashboards.test.jsx`; browser step 6) | | |
| Charts | any | "Show as table" lists the same values as the bars | pass (test + browser) | | |
| **Streamlit side by side** | same files, same period | equal numbers | **not run** (Streamlit not started by Dali) | | |

## 6. Real integration (B) — bounded manual smoke test, NOT run by Dali

Run once, together, with Ollama up and the Groq key in `.env`, **without** any `CALLVERSE_WEBUI_*` variable and
without `CALLVERSE_WEBUI_FAKE_CHAT` (the API then uses the real accounts file and databases). Budget: at most
**3 chat messages** and **1 decision**. Stop at the first failure and keep the trace file name (`traces/`).

| # | Step | Expected | Dali | Result | Evidence |
|---|---|---|---|---|---|
| 1 | API on the real files, log in as a real ShopNova customer | real orders listed | not run | | |
| 2 | one chat message about a real order | steps stream live (Intake → Router → Agent → Coordinator → SLM); reply not marked `[TEST DATA]`; the ticket visible in the new Console and in the Streamlit Console | not run | | ticket id, trace file |
| 3 | one message the queue mode sends to finance (`CALLVERSE_LAYER3_MODE=queue`, amount above the limit) | "waiting for finance"; the approval in the new UI's queue AND in the Streamlit admin page | not run | | approval id |
| 4 | one decision on it in the new UI | money written once, approval decided, the customer's ticket gets the SLM reply; Streamlit shows the same decided row | not run | | |
| 5 | (only if the Groq daily quota is actually gone) one message | the channel's busy reply shown as a saved, normal result | not run | | |

Not in this smoke test: a forced Groq 429, a decision interrupted halfway, Agent C / D flows.

## 7. Open core blockers (Yassine's decisions)

| # | Blocker | Where it bites | What the UI does today |
|---|---|---|---|
| 1 | **Partial decision recovery.** `approvals.decide` can fail after the company write (money committed, approval row still pending or the customer reply not sent). No core function finishes such a case; calling `decide` again (new UI or Streamlit, same function) refuses an already decided proposal, and a retry could pay twice. | admin queue, both companies | shows the evidence stage (`company_written_approval_pending`, `approval_closed_notification_unconfirmed`, `nothing_written`) and refuses to replay. **Procedure until then: keep the evidence shown on screen (approval id, stage, error words, time) and escalate to Yassine for a supported core recovery. No manual database edit, no second payment attempt.** Requested: `approvals.finish(approval_id)` in `callverse/`. |
| 2 | Satisfaction per ticket | Console dashboard | the ShopNova review average, labelled as such (waits for agent F) |
| 3 | Serving `frontend/dist` from the API | demo | two processes today; a few lines in `app.py` if wanted |
| 4 | Screenshot folder | docs | `webui/reports/screenshots/` (brief: `docs/screenshots/`) |
| 5 | Agents C / D | rebooking, special assistance | escalated, as in Streamlit |

## 8. Automated evidence (run before the walkthrough)

```bash
python -m pytest webui/api/tests -q
```

```bash
npm --prefix webui/frontend test
```

```bash
npm --prefix webui/frontend run build
```

| Check | Dali 2026-11-01 | Result today |
|---|---|---|
| API tests (incl. `test_dev_fixture.py`: the fixture in a fresh folder, the three decisions through the API) | 82 passed | |
| frontend tests | 51 passed, 10 files | |
| build | OK | |
| changes outside `webui/` on the branch | 3 README lines (step 1 pointer) | |

## 9. Sign-off

| | Name | Date | Decision |
|---|---|---|---|
| Walkthrough run by | | | |
| Fake-model checks (1–5) | | | pass / fail |
| Real smoke test (6) | | | pass / fail / not run |
| Merge into `main` | Yassine | | yes / not yet |
