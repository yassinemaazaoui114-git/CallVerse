# CallVerse web UI — acceptance walkthrough (for Yassine, with Dali)

Branch `feat/ui-react`, folder `webui/`. Nothing here is accepted until Yassine says so; the merge into `main` is
his. Fill the **Result** columns during the walkthrough: `pass` / `fail` / `not run`, plus a note or a
screenshot name under `webui/reports/screenshots/` as evidence.

Two kinds of checks, kept apart:

- **A. Fake-model checks** (demo fixture, `CALLVERSE_WEBUI_FAKE_CHAT=1`): no model, no Groq, no real database.
  Everything in parts 1–4 and most of 5 can be run this way, any day.
- **B. Real integration checks** (part 6): the real `config/accounts.yaml`, the real `callverse/data/*.db`, Ollama
  up, the Groq key in `.env`. **Not verified by Dali** (never run through the new UI); they spend Groq quota and
  write real rows, so they are run together, once, and bounded.

## 1. Startup

Fake-model setup (A), from the repository root, two terminals:

```bash
python -m webui.api.dev_fixture C:\path\to\a\temp\folder
```

Set the four `CALLVERSE_WEBUI_*` variables it prints, plus `CALLVERSE_LAYER3_MODE=queue` and
`CALLVERSE_WEBUI_FAKE_CHAT=1`, in the terminal of the API. Then:

```bash
python -m webui.api.run
```

```bash
npm --prefix webui/frontend run dev
```

Open <http://127.0.0.1:5173>. Password of every demo account in the fixture: `demo-only`. Delete the temp folder
at the end.

Real setup (B): same two commands **without** any `CALLVERSE_WEBUI_*` variable and without
`CALLVERSE_WEBUI_FAKE_CHAT` (the API then uses the real accounts file and databases); Ollama running; `.env`
with the Groq key (never printed, never read by the UI code). `CALLVERSE_LAYER3_MODE=queue` only if you want the
approval queue to fill.

| Check | Expected | Result | Evidence |
|---|---|---|---|
| `python -m webui.api.run` starts | "Uvicorn running on http://127.0.0.1:8610", `/api/health` → `{"ok": true}` | | |
| Vite starts | page on 127.0.0.1:5173, login screen | | |
| binds | both on 127.0.0.1 only (not 0.0.0.0) | | |

## 2. Accounts and roles

| Account | Role / company | Lands on | Must NOT see | Result | Evidence |
|---|---|---|---|---|---|
| `supervisor` | supervisor, no company | Console → Live tickets | /shop, /atlas, /admin pages (403 in the API, "denied" box) | | |
| `admin` | ShopNova admin | Refund approvals | Atlas approvals / records / dashboard, any customer page | | |
| `sara` `youssef` `amira` `karim` `leila` | ShopNova customers (ids 1–5) | My orders | another customer's order (404, same as missing), Atlas pages, admin pages | | |
| `atlas_admin` | Atlas admin | Atlas approvals | ShopNova approvals / dashboard, customer pages | | |
| `hedi` `sonia` `tarek` `lobna` `nizar` | Atlas customers (ids 1–5) | My bookings | another customer's booking, ShopNova pages (`hedi` is id 1 at Atlas, `sara` id 1 at ShopNova: never the same data) | | |
| wrong password | "Wrong username or password", no detail | | | | |
| logout | back to login; a reload stays on login (cookie gone) | | | | |

## 3. Customer flows (A: fake chat)

| Flow | Steps | Expected | Result | Evidence |
|---|---|---|---|---|
| ShopNova My orders | log in as `sara` | her orders, newest first, "today 2026-10-09 (simulation clock)" | | |
| Order detail | open order 4505 | lines, tracking, refunds; missing values "—", never 0 | | |
| Ask about this order | button on the detail | chat opens with "About order 4505…" placeholder | | |
| Chat reply | send "where is my order" | live steps (Intake, Agent …), then a reply starting `[TEST DATA]`, outcome shown as text | | |
| Chat busy | send a message containing `busy` | "Our assistant is busy right now … your message is saved"; no red error box | | |
| Chat disconnect | send a message containing `slow`, reload the page within 20 s | "A message is still being processed", Send disabled, "Check status" re-attaches; after ~20 s the reply appears once | | |
| Chat failure | send a message containing `fail` | red box with the error's words, no reply invented | | |
| Enter / Shift+Enter | in the chat box | Enter sends, Shift+Enter makes a new line | | |
| Atlas My bookings | log in as `hedi` | flights and hotel stays (7001 …), types labelled | | |
| Booking detail | open hotel 7001 and a flight | facts list, refunds, compensations; wrong type in the URL → not found | | |
| Atlas chat with context | "Ask about this booking" | placeholder names the booking; reply `[TEST DATA]` | | |
| Phone 375 px | any customer page | no horizontal scroll; fact lists stack label over value | | `10_atlas_booking_detail_phone_final.jpg` |

## 4. Admin flows (A)

| Flow | Steps | Expected | Result | Evidence |
|---|---|---|---|---|
| ShopNova queue | `admin` → Refund approvals | one pending approval (order 4505, 1,850 TND, test data) with the order facts and the rule | | |
| Confirm dialog | type a reason, Approve | dialog repeats approval id, amount, action, choice, reason; Tab / Shift+Tab stay inside; Escape closes; focus returns to Approve | | `07_shop_admin_dialog_keyboard_phone.jpg` |
| Decide | Confirm approval | result box: approval approved, ticket status, "refund … written", "the customer got a new reply"; the row moves to Decided; the customer (`sara`) sees an unread-reply notice | | `desktop_42_admin_approved_result.jpg` |
| Second click | double-click Confirm | one POST only (`client_id`), one decision | | |
| Already decided | decide the same approval from a second tab | "already approved", nothing written twice | | |
| Refuse | Refuse with a reason | nothing paid, customer told, row Decided | | |
| Atlas queue | `atlas_admin` → Approvals | the pending compensation (flight 7004, 839.50 TND) and refund (flight 7006, 1,900 TND), action named (refund / compensation), never assumed | | `desktop_53_atlas_admin_queue_compensation.jpg` |
| Atlas records | Records → hotels / flights / users / refunds / compensations / log | 50 rows per page, search, paging; read-only | | |
| Denied | `admin` opens `/atlas/admin/approvals` | denied box with the API's words, no data | | |

## 5. Dashboards: same data, same period, Streamlit next to the new UI

Run the Streamlit app and the new UI on the **same database files** (the real ones for B, or point the Streamlit
app at the fixture files for A) and the **same period**. Read the numbers side by side; they must be equal, not
"close" (same functions underneath: `reads.dashboard`, `admin_reads.dashboard`, `atlas_app_reads.dashboard`).

| Dashboard | Period to compare | Numbers to read in both | Result | Evidence |
|---|---|---|---|---|
| Console Dashboard (`supervisor`) | All, then Last 7 days (computer time) | tickets, solved by the AI %, escalated, money per company, Groq today (used / limit), tickets per day, by status | | `desktop_60/61_console_dashboard*.jpg` |
| Console Dashboard satisfaction | any | the same average as the Streamlit page; the note says "all ShopNova review scores on file (any date, not this period)" | | |
| Console Agents | All | per agent: tickets, tokens, average seconds, models; Coordinator "rules (no LLM)"; "—" where Streamlit shows nothing | | `desktop_62_console_agents.jpg` |
| ShopNova dashboard (`admin`) | 30 days, then 90 (simulation clock, from … to 2026-10-09) | orders, sales TND, late, stuck, refunds paid, top products / categories, review average + count, low stock | | `desktop_63_shop_admin_dashboard.jpg` |
| Atlas dashboard (`atlas_admin`) | All, then 7 days | hotel / flight by status, cancellation and delay rates, refunds and compensation paid, upcoming arrivals / departures until 2026-10-23 | | `desktop_64_atlas_admin_dashboard.jpg` |
| Period change that fails | stop the API, change the period | old numbers dimmed with "could not be loaded … the numbers below are those of <old period>"; Retry works after restart | | |
| Charts | any | "Show as table" lists the same values as the bars; the chart's accessible name lists them | | |

## 6. Real integration (B) — bounded manual smoke test, NOT verified by Dali

Run once, together, with Ollama up and the Groq key in `.env`. Budget: at most **3 chat messages** and **1
decision** (each chat message costs Groq tokens; each decision writes a real row). Stop at the first failure and
keep the trace file name (`traces/`).

| # | Step | Expected | Result | Evidence |
|---|---|---|---|---|
| 1 | API without `CALLVERSE_WEBUI_*`, log in as a real ShopNova customer | real orders listed | | |
| 2 | one chat message about a real order ("where is my order N") | steps stream live (Intake → Router → Agent → Coordinator → SLM), reply not marked `[TEST DATA]`, the same ticket visible in the Console and in the Streamlit Console | | ticket id, trace file |
| 3 | one message that the queue mode sends to finance (amount above the limit, `CALLVERSE_LAYER3_MODE=queue`) | "waiting for finance" outcome; the approval appears in the admin queue of the new UI AND in the Streamlit admin page | | approval id |
| 4 | one decision on it in the new UI | refund written once, approval decided, the customer's ticket gets the reply; the Streamlit page shows the same decided row | | |
| 5 | (optional, only if the Groq daily quota is actually gone) one message | the channel's busy reply shown as a saved, normal result | | |

Not in this smoke test (would need core work or a quota we do not want to spend): a forced Groq 429, a decision
interrupted halfway, Agent C / D flows (escalated until they exist).

## 7. Open core blockers (Yassine's decisions)

| # | Blocker | Where it bites | What the UI does today |
|---|---|---|---|
| 1 | **Partial decision recovery.** `approvals.decide` can fail after the company write (money committed, approval row still pending or the customer reply not sent). There is no core function to finish such a case; calling `decide` again (new UI or Streamlit, same function) refuses an already decided proposal, and a retry could pay twice. | admin queue, both companies | shows the evidence stage (`company_written_approval_pending`, `approval_closed_notification_unconfirmed`, `nothing_written`) and refuses to replay. **Procedure until then: the operator keeps the evidence shown on screen (approval id, stage, error words, time) and escalates to Yassine for a supported core recovery. No manual database edit, no second payment attempt.** Requested: `approvals.finish(approval_id)` in `callverse/`. |
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

| Check | Last result (2026-11-01, Dali) | Result today |
|---|---|---|
| API tests | 79 passed | |
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
