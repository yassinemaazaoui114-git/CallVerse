# UI replacement — step 6 report (for Yassine)

Branch `feat/ui-react` · after the step-5 correction `ed353dd` · folder `webui/` · 2026-11-01 · Dali's lane.
`callverse/` unchanged, Streamlit apps unchanged, no merge into `main`. No step 7.

## 1. In plain words

The dashboards are in the new UI: the supervisor's **Dashboard** (the center's KPIs, the money per company,
Groq tokens used today, tickets per day / per company, tokens per ticket, tickets by status) and **Agents**
(one card per agent of the pipeline), and the two business dashboards for the **ShopNova** and **Atlas**
admins (sales, orders, late deliveries, reviews, low stock; cancellation and delay rates, bookings by status,
upcoming arrivals and departures). Every number is computed by the core's own functions, the same ones the
Streamlit pages call; the API only passes them on with the period list and the clock each read uses, and the
screens draw them. Periods are each read's own (the Console counts in computer time because the demo clock
does not move; the company dashboards count in the simulation clock), and the screen says which. A missing
value (no review, no timed reply) shows "—", never 0. Charts are plain bars with the values written next to
them and a "Show as table" switch; a period change keeps the previous numbers dimmed until the new ones arrive
and ignores a late answer of the old period. Checked in the browser with the demo fixture on desktop and phone.

## 2. Done

- **API** (`app.py`): `GET /api/console/dashboard?days=`, `GET /api/console/agents?days=`, `GET /api/console/groq`
  (supervisor; `reads.dashboard` / `agents` / `groq_today`, periods `reads.PERIODS`, `has_tickets`, clock
  "computer time"), `GET /api/admin/dashboard?days=7|30|90` (ShopNova admin with `view_dashboard`;
  `admin_reads.dashboard`, its `PERIODS` / `DEFAULT_PERIOD` / `LOW_STOCK`), `GET /api/atlas/admin/dashboard?days=7|30|all`
  (Atlas admin with `view_dashboard`; `atlas_app_reads.dashboard`, its `PERIODS` / `UPCOMING_DAYS`). Other periods →
  400 `bad_period`; the company dashboards sit behind `data_ready` (503, nothing seeded).
- **Frontend**: `components/Chart.jsx` (`BarChart`, `ColumnChart` as SVG with an `aria-label` listing every
  value, the values printed next to the bars, a "Show as table" toggle rendering a real table; `Stat` tiles;
  `fmt` → "—" for null), `components/Period.jsx` (period in `?days=`, options from the API), screens
  `ConsoleDashboard`, `ConsoleAgents`, `ShopAdminDashboard`, `AtlasAdminDashboard`; `useGuardedLoad` gained a
  `keep` option (previous answer kept, dimmed with `aria-busy`, while the next period loads; the old request is
  aborted and its late answer dropped). Menu entries Agents / Dashboard (Console), Dashboard (both admin areas).
  Phone fixes found on the way: grid panels shrink so wide tables scroll inside them; the top bar's logout
  becomes icon-only under 480 px (name kept for screen readers).
- **Tests**: `webui/api/tests/test_dashboards.py` (8) and `src/test/Dashboards.test.jsx` (5).

## 3. Numbers / evidence

| Check | Result |
|---|---|
| `python -m pytest webui/api/tests -q` (steps 1–6) | **79 passed** |
| `npm --prefix webui/frontend test` (steps 1–6) | **48 passed** (12 files) |
| `npm --prefix webui/frontend run build` | OK, JS 270.0 kB (80.8 kB gzip) |
| Console routes: no login 401; sara / admin / atlas_admin / hedi 403 `forbidden` | passed |
| Console dashboard: no tickets → `has_tickets false`, `dashboard null`; with a ShopNova and an Atlas ticket → tickets 2, escalated 1, per_company both; periods = the core's `{All, Last 7 days, Last 30 days}`; `days=90` → 400; a ticket dated 2020 falls out of "7" and stays in "all" (computer time) | passed |
| Agents: the five cards in pipeline order, Agent B's tokens and model, the Coordinator "rules (no LLM)", a `None` average passes through; Groq: exactly `{tickets, system, total, limit}` | passed |
| Console reads change no file, create no company file | passed |
| ShopNova dashboard: sara / atlas_admin / supervisor 403, no login 401; days 30 default, periods [7, 30, 90], 30 / 90 sales-per-day rows, `days=14` → 400; a `None` review average passes through | passed |
| Atlas dashboard: sara / admin / supervisor / hedi 403; periods `{7, 30, All}`, `days=7` → start 2026-10-03, `days=90` → 400; the ShopNova admin 403 | passed |
| Both admin dashboards → 503 `setup_required` without the company file, file not created | passed |
| Screens: a late 7-day answer after switching to 30 days is dropped (request aborted, old rows kept until the 30-day rows arrive); "—" for a missing satisfaction / reply time / review average; the chart's accessible name lists the values and "Show as table" renders them; Groq shown as given (4,050 of 200,000, meter value 4,050); empty "No tickets yet"; Agents "—" for a missing average; the Atlas rates as given; the denied box shows the API's words | passed |
| Browser (demo fixture, desktop): supervisor → Dashboard (7 tickets, 42.9 % solved by the AI, compensation 839.50 TND, Groq 7,320 of 200,000, money per company, four charts; screenshots 60–61), Agents (five cards with the core's numbers; 62); admin → ShopNova dashboard, 30 then 90 days (441 → 1,989 orders, "from 2026-07-12 to 2026-10-09 (simulation clock)"; 63); atlas_admin → Atlas dashboard, all then 7 days (2,006 hotel bookings, 37.5 % cancellation; 64) | ✔ |
| Browser, phone 375×812: Atlas dashboard with 7 days, `scrollWidth` 375 = `clientWidth` after the grid fix (65) | ✔ |
| Real model / money | none |

## 4. Problems and limitations

- **Tickets per day** draws the day totals (all companies); the per-company split stays in the table view and
  in the "Per company" chart (the Streamlit chart stacked the companies in one bar).
- **SVG text scales with the panel**: capped the chart width at 560 px so labels stay readable; on a very wide
  screen the charts do not fill the panel.
- **Not verified in the browser**: the Console dashboard's "No tickets yet" and "No tickets in this period"
  boxes, the ShopNova dashboard on a phone, the Console dashboard on a phone (same grid and components as the
  Atlas one, which was checked), the "stale while loading" dimming (covered by the screen test).
- The Console dashboard's satisfaction is still ShopNova's Olist review average (the core's note: not per
  ticket until agent F); the screen says so.

## 5. Questions / core blockers for the Brain

1. (still open from step 4) `approvals.finish(approval_id)` in the core for partial decisions.
2. Step 7 is "polish + screenshots in `docs/screenshots/`": the screenshots live under `webui/reports/screenshots/`
   today (the brief keeps the new UI under `webui/`). Copy the final set to `docs/screenshots/` in step 7, or
   keep them under `webui/`?
3. Serving the built `webui/frontend/dist` from the API (one process, no Vite in a demo) is a few lines; part of
   step 7?

## 6. Next step

Step 7 of the brief (polish, screenshots, the "busy / quota reached" message in the chat using Groq today).
After your review of this step.
