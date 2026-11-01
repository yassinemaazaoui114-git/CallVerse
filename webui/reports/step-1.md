# UI replacement — step 1 report (for Yassine)

Branch `feat/ui-react` (from `origin/main` at `21f1167`, T14b merged) · folder `webui/` · 2026-11-01 · Dali's lane.
Nothing outside `webui/` is changed except a two-line pointer in the main `README.md`.

## 1. In plain words

The new CallVerse UI has its first working piece: a small web API in front of the existing Python functions, and
a React site with three screens: **Log in**, **Live tickets** and **Ticket detail**, for the supervisor only.
Nothing new is computed: the API calls `callverse.console.reads` (the same read-only functions the Streamlit
Console uses) and the existing accounts file; it loads no model and never writes a database. The screens follow
the approved dark "control room" look, work on a phone, refresh the ticket list every 10 seconds without losing
the user's place, and show clear messages when the API is down, the session expired, the account is not the
supervisor or a ticket does not exist. The Streamlit apps are untouched and still the reference.

## 2. Done

- `webui/api/`: FastAPI app (`app.py`), settings, `auth.py` (login against the existing bcrypt hashes with
  `bcrypt.checkpw`, in-memory sessions, HttpOnly + SameSite=Strict cookie, `X-Requested-With` check on every
  POST), `console_reads.py` (wrappers: Live tickets rows, filter values, ticket detail with each step described
  by `reads.describe_step` next to its raw data, the Coordinator decision per message, tool calls and policy
  searches listed), `run.py` (127.0.0.1:8610), `dev_fixture.py` (temporary accounts + 6 example tickets for a
  demo without the pipeline).
- Routes: `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/session`, `GET /api/company`
  (ShopNova through `shopnova_tools.get_company_profile`, the platform server's function; Atlas through its
  profile file from the company registry, see Problems), `GET /api/console/tickets` (4 filters),
  `GET /api/console/tickets/filters`, `GET /api/console/tickets/{id}`, `GET /api/health`.
- `webui/frontend/`: React 18 + Vite 5, JavaScript, 3 dependencies (react, react-dom, react-router-dom). Design
  tokens (`styles/tokens.css`), one SVG icon set, skip link, visible focus, reduced motion. Screens: Login
  (show/hide password, error focused for screen readers, "session expired" / "logged out" notices), Live
  tickets (filters kept in the URL so Back keeps them; refresh every 10 s that keeps the data and the focus;
  status line with the last successful update; refresh-failure alert with Retry; empty / no-match / loading /
  unavailable / supervisor-only states), Ticket detail (identity + badges, computer time vs simulation time
  marked, finance approvals, conversation beside the processing panel on wide screens and stacked on phones,
  select a message to see its steps, Coordinator decision highlighted, timeline, disclosures for tools, policy
  evidence and raw steps, missing-ticket state; unknown statuses / outcomes / steps shown as plain text).
- `webui/api/tests/`: 15 tests (conftest with temp accounts + temp databases + `llm.chat` made to fail).
- `webui/README.md` (setup, run, test), this report, 11 screenshots in `webui/reports/screenshots/`.
- Used the `ui-ux-pro-max` skill for guidance: kept its accessibility, table-overflow, live-status, focus,
  reduced-motion and breakpoint rules; discarded its landing-page / glassmorphism / Fira font suggestions
  (not this product; the brief's colours and fonts win).

## 3. Numbers / evidence

| Check | Result |
|---|---|
| `python -m pytest webui/api/tests -q` | **15 passed** (12.9 s) |
| `python -m pytest tests/test_console.py -q` (existing Console tests, unchanged) | **34 passed** |
| Routes covered by at least one test | 8 / 8 |
| Invalid login (wrong password, unknown user, empty password) | 401 `bad_login` |
| Login without the `X-Requested-With` header | 403 `csrf` |
| Logout, reused old cookie, expired session | 401 on `/api/auth/session` afterwards |
| `sara`, `hedi` (users), `admin`, `atlas_admin` on the 3 Console routes | 403 `forbidden`; no login → 401 |
| Filters (company / status / priority / agent / combined / no match) | counts 1, 1, 1, 2, 1, 0 as expected |
| Missing ticket `T-9999` | 404 `not_found` (API) and "Ticket T-9999 does not exist" (screen) |
| Unfamiliar outcome `ask_proof` + unknown step `photo_proof_received` | shown as text, no crash (test + screenshot 03) |
| No model: `llm.chat` patched to fail; `torch`, `transformers`, `sentence_transformers`, `streamlit`, `callverse.pipeline`, `callverse.agents`, `web_chat` not imported | passed |
| No business write: tickets DB and company DB SHA-256 unchanged after every read; Atlas DB file never created | passed |
| `npm run build` | 44 modules, JS 191.8 kB (61.9 kB gzip), CSS 13.8 kB |
| Browser (built-in, desktop ~1000 px and phone 375×812) | login ✔, wrong password ✔, filtered list from URL ✔, keyboard focus kept across a 10 s refresh ✔, open ticket by link ✔, Back keeps `?company=atlas` ✔, message selection ✔, admin → "Supervisor only" ✔, API stopped → "Refresh failed… table still shows data from 12:33:07" ✔, full-page "API not reachable" + Retry ✔, API restarted → "Your session expired" ✔, no horizontal scroll at 375 px (`scrollWidth` 375 = `clientWidth`) ✔ |
| Real data touched | none: no `config/accounts.yaml` and no `callverse/data/*.db` exist on this PC (checked before and after); the demo used a temp folder |

Screenshots: `webui/reports/screenshots/01_login.jpg` … `11_phone_detail_steps.jpg`.

## 4. Problems

- **`GET /api/company` for Atlas** does not call `callverse.tools.atlas_tools.get_company_profile`: importing
  that module pulls in `callverse.kb.search` (the embedding index), which the brief forbids for this step. The
  route reads the same JSON file through `callverse.companies.path("atlas", "profile_file")` (3 lines, no logic).
  If you prefer, a tiny `callverse` change (move Atlas's profile read next to ShopNova's) would remove this.
- **Sessions live in memory**: restarting the API logs everyone out (fine for a one-PC demo; the UI shows
  "session expired"). No login rate limit beyond bcrypt's cost (~0.1 s per try).
- **The Streamlit cookie is not shared**: the new UI has its own login (the brief's cookie/JWT session), so the
  Console's Streamlit cookie and the new cookie are independent.
- **"No tickets yet"** state is covered by an API test only; not looked at in the browser (the demo fixture
  always has tickets).
- **Dev proxy only**: in step 1 the built `dist/` is not served by the API yet (npm dev server + proxy). Serving
  the static build from FastAPI is a few lines for a later step.
- The Vite dev server also answers on `http://localhost:5173`; the first blank render I saw there was a
  transient of the preview tab, the app works on both names. Both servers bind to 127.0.0.1.
- Not committed on purpose: `.claude/launch.json` (my local preview config) and `.agents/` (the installed skill,
  already untracked on `main`).

## 5. Questions for the Brain

1. `GET /api/company` for Atlas through the profile file (above): acceptable, or should Yassine expose a light
   Atlas profile function in `callverse/`?
2. Session length: 8 h in memory. OK for the demo, or do you want a signed cookie that survives an API restart?
3. The Live tickets rows keep the read layer's key `"lead agent"` (with a space) unchanged, as the brief asks
   ("existing ticket fields from the read layer"). Keep, or rename to `lead_agent` in the API for the next steps?
4. Step 2 is the ShopNova user page. Its data comes from the platform server's GET routes (`/orders`, …), which
   run on port 8000 with no login. Should the new API call that server over HTTP, or import the same functions
   (`reports.list_orders`, `shopnova_tools.get_order`, …) directly as it does for the Console? (Importing is
   simpler and needs no second process.)

## 6. Next step

Step 2 of the brief: the ShopNova user page (orders, order detail, "ask about this order" button that only
prepares the chat; the chat itself is step 3). Before that: your review of this step and the four answers above.
