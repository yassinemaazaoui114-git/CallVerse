# CallVerse web UI (React + FastAPI) — `webui/`

The new UI that will replace the three Streamlit apps (brief: `docs/UI_replacement_brief.md`). It is built in
steps; this folder holds **step 1**: the API skeleton, login, `GET /company`, and the supervisor's Console
**Live tickets** and **Ticket detail** screens (read only, no model, no chat).

```
webui/
  api/            FastAPI: a thin layer over callverse/ functions (no business logic here)
    app.py        the routes            settings.py   ports, cookie, env overrides
    auth.py       login + sessions      console_reads.py  wrappers around callverse.console.reads
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

Open <http://127.0.0.1:5173> and log in as `supervisor`. Any other role can log in but sees "Supervisor only".

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
| `GET /api/health` | anyone | `{ok: true}` |

Errors always look like `{"error": "<code>", "message": "<words>"}` (`not_logged_in` 401, `forbidden` 403,
`csrf` 403, `bad_login` 401, `no_accounts` 503, `not_found` 404).

Security: the session is a random token kept in memory on the server; the browser only holds it in an
`HttpOnly; SameSite=Strict` cookie scoped to `/api`. Every `POST` must send `X-Requested-With: CallVerse` (no
CORS is enabled, so another site cannot add that header). The role is read from the accounts file on every
request through `callverse.auth.accounts.check_role`, never from the browser. The session lasts
`CALLVERSE_WEBUI_SESSION_HOURS` (default 8); restarting the API logs everyone out.

## Design

Tokens in `frontend/src/styles/tokens.css` (background `#0B1220`, panels `#152033`, text `#E2E8F0`, muted
`#94A3B8`, primary `#2DD4BF` with `#0B1220` text; Open Sans body 16 px, Poppins 600 headings 24–28 px, tables
14 px; 4/8 px spacing; 8 px controls, 12 px panels). Components use only these variables. SVG icons in
`components/Icon.jsx`, visible focus rings, `prefers-reduced-motion` honoured, phone layout from 375 px.
