# CallVerse web UI (React + FastAPI) — `webui/`

The new UI that will replace the three Streamlit apps (brief: `docs/UI_replacement_brief.md`). It is built in
steps. So far: **step 1** = the API skeleton, login, `GET /company`, the supervisor's Console **Live tickets**
and **Ticket detail**; **step 2** = the ShopNova customer's **My orders**, **Order detail** and **Ask about this
order**; **step 3** = the customer's **Help chat** with live progress (SSE) through the existing web chat channel;
**step 4** = the ShopNova admin's **Refund approvals** (the Layer 3 queue) through `approvals.decide`;
**step 5** = Atlas Travel: the customer's **My bookings** (flights and hotel stays), **Booking detail** and
**Help chat**, the admin's **Approvals** (refunds AND compensations) and read-only **Records**. The same screens
and routes as ShopNova's, under `/api/atlas`, with the company taken from the account;
**step 6** = the dashboards: the Console's **Dashboard** and **Agents** (plus Groq today) for the supervisor, and
the two admin dashboards (ShopNova, Atlas), all read-only wrappers of the core's own functions;
**step 7** = the review pass: every account and flow checked in the browser on desktop and on a 375 px phone,
keyboard and screen-reader fixes, the final screenshot set and the handoff report (`reports/step-7.md`);
**step 8 (T27)** = Agent D's owner screens: **Promotions** (ShopNova admin, `/admin/promotions`) and **Hotel deals**
(Atlas admin, `/atlas/admin/deals`) with Approve / Refuse, a **Check now** panel on both admin dashboards, the red
**Urgent** badge (Live tickets, Ticket detail, Approvals sorted urgent first) and Agent C/D's outcomes in plain words
in Ticket detail ("What was done"). Design note: `reports/step-8.md`.
The Console and the order pages stay read only and load no model; the chat loads the channel (and so the
pipeline) on the first message only.

```
webui/
  api/            FastAPI: a thin layer over callverse/ functions (no business logic here)
    app.py        the routes            settings.py   ports, cookie, env overrides
    auth.py       login + sessions      console_reads.py  wrappers around callverse.console.reads
                                        shop_reads.py     wrappers around callverse.data.shop_reads + read tools
    chat.py       chat jobs (worker thread per message) + SSE stream over callverse.channels.web_chat.send
    admin.py      the admin approval queue (both companies) over store.approvals + callverse.channels.approvals.decide
    atlas_reads.py wrappers around callverse.data.atlas.atlas_app_reads / reads (bookings, step 5)
    run.py        start the API         dev_fixture.py    temp accounts + example tickets for a demo
    tests/        pytest (one test per route + security rules)
  frontend/       React 18 + Vite 5 (JavaScript): src/screens, src/components, src/styles (design tokens)
  reports/        step reports for Yassine + screenshots
```

Rules kept: nothing in `callverse/` is changed; the Streamlit apps stay; both servers bind to **127.0.0.1** only;
the account store is the existing `config/accounts.yaml` (bcrypt hashes, same check as streamlit-authenticator);
the Console data comes from `callverse.console.reads` on read-only SQLite connections.

## Setup (once)

Python (same environment as the project; FastAPI, uvicorn, httpx, bcrypt, pyyaml, pytest are already in
`requirements.txt`):

```bash
pip install -r requirements.txt
```

Node.js 22 (frontend tooling only):

```bash
npm --prefix webui/frontend install
```

Accounts: the real `config/accounts.yaml` (made by `python -m scripts.create_demo_accounts`, see the main README).
To try the UI **without** the real accounts or the real tickets database, make a temporary fixture (one password
`demo-only` for every demo username, six example tickets; it never touches the real files):

```bash
python -m webui.api.dev_fixture C:\path\to\a\temp\folder
```

It prints the variables to set before starting the API (`CALLVERSE_WEBUI_ACCOUNTS`,
`CALLVERSE_WEBUI_TICKETS_DB`, `CALLVERSE_WEBUI_SHOPNOVA_DB`, `CALLVERSE_WEBUI_ATLAS_DB`,
`CALLVERSE_LAYER3_MODE=queue`, `CALLVERSE_WEBUI_FAKE_CHAT=1`) and the three pending approvals it made with the
real Coordinators in queue mode (test data): youssef's order 4515 (refund 378.00 TND), nizar's flight 7004
(compensation 839.50 TND), sonia's flight 7006 (refund 1,900.00 TND). One approval is decided once: for a second
approve / refuse of the same case, make a second fixture folder. `webui/api/tests/test_dev_fixture.py` runs the
fixture in a fresh folder and decides the three cases through the API. The walkthrough sheet with PowerShell
setup lines is `reports/acceptance.md`. Delete the folder when done.

To look at the **chat screen without Ollama / Groq**, add `CALLVERSE_WEBUI_FAKE_CHAT=1`: the chat then uses the
fake channel of `webui/api/dev_fixture.py` (no model, every reply starts with `[TEST DATA]`; the words "busy",
"slow" and "fail" in a message trigger the busy outcome, a 20 s run and a worker failure). Never set it for a
real demo: the real chat needs Ollama running and the Groq key in `.env`, exactly like the Streamlit app.

## Run

Two terminals, from the repository root.

API (127.0.0.1:8610; OpenAPI page at <http://127.0.0.1:8610/api/docs>):

```bash
python -m webui.api.run
```

Frontend dev server (127.0.0.1:5173; it proxies `/api` to the API, so the browser sees one origin):

```bash
npm --prefix webui/frontend run dev
```

Open <http://127.0.0.1:5173> and log in. `supervisor` lands in the Console; a ShopNova customer (`sara` …
`leila`) in My orders; `admin` in Refund approvals; `hedi` … (Atlas customers) in My bookings; `atlas_admin` in
the Atlas approvals. The approval queue is only filled when Layer 3 runs in queue mode (`CALLVERSE_LAYER3_MODE=queue`, see the
main README); `CALLVERSE_WEBUI_FAKE_CHAT=1` also makes the decision's customer reply a fake, marked one.

Production-style build (static files in `webui/frontend/dist`, served later in front of the API):

```bash
npm --prefix webui/frontend run build
```

## Test

API:

```bash
python -m pytest webui/api/tests -q
```

Frontend screens (vitest + Testing Library in a jsdom browser, with a fake `fetch`; no server needed):

```bash
npm --prefix webui/frontend test
```

The tests use a temporary accounts file, a temporary tickets database and temporary company databases; they
make `callverse.llm.chat` fail if anything calls it, and check that no read changes a database file and that no
model library or Streamlit is imported. The existing Console tests still pass: `python -m pytest tests/test_console.py -q`.

## API (step 1)

| Route | Who | What |
|---|---|---|
| `POST /api/auth/login` | anyone | `{username, password}` → `{session}`; sets the HttpOnly cookie |
| `POST /api/auth/logout` | anyone | deletes the session, clears the cookie |
| `GET /api/auth/session` | logged in | `{session: {username, name, role, company}}` or 401 |
| `GET /api/company?company=shopnova\|atlas` | logged in | the company profile (same function as the platform's `/company`) |
| `GET /api/console/tickets?company=&status=&priority=&agent=` | supervisor | the Live tickets rows (`reads.live_tickets`) + `has_tickets` |
| `GET /api/console/tickets/filters` | supervisor | the values of the four filters (`reads.filter_values`) |
| `GET /api/console/tickets/{id}` | supervisor | one ticket: conversation, per-message steps (plain words + raw data), decision, approvals |
| `GET /api/shop/orders` | ShopNova customer | the customer's own orders (summaries, newest first) + `sim_today` |
| `GET /api/shop/orders/{id}` | ShopNova customer | one OWNED order: `order` (lines, refunds), `tracking`, `refunds`; missing or someone else's → the same 404 |
| `GET /api/shop/chat?ticket=` | ShopNova customer | the conversation: the named owned ticket (or the current one), its messages, the unread-reply notices, the running / last job |
| `POST /api/shop/chat/send` | ShopNova customer | `{text, ticket_id?, about_order?, client_id?}` → an **SSE stream** (below) |
| `GET /api/shop/chat/job` | ShopNova customer | the customer's running / last job (status, steps so far, result or error) |
| `GET /api/shop/chat/job/stream` | ShopNova customer | re-attach to the running job's SSE stream (replays its steps) |
| `POST /api/shop/chat/tickets/{id}/read` | ShopNova customer | the customer opened this ticket's new reply (owned ticket only) |
| `GET /api/admin/approvals?status=pending\|decided` | ShopNova admin (`approve_refunds`) | the Layer 3 queue: ShopNova rows with the order / proposal facts |
| `GET /api/admin/approvals/{id}` | ShopNova admin | one ShopNova approval's recorded state (Atlas or missing → 404) |
| `POST /api/admin/approvals/{id}/decide` | ShopNova admin | `{approve, reason, client_id?}` → `approvals.decide(id, <username from the account>, approve, reason, company="shopnova")` |
| `GET /api/atlas/bookings` | Atlas customer | the customer's flights and hotel stays (`atlas_app_reads.my_bookings`) |
| `GET /api/atlas/bookings/{flight\|hotel}/{id}` | Atlas customer | one OWNED booking of that TYPE: the My bookings row, the agents' facts (hidden fields removed), refunds, compensations; wrong type / someone else's / missing → the same 404 |
| `/api/atlas/chat…` | Atlas customer | the same five chat routes as `/api/shop/chat…`, with `about_booking` as the context; jobs and tickets are the company's own |
| `/api/atlas/admin/approvals…` | Atlas admin (`approve_refunds`) | the same three approval routes as `/api/admin/approvals…`; an approval's `action` is refund, compensation or cancel, never assumed |
| `GET /api/atlas/admin/records/{hotels\|flights\|users\|refunds\|compensations\|log}?search=&page=` | Atlas admin (`view_dashboard`) | one page of 50 rows (`atlas_app_reads.*_page`) or the last 50 admin actions |
| `GET /api/console/dashboard?days=all\|7\|30` | supervisor | `reads.dashboard(days)` (computer time; satisfaction and Groq today inside), the periods, `has_tickets` |
| `GET /api/console/agents?days=` | supervisor | `reads.agents(days)`: one card per agent |
| `GET /api/console/groq` | supervisor | `reads.groq_today()`: tokens used today out of the configured quota, as the core counts them |
| `GET /api/admin/dashboard?days=7\|30\|90` | ShopNova admin (`view_dashboard`) | `admin_reads.dashboard(days)` (simulation clock) |
| `GET /api/atlas/admin/dashboard?days=7\|30\|all` | Atlas admin (`view_dashboard`) | `atlas_app_reads.dashboard(days)` (simulation clock) |
| `GET /api/health` | anyone | `{ok: true}` |

Errors always look like `{"error": "<code>", "message": "<words>"}` (`not_logged_in` 401, `forbidden` 403,
`csrf` 403, `customer_only` 403, `bad_login` 401, `no_accounts` 503, `not_found` 404, `setup_required` 503,
`busy_user` 409, `empty_text` / `text_too_long` 400, `no_job` 404, `admin_only` 403, `already_decided` 409,
`decision_in_progress` 409, `recheck_refused` 409, `reason_required` 400, `write_refused` 409).

## Agent D's owner screens (step 8, T27)

| Route | Who | What |
|---|---|---|
| `GET /api/admin/promotions?status=pending\|decided` | ShopNova admin (`approve_refunds`) | `approvals.promotions()` + Agent D's facts (stock, sold in 30 days, days of cover) |
| `POST /api/admin/promotions/{id}/decision` `{approve, reason, client_id}` | same | `approvals.decide_promotion()` |
| `POST /api/admin/stock-check` | same | `approvals.run_stock_scan("shopnova")` → `{counts: {short, over, proposed}}` |
| `GET /api/atlas/admin/deals?status=` | Atlas admin (`approve_refunds`) | `approvals.atlas_deals()` + capacity / lowest occupancy, first / last night |
| `POST /api/atlas/admin/deals/{id}/decision` | same | `approvals.decide_atlas_deal()` |
| `POST /api/atlas/admin/room-check` | same | `approvals.run_stock_scan("atlas")` → `{counts: {overbooked, low, proposed}}` |

`webui/api/owner.py` only calls these existing functions. Decisions use the same guard as the approvals
(`admin.Decisions`): one at a time per row (409 `decision_in_progress`), an identical request sent again with the
same `client_id` gets the recorded answer, a decided row gives 409 `already_decided`, refuse without a reason 400
`reason_required`. One scan at a time per company (409 `scan_in_progress`; a crash is 500 `scan_failed`). The
Console's ticket rows and ticket detail carry `urgent` (an approval with `urgent = 1`, or the "urgent refund"
handover step of Agent C). Tests: `webui/api/tests/test_owner.py`, `src/test/T27.test.jsx`.

## Dashboards (step 6)

Thin wrappers: every number is the core's (`callverse.console.reads.dashboard` / `agents` / `groq_today`,
`callverse.data.admin_reads.dashboard`, `callverse.data.atlas.atlas_app_reads.dashboard`); the API adds the
period list of each read, whether any ticket exists, the clock the read uses and the time it was read. Each read
keeps its own periods (Console: all / 7 / 30 days of COMPUTER time, since the simulation clock does not move;
ShopNova: 7 / 30 / 90 days of the SIMULATION clock; Atlas: 7 / 30 / all, simulation clock); any other value is
400 `bad_period`. The screens label the clock, keep the period in the URL (`?days=`), keep the previous numbers
dimmed while a new period loads and drop a late answer of an older period, draw plain SVG bars with the values
written next to them and a "Show as table" alternative, and show a missing value as "—" (never 0). Groq today is
the core's count out of the configured daily quota; no remaining-quota maths is done in the browser.

## Two companies, one API (step 5)

Every company route takes its company from the ROUTE prefix and checks the account against it
(`accounts.check_role(..., company)` / `check_permission(..., permission, company)`): `hedi` (Atlas user 1) is
refused on `/api/shop/…` and `sara` (ShopNova user 1) on `/api/atlas/…`, even though both are "user 1". Tickets
are checked for owner AND company; chat jobs are keyed by (company, user id); recorded decisions and the
in-flight guard by (company, admin, approval id, client_id); the "about this order / booking" id must be the
customer's own in that company. `data_ready(company)` answers 503 `setup_required` before any read when
`shopnova.db` / `atlas.db` is missing (the core's `connect()` would seed it). In the browser, `COMPANIES` in
`src/api.js` binds each company's screens to its prefix, words and routes; the Chat and Approvals screens are
the same components with a `company` prop.

## Admin decisions (step 4)

Browser inputs are the approval id, approve / refuse, the reason and a `client_id`; the admin's username and
the company come from the account. The route re-reads the approval (404 / 409 `already_decided` with who and
when), applies the reason rule, refuses a concurrent request on the same approval (409 `decision_in_progress`),
then calls the core's `decide()` in a worker thread: its own pending check under its lock, the Coordinator's
re-check on fresh data (a failure → 409 `recheck_refused`, nothing written, still pending), the one write
transaction, the customer reply and the unread notice. The result is kept 15 min under the `client_id`, bound
to admin, company, approval, choice and reason: the identical request asked again (lost answer) returns the
recorded result, never a second run; the same id with other content → 409 `client_id_reused`.

Three kinds of answer: the core refused (4xx / 409, nothing written by its contract); the core completed (200);
an exception after the core started → 500 `decision_uncertain` with `evidence` (the re-read approval row,
proposal decision, refund row, ticket status, last message, and a stage: `nothing_written`,
`company_written_approval_pending`, `approval_closed_reply_missing`, `complete`). `GET /api/admin/approvals/{id}`
returns the same `evidence` plus `in_flight` (a decision running in this process). The screen never retries by
itself: on a lost answer it reads that state and says "still processing", "recorded as …", "partially completed,
do not decide again" or "no write found" (only then "Confirm again" with the same request id).
Transaction safety is the core's: `admin_decide_refund` decides the proposal and writes the refund in one SQLite
transaction and refuses an already decided proposal; `close_approval` only closes a pending row. Closing the
approval row and writing the customer reply happen after that transaction, so a crash in between leaves a partial
state the API reports but cannot finish (a core function is requested in the step-4 report).

## Chat transport (step 3)

One message = one **job**: the API validates everything first (login, ShopNova customer role, shop data present,
text, the ticket and the order must be this customer's), then runs `web_chat.send(...)` in a **worker thread**
(the channel keeps its own lock and rules; the API's event loop stays free, so the Console keeps answering) and
answers the POST with a `text/event-stream` body. The browser reads it with `fetch` + a small SSE reader
(`src/sse.js`; a native EventSource cannot POST). Frames: `event: job` (job id), `event: step` (one live text
from the channel's `on_step`), `event: done` (the channel's saved result: ticket id, status, reply, outcome),
`event: error` (the worker failed), and `: ping` comments every 15 s on an idle connection. The reader buffers
partial chunks and splits on blank lines, so a frame cut by the network is reassembled.

Duplicates: each send carries a `client_id`, bound on the server to its text, ticket and order for 15 min
after the job finished (jobs are indexed by company, customer and `client_id`, apart from the "current job"
pointer; the index is bounded to 500 records, oldest finished dropped first). The same id with the same payload
returns the same job, even a replay of A after B ran, and never runs the channel again; the same id with
another payload is refused (409 `client_id_reused`). Another send while the customer's job runs is refused
(409 `busy_user`).

Disconnects: dropping the stream does **not** stop the worker; the channel finishes and saves its reply in the
tickets store. The screen says so ("Connection lost… NOT sent again") and offers **Check status**:
`GET /api/shop/chat/job` tells whether the job is still running (then the screen re-attaches to
`GET /api/shop/chat/job/stream`, which replays the steps so far) or finished (then the saved conversation is
reloaded). On page load a running job is shown as "CallVerse is still working on your last message" with Send
disabled. Jobs live in memory for 15 min after they finish. **Stopping the API process is not a browser
disconnect**: the worker is a daemon thread and dies with the process, so a message that was still being
handled is interrupted; only what the channel had already written to `callverse.db` (the user message, the
steps so far, and the reply if it was reached) survives a restart. The job's progress and its duplicate record
are gone too, so a resend after a restart is a new run.

Request identity in the browser: every NEW message gets a fresh `client_id`, bound to its text, ticket and
order. While a submission's outcome is uncertain (connection lost, or the server said a previous message is
still running), Send is paused and the screen offers **Check status** (one at a time; never resends),
**Resend the same message** (the same id and payload: the server returns the same job or runs it once) or
**Discard**. The next typed message is never treated as a retry of the previous one. Streams are detached
(aborted on the browser side only) when the conversation changes or the screen unmounts; a late event of a
detached stream changes nothing and never redirects. Detaching never cancels the server's job.

Transport state (sending / disconnected / failed) is separate from the business outcome (`approve`, `busy`,
`not_your_order`, an outcome the UI has never seen…), which only comes from the saved result and is shown as
text; the channel's "busy" reply (Agent B's quota) is a normal outcome with its own note.

Security: the session is a random token kept in memory on the server; the browser only holds it in an
`HttpOnly; SameSite=Strict` cookie scoped to `/api`. Every `POST` must send `X-Requested-With: CallVerse` (no
CORS is enabled, so another site cannot add that header). The role is read from the accounts file on every
request through `callverse.auth.accounts.check_role`, never from the browser. The session lasts
`CALLVERSE_WEBUI_SESSION_HOURS` (default 8); restarting the API logs everyone out.

## Review pass (step 7) and known limits

Checked with the demo fixture (`dev_fixture.py`, fake chat), on desktop and on a 375 × 812 phone: the supervisor
(tickets, detail, dashboard, agents), the ShopNova customer and admin, the Atlas customer and admin. Fixed on the
way: the confirmation dialog of the admin queue keeps Tab / Shift+Tab inside, closes on Escape (not while a
decision runs) and gives the focus back to the button that opened it; on a phone the fact lists (`dl.kv`) put the
label above the value instead of squeezing the value into a narrow column.

How the chat behaves when the assistant is not available (verified with the fake channel and the tests):

- **Busy / quota.** The only signal is the channel's own `busy` outcome (`web_chat.BUSY_REPLY`, given when Agent
  B's models answer a daily-quota 429 or the check itself fails). The UI shows it as a normal result ("Our
  assistant is busy right now … your message is saved"), never as an error; the message is kept in the
  conversation. The browser never infers "busy" from the Console's Groq counter, and customers are never shown
  that counter (it is a supervisor read).
- **A message of the same customer already running** → 409 `busy_user`: the draft is kept, the screen says a
  previous message is still being processed and offers "Check status".
- **Connection lost** mid-stream: the job keeps running on the server; "Check status" re-attaches to the same job
  (same `client_id`, no second run); "Resend the same message" sends the same payload and id, which the server
  answers with the recorded result if the job already finished.
- **Worker failure** ("fail" with the fake channel): an `error` event, shown with its words, no invented reply.

Not done, by design or waiting for a decision (details in `reports/step-7.md`): a decision that stops halfway
(money written, approval row or customer reply not finished) needs `approvals.finish(approval_id)` in the core
(the Streamlit app cannot finish it: the same `decide` refuses an already decided proposal; keep the evidence
shown on screen and escalate to Yassine, no manual database edit, no second attempt); the
built `frontend/dist` is not served by the API yet (two processes in a demo); screenshots live under
`webui/reports/screenshots/` (the brief says `docs/screenshots/`); the Console's satisfaction number is still the
ShopNova review average, not per ticket; the Streamlit apps are untouched and still the reference.

## Design

Three themes on the same components: the Console (dark, `tokens.css`), ShopNova (light, paper `#FBF7F2`,
navy `#1F2A44` text and primary buttons, coral `#FF6B4A` accent) and Atlas Travel (white panels on pale blue
`#E0F2FE`, deep blue `#0C4A6E` text, `#0369A1` primary buttons, orange `#F97316` accent); `styles/themes.css`,
switched by `data-theme` on `<html>` per area. Tokens in `frontend/src/styles/tokens.css` (background `#0B1220`, panels `#152033`, text `#E2E8F0`, muted
`#94A3B8`, primary `#2DD4BF` with `#0B1220` text; Open Sans body 16 px, Poppins 600 headings 24–28 px, tables
14 px; 4/8 px spacing; 8 px controls, 12 px panels). Components use only these variables. SVG icons in
`components/Icon.jsx`, visible focus rings, `prefers-reduced-motion` honoured, phone layout from 375 px.
