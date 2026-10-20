# P05 — ShopNova platform as a local server (localhost)

## Why
Today the platform is Python functions only. We want it to run as a **local server on this PC** so that:
- we can open it in a browser and show the professor the company, the data (with AI-generated labels), the rules and
  what happened (refunds, events, traces);
- later, the agents and the Coordinator can call it over HTTP. **Integration with intake / agents / `main` comes at
  the end, not in this task.**

## Hard limits
- **Localhost only**: bind to `127.0.0.1`, never `0.0.0.0`. No deployment, no cloud.
- The server is a **thin layer over the existing functions** (`shopnova_tools.py`, `writes.py`, `layer3.py`,
  `policies.py`, `seed.py`). No business logic is copied into the server.
- Agents keep their allow-lists: any "agent" call goes through `registry.run_tool()`. Write functions stay out of
  every allow-list.
- Do not change agents, `llm.py`, intake, `registry.py` allow-lists, policies, seed data or tool shapes.
  Scripted orders and demo RESULT lines stay identical.
- Tests use the temporary DB only; the real `shopnova.db` stays unchanged by the tests.
- No secrets in files. Do not merge anything (not intake, not `main`).

## What to do
1. **Dependencies**: add `fastapi` and `uvicorn` to `requirements.txt` (already installed on this PC; `httpx` is
   needed for the tests). Nothing else.
2. **App** — `callverse/server/app.py` (FastAPI). Endpoints (JSON, return exactly what the functions return):
   - Read (dashboard / anyone on this PC):
     `GET /company`, `GET /policies`, `GET /policies/{rule_id}`,
     `GET /orders?status=&scripted=&limit=50` (list), `GET /orders/{id}`, `GET /orders/{id}/tracking`,
     `GET /orders/{id}/refunds`, `GET /users/{id}`, `GET /summary` (same numbers as `scripts/data_summary.py`;
     move the counting into one function both use, don't copy it).
   - Agent tool call: `POST /tools/{name}` with body `{"agent": "A", "args": {...}}` → `registry.run_tool(agent, name, args)`.
     A tool outside the agent's allow-list → refused (as today), HTTP 403.
   - Coordinator writes: `POST /coordinator/refunds`, `POST /coordinator/subscriptions`,
     `POST /coordinator/orders/{id}/status`, `POST /layer3/decide`. They need the header
     `X-Coordinator-Token` equal to `PLATFORM_COORDINATOR_TOKEN` from `.env`. If the variable is missing, all write
     endpoints are refused (HTTP 403), so writes are off by default. A refused write returns the function's
     `{"error": ...}` with HTTP 400.
   - `POST /admin/reset` (same token): re-seed the DB, for demos.
   - Every request goes through the existing trace system (one line per call, actor = `server`, agent id when given).
3. **Dashboard** — `GET /` returns one plain HTML page (no frontend framework, no build step, inline CSS/JS, works
   offline). It shows: the company profile; the orders table with status and **AI-generated / scripted labels**
   (filter by status, scripted only); click an order to see its tracking and refunds; the 8 policies; refunds,
   subscriptions and events tables; the last 20 trace lines. Read-only: no buttons that write.
4. **Run script** — `scripts/run_platform_server.py`: starts uvicorn on `127.0.0.1:8000`, prints the URL and
   `/docs` (FastAPI's built-in API page). Add a "Run the platform server" section to the README.
5. **Demo over HTTP** — `scripts/demo_platform_http.py`: same S1, S2, S3 and extras as `demo_platform.py`, but through
   the HTTP endpoints (start the app in-process with FastAPI's `TestClient`, so no second terminal is needed).
   The RESULT lines must match `demo_platform.py`.
6. **Tests** — `tests/test_server.py` with `TestClient`:
   - `GET /orders/4512/tracking` → `days_late` 6; `GET /orders?scripted=1` → 11 orders; `GET /summary` → 131 orders.
   - `POST /tools/get_tracking` as agent A → 200; `POST /tools/get_refunds` as agent A → 403 (not on A's list).
   - Write endpoint without token / wrong token / env var missing → 403, no DB change.
   - With token: refund 59.90 on 4512 → 200 `approved`; 70.00 → 400 (safety net); `nan` amount → 400.
   - `GET /` returns HTML containing "ShopNova".
   - The server binds to `127.0.0.1` (check the run script's settings).
7. **Contract** — `docs/platform_contract.md`: new §8 "Local server" (endpoints, token rule, localhost only).
   Add `PLATFORM_COORDINATOR_TOKEN=` (empty) to `.env.example`.

## Checks (with numbers)
- `python scripts/run_platform_server.py` → open `http://127.0.0.1:8000/` → dashboard shows 131 orders, 11 scripted;
  `http://127.0.0.1:8000/docs` lists every endpoint. (Report what you saw; a screenshot is welcome.)
- `python scripts/demo_platform_http.py` → exit 0, RESULT lines identical to `python scripts/demo_platform.py` (diff).
- All tests pass (report x/y, the 68 old ones included). Real `shopnova.db` unchanged by the tests.
- `git grep 0.0.0.0` finds nothing in the server code.

## Time box and stop rule
2 hours. Stop and ask if a step needs a change to a tool shape, an allow-list or the agents.

## Git
Work on branch `platform`, commit and push it. **Do not merge** intake or `main` (integration is a later step).
Write `tasks/P05_report.md` (6-section format) and set `tasks/NEXT_PLATFORM.md` to WAITING FOR REVIEW.
