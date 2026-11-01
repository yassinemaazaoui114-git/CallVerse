# CallVerse UI (React + Node + FastAPI) — brief for Dali

Draft 2026-11-01 · Owner: Dali · Approver: Yassine · Reviewer: Brain. This UI **replaces** the three Streamlit apps
(ShopNova 8501, Console 8502, Atlas 8503). Same behaviour, new look. Pages: see `docs/ui_design.md`.

## 1. Where to work
- Branch `feat/ui-react` from the latest `main`. All your code in a **new folder `webui/`** (`webui/api` = FastAPI, `webui/frontend` = React, Node for build/dev proxy).
- **Do not edit `callverse/`** (core is Yassine's lane and changes under you in T14c / RL1). If you need a change there, write it in a note to Yassine.
- No merge into `main` without Yassine's OK after the Brain's review. Never force push / rebase / reset a shared branch.

## 2. What the API layer must wrap (do not rewrite logic)
Your FastAPI is a **thin layer over existing Python functions** — import them, call them, return JSON.

| UI need | Call this | Notes |
|---|---|---|
| Chat (user sends a message) | `callverse.channels.web_chat.send(user_id, company, text, ticket_id=None, on_step=cb, about_order=None)` | Returns `{ticket_id, status, reply, outcome, reply_source, steps, seconds}`. Takes 5–60 s → run in a worker thread and stream `on_step` texts to the browser (SSE or WebSocket). One chat at a time is handled inside (lock). |
| Approve / reject a refund | `callverse.channels.approvals.decide(approval_id, admin, approve, reason)` | It re-checks the proposal itself (`recheck`). Atlas is handled inside. |
| Console pages (tickets, detail, dashboard, agents, refunds, satisfaction, Groq today) | `callverse.console.reads.*` (`live_tickets`, `ticket_detail`, `dashboard`, `agents`, `satisfaction`, `groq_today`, …) | Read-only. |
| Atlas pages (my bookings, dashboard, hotel/flight lists, refunds, compensations, admin log) | `callverse.data.atlas.atlas_app_reads.*` | Read-only. |
| ShopNova platform data (orders, tracking, refunds, clock) | existing server `callverse/server/app.py` GET routes (`/orders`, `/orders/{id}`, `/refunds`, `/clock`, …) | Localhost only. It has **no chat, no login**. |
| Login / roles | `callverse.auth.accounts` (`account`, `check_role`, `check_permission`) | Reuse. Do not invent a second user store. |
| Writes (admin actions) | only the functions in `callverse/data/writes.py` (+ `approvals.decide`) | **Never write SQL from the UI.** |

If a function you need is missing, list it for Yassine — do not copy logic into the UI.

## 3. Rules
- Localhost only (127.0.0.1). No secrets in git; keys stay in `.env` (never read or print it). Passwords hashed; cookie/JWT session; every admin route checks role + permission.
- The UI **shows what the pipeline returns**: no hard-coded outcome/rule lists. New outcomes will appear (T14c adds `decline` for Atlas, `ask_proof`, a "photo proof received" flag on approvals). Unknown outcome → show it as plain text, never crash.
- Layer 3 (human approval) stays: refunds above the limit and every Atlas compensation go to the admin queue; the UI must not offer a way around it.
- Real LLM limits: Groq free ≈ 25 refund chats/day. Show the Console "Groq today" number; add a "busy / quota reached" message instead of an error page.
- Keep the Streamlit apps running until Yassine says the new UI is accepted (they are your behaviour reference).

## 4. How to run (current main)
1. Ollama running (local models). 2. `.env` has the Groq key (do not open it). 3. Seed the databases with the commands in `docs/DEMO_RUNBOOK.md`.
4. Demo accounts: see `docs/DEMO_RUNBOOK.md` / `callverse/auth/accounts.py`. 5. Run API on 127.0.0.1 and `npm run dev` for the frontend.

## 5. Deliver in this order (each step = small PR-sized commit, report to Yassine)
1. API skeleton + login + `GET /company`, read-only Console list/detail (no LLM, no quota).
2. ShopNova user page: orders, order detail, "ask about this order".
3. Chat with live steps (SSE) — test with the scripted users first.
4. Admin approvals (approve/reject, reason).
5. Atlas user + admin pages. 6. Dashboard / agents / satisfaction. 7. Polish + screenshots in `docs/screenshots/`.
Tests: API tests with a fake `chat_fn` (as the existing tests do); at least one test per route. Report format: In plain words · Numbers · Problems · Questions for the Brain · Next step.
