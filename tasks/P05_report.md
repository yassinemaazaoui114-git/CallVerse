# P05 report — ShopNova platform as a local server (localhost)

## 1. In plain words
The ShopNova platform now runs as a small website on this PC only (`http://127.0.0.1:8000`). Opening it in a browser
shows the company, all 131 orders with their "AI-generated" and "scripted" labels, the 8 rules, refunds,
subscriptions, events and the latest log lines. It is read-only: there is no button that changes anything. Agents will
later be able to ask for data over the web, still limited to their allowed tools. Changes (refunds, statuses) are
possible only with a secret password set in `.env`, and they are switched off until someone sets it.

## 2. Done
- **Dependencies**: `fastapi`, `uvicorn` and `httpx` (needed by the test client) added to `requirements.txt`.
- **Server** `callverse/server/app.py` (FastAPI). It calls the existing functions and contains no business rules:
  - read: `/company`, `/policies`, `/policies/{id}`, `/orders` (filters `status`, `scripted`, `limit`), `/orders/{id}`,
    `/orders/{id}/tracking`, `/orders/{id}/refunds`, `/users/{id}`, `/summary`, plus `/refunds`, `/subscriptions`,
    `/events`, `/traces/recent` (added because the dashboard needs them);
  - agents: `POST /tools/{name}` → `registry.run_tool()`. Off the allow-list → 403;
  - Coordinator: `POST /coordinator/refunds`, `/coordinator/subscriptions`, `/coordinator/orders/{id}/status`,
    `/layer3/decide`, `/admin/reset`. All need `X-Coordinator-Token` = `PLATFORM_COORDINATOR_TOKEN` (constant-time
    compare). If the variable is missing → 403, so writes are off by default. A refusal from the function → 400;
  - a middleware writes one trace line per request (`http_request`, actor `server`, `agent` on tool calls).
- **Shared counting** `callverse/data/reports.py`: `summary()`, used by both `GET /summary` and
  `scripts/data_summary.py` (that script now only prints), plus `list_orders()` and `list_rows()`. No agent can reach them.
- **Dashboard** `callverse/server/dashboard.html`: one plain page with inline CSS and JS, no framework, works offline.
  It has stat tiles, the orders table with labels and filters (status, scripted only), order details on click
  (tracking + refunds), the company profile, the policies, refunds / subscriptions / events, and the last 20 trace lines.
  Values are inserted with `textContent` only (no HTML injection). The only button is "Refresh".
- **Run script** `scripts/run_platform_server.py` (`HOST = "127.0.0.1"`, port 8000; prints the URL, `/docs`, the DB
  and the trace file). README section "Run the platform server".
- **HTTP demo** `scripts/demo_platform_http.py`: S1, S2, S3 and extras through the endpoints, using `TestClient`
  in-process. It sets a random token for its own process only and never writes it to `.env`.
- **Tests** `tests/test_server.py` (15 tests).
- **Contract** §8 "Local server" (endpoint table, token rule, localhost only); `PLATFORM_COORDINATOR_TOKEN=` (empty)
  added to `.env.example`.

## 3. Evidence
- Tests: **83 passed / 83** (the 68 old tests + 15 new, 9.9 s). Real `shopnova.db` MD5 `56d970b1…b189` is the same
  before and after.
- `python scripts/demo_platform_http.py` → **exit 0**; its 8 RESULT lines are **identical** to `python scripts/demo_platform.py`
  (diffed). Real DB MD5 unchanged afterwards (the demo re-seeds at the end).
- Live server (`python scripts/run_platform_server.py`, checked with curl, then stopped):
  - `netstat`: `TCP 127.0.0.1:8000 LISTENING`, so it listens on localhost only.
  - `GET /` → 200 `text/html`, title "ShopNova Platform"; `GET /docs` → 200; OpenAPI lists **19 endpoints**
    (13 GET + 6 POST); the dashboard page itself is hidden from the API list.
  - `GET /summary` → 131 orders, 11 scripted, 120 generated, 131 labelled AI-generated. `GET /orders?scripted=1` → ids 4505–4515.
  - `POST /coordinator/refunds` with no token in `.env` → **403** "writes are disabled: PLATFORM_COORDINATOR_TOKEN is not set in .env".
  - `POST /tools/get_refunds` as agent A → **403**; the trace has `tool_refused` (registry) then `http_request` (server, agent A, 403).
- Dashboard: I could not open a browser from here, so I ran its JavaScript in Node 22 with a tiny fake page, against
  the live server:
  - stat tiles: "131 orders | 11 scripted (4505-4515) | 120 generated (5001-5120) | 131 orders AI-generated |
    42 late orders | 11 late > 5 days, not delivered | 10 cash on delivery unpaid | 19086.80 TND total paid | 7 / 909.20 TND refunds";
  - orders table: 131 rows, the first being 4505 with labels "AI-generated scripted"; the scripted filter → 11 rows;
  - 8 policies, 11 company fields, 20 trace lines;
  - clicking order 4512 → "stuck_at_depot, Days late 6, Delivered no, Rapid-Poste RP200052, Refunded 0.00 TND, AI-generated scripted".
  I have no screenshot; it is worth a quick look in a real browser.
- `git grep 0.0.0.0` in `callverse/`, `scripts/` and `tests/` → nothing. It appears only in the contract text "never `0.0.0.0`".

## 4. Problems
- **`data_summary.py` output changed in one place**: "shipped" and "processing" both have 12 orders. The old query left
  tied rows in whatever order SQLite returned; `summary()` now sorts ties by name, so "processing" is printed before
  "shipped". All numbers are the same.
- **Test warning**: Starlette prints a deprecation warning, "Using `httpx` with `starlette.testclient` is deprecated;
  install `httpx2`". Tests pass. I did not add `httpx2` (no new library without approval).
- **Writes are off on this PC**: `.env` has no `PLATFORM_COORDINATOR_TOKEN`, so the live server refuses every write.
  That is the intended default. To turn writes on, Dali or Yassine sets a value in `.env`; I didn't create a secret.
- **No authentication on reads**: anyone on this PC can read the data. That's acceptable for fictional data on localhost.
- A tool's own error (e.g. `get_order(9999)` through `POST /tools/get_order`) returns **200** with `{"error": ...}`,
  because for an agent this is a normal tool answer. Only an allow-list refusal is 403. The GET read endpoints return
  404 for the same case.
- Extra read endpoints (`/refunds`, `/subscriptions`, `/events`, `/traces/recent`) are not in the task list but are needed
  for the dashboard. They are read-only and listed in the contract.

## 5. Questions for the Brain
1. Should I add `httpx2` to silence the Starlette warning, or keep `httpx` until it breaks?
2. When agents move to HTTP: should `POST /tools/{name}` also need a token per agent? Today the agent id in the body
   is trusted, which is fine on localhost.
3. Is HTTP 200 for a tool's own `{"error"}` (and 403 only for allow-list refusals) the shape the core lane wants?

## 6. Next step
Integration (later, with Yassine): merge `platform` + `feature/intake` into `main` (`config.yaml`: keep both sections),
then decide whether agents and the Coordinator call the platform in Python (as today) or over HTTP, using
`POST /tools/{name}` and the `/coordinator/*` endpoints.

Git: committed on `platform` and pushed to `origin/platform`. Nothing merged (not intake, not `main`).
