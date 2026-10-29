# CallVerse + ShopNova UI — design doc (draft for Yassine's OK)

**Date:** 2026-10-29 · **Author:** the Brain · **Status:** APPROVED by Yassine 2026-10-29 10:15 (with option A: one ShopNova Admin). Built in T16–T19.
**Agreed so far (2026-10-29, all ⭐):** Streamlit; two separate apps; design doc first; ShopNova app first; a separate
CallVerse database for tickets; `streamlit-authenticator`; 4 roles; demo accounts only; chat after login; pages below;
CRUD scope below; simple "buy"; real Layer 3 queue with the stub as a config backup; Agent B's Groq setting as its own
small task first; live steps while waiting; style shown as a mock first; English; ports 8501 / 8502, localhost only;
Dali's `/demo` page kept until the Console replaces it; automatic page tests.

## 1. The big picture
```
 ShopNova app (8501)                       CallVerse Console (8502)
 users · admin                             CallVerse supervisor
   │  Help chat message                        ▲  reads only
   ▼                                           │
 channel: web_chat.send(user, text) ──► CallVerse pipeline (Intake → queue → agents → Coordinator → SLM)
   │                                        │ reads/writes company data ONLY through tools + writes.py
   │                                        ▼
   │                                   shopnova.db (company data: orders, refunds, reviews…)
   ▼
 callverse.db (the center's own data: tickets, messages, steps, approvals)  ◄── Console reads it
```
- **CallVerse is the main platform.** ShopNova is one company (user of the center); Atlas gets its own app later.
- Two databases, like a real outsourced center: the company's data (`shopnova.db`) and the center's tickets
  (`callverse.db`). The Console never writes company data.
- The ShopNova app reaches CallVerse through **one channel function** (the "channels layer" of our design), not by
  calling agents directly.

## 2. Folders (new)
```
apps/shopnova/   Home.py + pages/ (Shop, My orders, Help chat, Back office, Refund approvals) + .streamlit/config.toml
apps/console/    Home.py + pages/ (Live tickets, Ticket detail, Agents, Dashboard) + .streamlit/config.toml
callverse/tickets/   store.py (callverse.db: create/read tickets, messages, steps, approvals)
callverse/channels/  web_chat.py (send(user_id, company, text) → runs the pipeline, saves the ticket, returns the reply)
callverse/auth/      accounts.py (load hashed accounts, require_role helper)
scripts/create_demo_accounts.py   (Yassine runs it himself; writes the git-ignored accounts file)
```

## 3. Tickets (`callverse.db`)
| Table | Columns (main) |
|---|---|
| tickets | id (T-0001…), company, user_id, status, main_reason, priority, lead_agent, created_at, updated_at, closed_at |
| messages | id, ticket_id, sender (user / assistant / system), text, at |
| steps | id, ticket_id, message_id, step (intake / route / tool_call / search_policy / proposal / coordinator / layer3 / slm / write / error), agent, data (JSON), at |
| approvals | id, ticket_id, order_id, amount, proposal_id, status (pending / approved / refused), decided_by, decided_at, reason |
- **Statuses:** New → Open → Waiting for user / Waiting for finance → Solved → Closed (our ticket lifecycle; auto-close
  after 3 days comes later).
- **One chat = one ticket** until it is solved; each user message is handled by the pipeline as today (no
  multi-turn memory yet: that is T14's "second question" item).
- **Steps** are copied from the pipeline result and its trace lines for that message, so the Console can replay
  "how the agents worked" without reading trace files.

## 4. Logins and roles
| Role | App | Can do | Demo accounts |
|---|---|---|---|
| User | ShopNova | Shop, buy, My orders, Help chat (own orders only) | the 5 scripted users (Sara, Youssef, Amira, Karim, Leila) |
| Admin | ShopNova | Admin dashboard, Manage (CRUD), Refund approvals — checked **per action** by permission (`view_dashboard`, `edit_catalogue`, `edit_orders`, `edit_users`, `approve_refunds`), so a separate finance role can be added later in a few lines; every admin action logged with who and when | 1 |
| Supervisor | Console | Everything in the Console (read only) | 1 |
- `streamlit-authenticator`, passwords **hashed** (bcrypt) in a **git-ignored** accounts file.
- `scripts/create_demo_accounts.py` is run **by Yassine** in his own terminal: it asks for each password (or makes
  random ones and shows them once). Claude Code never sees the passwords.
- Every protected page starts with `require_role(...)`; without the right role, the page shows only "please log in".
- Real Olist users have no login (no passwords): they exist only as data.

## 5. ShopNova app (port 8501)
| Page | Who | What |
|---|---|---|
| Shop | everyone (buy needs login) | catalogue by category, search, product cards; **Buy**: creates a `processing` order (card or cash on delivery; no real payment) |
| My orders | user | own orders, status, promised / delivered dates, delivery line, refunds; button "Ask about this order" → Help chat |
| Help chat | user | chat with CallVerse; live steps while waiting ("Reading your message…", "Checking your order…", "Checking the rules…", "Writing the reply…"); ticket number shown |
| Admin dashboard | admin | the company's business view: sales (TND) per day, orders by status, late deliveries, stuck parcels, refunds paid, top products and categories, review scores, low stock |
| Manage | admin | Products: add, edit, delete, stock · Orders: view, change status only through allowed moves, cancel (no delete) · Users: add, edit (no delete) · Refunds: view only |
| Refund approvals | admin | refunds above 300 TND waiting: order, user, amount, rule, agent's facts → **Approve** / **Refuse** + reason |

## 6. CallVerse Console (port 8502)
| Page | What |
|---|---|
| Live tickets | all tickets, all companies: id, company, user, reason, priority, status, lead agent, age; filters |
| Ticket detail | the conversation + the step-by-step timeline: Intake (reason, emotion, priority, order id) → route → each tool call and policy search → proposal → Coordinator decision + why → Layer 3 → reply writer (source slm / retry / template) → writes |
| Agents | per agent: tickets handled, proposals, approved / sent back / escalated, errors, avg time |
| Dashboard (KPIs) | tickets per day and per company · % solved by AI alone · % sent to Layer 2 / Layer 3 · avg time to reply · refunds approved / refused + TND paid · late replies (SLA) · user satisfaction (reviews; agent F later) · tokens per ticket |

## 7. Layer 3: real approval queue
1. The Coordinator reaches a refund above 300 TND (R-ESC-01).
2. With `layer3.mode: queue` (config), it records an **approval** row (pending) instead of calling the stub; the ticket
   becomes **Waiting for finance**; the user gets: "Your refund needs approval from our finance team. We will reply
   here as soon as it has been reviewed." (our fallback wording, no time promise).
3. The admin approves / refuses in the app → the decision is recorded on the proposal → if approved, `create_refund`
   (writes.py, same safety net) → a new assistant message on the ticket (written by the SLM from the decision) →
   ticket Solved.
4. `layer3.mode: stub` keeps today's behaviour (tests, demo backup).

## 8. Safety rules (checked by tests)
- **Every write goes through `callverse/data/writes.py`.** New write functions (create/edit/delete product, create
  order, create/edit user, record approval) are added there with input checks and tests, and are **never** in an
  agent's allow-list.
- No delete on orders, refunds, users, tickets, approvals. Orders: cancel only.
- Inputs checked: prices > 0, stock whole number ≥ 0, quantities 1–10, statuses only through allowed moves.
- **Identity check:** in the Help chat, an order that is not the logged-in user's → "This order is not on your
  account" (no data shown, no agent action).
- Login checked on every protected page and before every write (not only by hiding buttons).
- Passwords hashed; accounts file and `callverse.db` git-ignored; no keys in code; both apps on 127.0.0.1 only.
- Automatic tests with Streamlit's `AppTest`: each page loads; protected pages refuse without login; each write
  path works and refuses bad input; the chat saves a ticket with steps (fake LLM, no API calls in tests).

## 9. Task split (proposal)
1. **T16** — Agent B's own model setting (Groq gpt-oss-120b, option A) — small.
2. **T17** — tickets store + channel + logins + ShopNova: Shop, My orders, Help chat.
3. **T18** — ShopNova Admin: Admin dashboard + Manage (CRUD) + Refund approvals (real Layer 3 queue).
4. **T19** — CallVerse Console: Live tickets, Ticket detail, Agents, Dashboard (KPIs); then retire Dali's `/demo`.
5. Later: Atlas app (same template).

## 10. Decisions after the draft
- 2026-10-29 10:13–10:15: style mock approved ("looks good"); **option A**: staff + finance merged into one ShopNova **Admin** (dashboard + CRUD + refund approvals), permission per action, actions logged; task split T16–T19 approved. Roles: user · admin · CallVerse supervisor. Demo accounts: 5 scripted users + 1 admin + 1 supervisor.
