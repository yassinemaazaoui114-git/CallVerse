# CallVerse web UI (React + FastAPI) — `webui/`

The new UI that will replace the three Streamlit apps (brief: `docs/UI_replacement_brief.md`). It is built in
steps. So far: **step 1** = the API skeleton, login, `GET /company`, the supervisor's Console **Live tickets**
and **Ticket detail**; **step 2** = the ShopNova customer's **My orders**, **Order detail** and **Ask about this
order**; **step 3** = the customer's **Help chat** with live progress (SSE) through the existing web chat channel.
The Console and the order pages stay read only and load no model; the chat loads the channel (and so the
pipeline) on the first message only.

```
webui/
  api/            FastAPI: a thin layer over callverse/ functions (no business logic here)
    app.py        the routes            settings.py   ports, cookie, env overrides
    auth.py       login + sessions      console_reads.py  wrappers around callverse.console.reads
                                        shop_reads.py     wrappers around callverse.data.shop_reads + read tools
    chat.py       chat jobs (worker thread per message) + SSE stream over callverse.channels.web_chat.send
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

It prints the three variables to set before starting the API (`CALLVERSE_WEBUI_ACCOUNTS`,
`CALLVERSE_WEBUI_TICKETS_DB`, `CALLVERSE_WEBUI_SHOPNOVA_DB`). Delete the folder when done.

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
`leila`) in My orders; any other account on a page saying its screens are not built yet.

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
| `GET /api/health` | anyone | `{ok: true}` |

Errors always look like `{"error": "<code>", "message": "<words>"}` (`not_logged_in` 401, `forbidden` 403,
`csrf` 403, `customer_only` 403, `bad_login` 401, `no_accounts` 503, `not_found` 404, `setup_required` 503,
`busy_user` 409, `empty_text` / `text_too_long` 400, `no_job` 404).

## Chat transport (step 3)

One message = one **job**: the API validates everything first (login, ShopNova customer role, shop data present,
text, the ticket and the order must be this customer's), then runs `web_chat.send(...)` in a **worker thread**
(the channel keeps its own lock and rules; the API's event loop stays free, so the Console keeps answering) and
answers the POST with a `text/event-stream` body. The browser reads it with `fetch` + a small SSE reader
(`src/sse.js`; a native EventSource cannot POST). Frames: `event: job` (job id), `event: step` (one live text
from the channel's `on_step`), `event: done` (the channel's saved result: ticket id, status, reply, outcome),
`event: error` (the worker failed), and `: ping` comments every 15 s on an idle connection. The reader buffers
partial chunks and splits on blank lines, so a frame cut by the network is reassembled.

Duplicates: each send carries a fresh `client_id`. A second send while the customer's job runs is refused
(409 `busy_user`) unless it carries the same `client_id` (double click / retry): then the same job is returned.
A finished job with the same `client_id` is answered from memory, never run twice.

Disconnects: dropping the stream does **not** stop the worker; the channel finishes and saves its reply in the
tickets store. The screen says so ("Connection lost… NOT sent again") and offers **Check status**:
`GET /api/shop/chat/job` tells whether the job is still running (then the screen re-attaches to
`GET /api/shop/chat/job/stream`, which replays the steps so far) or finished (then the saved conversation is
reloaded). On page load a running job is shown as "CallVerse is still working on your last message" with Send
disabled. Jobs live in memory for 15 min after they finish; restarting the API forgets them (the conversation
itself is always read back from `callverse.db`).

Transport state (sending / disconnected / failed) is separate from the business outcome (`approve`, `busy`,
`not_your_order`, an outcome the UI has never seen…), which only comes from the saved result and is shown as
text; the channel's "busy" reply (Agent B's quota) is a normal outcome with its own note.

Security: the session is a random token kept in memory on the server; the browser only holds it in an
`HttpOnly; SameSite=Strict` cookie scoped to `/api`. Every `POST` must send `X-Requested-With: CallVerse` (no
CORS is enabled, so another site cannot add that header). The role is read from the accounts file on every
request through `callverse.auth.accounts.check_role`, never from the browser. The session lasts
`CALLVERSE_WEBUI_SESSION_HOURS` (default 8); restarting the API logs everyone out.

## Design

Two themes on the same components: the Console (dark, `tokens.css`) and ShopNova (light, paper `#FBF7F2`,
navy `#1F2A44` text and primary buttons, coral `#FF6B4A` accent; `styles/themes.css`, switched by
`data-theme` on `<html>` per area). Tokens in `frontend/src/styles/tokens.css` (background `#0B1220`, panels `#152033`, text `#E2E8F0`, muted
`#94A3B8`, primary `#2DD4BF` with `#0B1220` text; Open Sans body 16 px, Poppins 600 headings 24–28 px, tables
14 px; 4/8 px spacing; 8 px controls, 12 px panels). Components use only these variables. SVG icons in
`components/Icon.jsx`, visible focus rings, `prefers-reduced-motion` honoured, phone layout from 375 px.
