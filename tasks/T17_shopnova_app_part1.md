# T17 — ShopNova app, part 1: tickets, logins, Shop, My orders, Help chat (Streamlit)

## Why
UI direction (Yassine, 2026-10-29): two Streamlit apps — the **CallVerse Console** (main platform) and the
**ShopNova app** (the company's site). Design approved: `docs/ui_design.md` (copy of the Brain's `UI_design.md`,
already placed in the repo by the Brain; summary below). T17 builds the base (tickets store, channel, logins) and the 3 user pages. Admin
pages = T18, Console = T19. All details approved by Yassine on 2026-10-29 (18 design items + option A + 16 T17
items, all the Brain's ⭐).

## Hard limits
- **No change** to prompts, agents' logic, tools, the Coordinator, rules, Intake, SLM. The pipeline is called, not
  changed (the only pipeline-side addition allowed is a **listener hook** on `trace.log`, see step 6).
- **Every write to company data goes through `callverse/data/writes.py`** (new `create_order` there, with checks and
  tests, never in an agent allow-list). No raw SQL writes from the app.
- **No secrets in git:** `config/accounts.yaml` (hashed passwords) and `callverse/data/callverse.db` are git-ignored.
  Claude Code never creates real passwords: Yassine runs the account script himself. Never read or stage `.env`.
- Tests: 0 API calls (fake LLM). Never run `tests/data/*`. Apps bind to **127.0.0.1 only**.
- Before any live run: Yassine has restarted the PC / closed apps; stop if free RAM gets critically low (< 300 MB).

## Design summary (from `UI_design.md`, approved)
- Two databases: `shopnova.db` (company data, existing) and **`callverse.db`** (the center's tickets).
- The ShopNova app reaches CallVerse only through **one channel function** `callverse/channels/web_chat.py`.
- Roles: **user** (ShopNova), **admin** (ShopNova, T18), **supervisor** (Console, T19). Permissions checked per
  action. Demo accounts: sara, youssef, amira, karim, leila (= scripted users 1–5), admin, supervisor.
- Style (approved mock): ShopNova = warm and light (cream `#FBF7F2`, navy `#1F2A44`, coral `#FF6B4A`, rounded cards,
  "ShopNova ✦" logo, sidebar nav, floating "Need help? Chat with us" button). English.

## What to do
0. **Git.** `git fetch`, `git checkout main`, `git pull` (must include the T16 merge, pushed by Yassine; if not,
   stop and ask). Branch `feature/t17-shopnova-app`. Commit this task file + `tasks/NEXT.md` (IN PROGRESS) first.
   The Brain already placed the approved design doc at `docs/ui_design.md` (untracked): commit it on the branch
   unchanged.
1. **Libraries (item 2):** add `streamlit`, `streamlit-authenticator`, `bcrypt` to `requirements.txt` with **exact
   pinned versions** (latest stable that work together on Python of this repo; say which). Install in `.venv`.
2. **Tickets store** `callverse/tickets/store.py` → `callverse/data/callverse.db` (git-ignored, created on first use):
   tables `tickets` (id `T-0001`…, company, user_id, status, main_reason, priority, lead_agent, created_at,
   updated_at, closed_at), `messages` (id, ticket_id, sender user/assistant/system, text, at), `steps` (id, ticket_id,
   message_id, step, agent, data JSON, at), `approvals` (id, ticket_id, order_id, amount, proposal_id, status
   pending/approved/refused, decided_by, decided_at, reason — created now, used in T18). Statuses: New, Open,
   Waiting for user, Waiting for finance, Solved, Closed. Times from the simulation clock. Tests use a temp file.
3. **Ticket rule (item 11):** one chat = one ticket. A ticket becomes **Solved** when the decision is final
   (approve / info / refused / off-topic answer); `ask_user` / `ask_proof` → **Waiting for user**. A new message on a
   Solved ticket **within 3 days** (sim clock) reopens it (**Open**); after 3 days, or after "New chat", a new ticket.
   Each user message is still handled by the pipeline on its own (no multi-turn memory: T14).
4. **Logins (items 3–4):** `callverse/auth/accounts.py`: load `config/accounts.yaml` (streamlit-authenticator
   format, bcrypt hashes), `require_role(role)` helper used at the top of every protected page **and** before every
   write. `config/accounts.example.yaml` (usernames + roles + user_id links, no passwords) is committed.
   `scripts/create_demo_accounts.py`: Yassine runs it himself; it asks for each password twice (hidden input) or
   offers random ones shown once; writes `config/accounts.yaml`. Add `config/accounts.yaml` and `callverse.db` to
   `.gitignore`. Accounts: sara→user 1, youssef→2, amira→3, karim→4, leila→5 (role user), admin (role admin),
   supervisor (role supervisor).
5. **Channel** `callverse/channels/web_chat.py`: `send(user_id, company, text, ticket_id=None, on_step=None)`:
   - **Quota check (item 9):** before calling, check B's Groq models (extend `scripts/quota_check.py` logic into a
     reusable function that also checks `agent_b`; cache the result for a few minutes). If used up → reply
     "Our assistant is busy, please try again later." and **no** pipeline call; ticket stays Open; step logged.
   - **Identity check (item 12):** run Intake; if it finds an order id that is **not** this user's order → reply
     "This order is not on your account." with **no** agent call and no data shown. No order id → pipeline as today.
   - Otherwise call the pipeline (`handle_ticket` on the Intake ticket), save the user message, the reply, and the
     steps; update ticket status / main_reason / priority / lead_agent. Never crash: any error → the pipeline's own
     escalate reply, error step saved.
   - **Models (item 8):** the app sets `CALLVERSE_AGENTS_SET=local` at start (Intake + A local, B on Groq, T16).
6. **Live steps (item 10):** a small listener in `callverse/trace.py` (register / unregister a callback called by
   `trace.log`, no other change); the channel registers it for the duration of one message and passes friendly
   step texts to `on_step` ("Reading your message…", "Checking your order…", "Checking the rules…", "Checking with
   our refund team…", "Writing the reply…"). The same events are saved as `steps`.
7. **New write `create_order` (item 7)** in `writes.py`: user must exist; product must exist and have stock;
   quantity 1–10; payment `card` or `cash_on_delivery` (paid 0 until delivered); status `processing`; order_date =
   sim today; **promised_date = today + 25 days** (profile median); items JSON like the real orders incl. no
   delivery line (shop fee 0 for now — say so); stock decreases; `source = 'app'`, `ai_generated = 0`, `scripted = 0`.
   Refusals return `{"error": ...}` like the other write functions. Never in an agent allow-list.
8. **ShopNova app** `apps/shopnova/` (`Home.py` + `pages/`, `.streamlit/config.toml` with the approved colours):
   - **Shop** (everyone; Buy needs login): "Featured" = the 6 scripted products on top; then all products with
     search, category filter, **24 per page**; one **icon per category** (item 6); Buy → `create_order`.
   - **My orders** (user): own orders only — status, promised / delivered dates, lines incl. Delivery, refunds;
     "Ask about this order" → opens Help chat with the order number filled in.
   - **Help chat** (user): `st.chat_message` history of the current ticket, ticket number shown, live steps while
     waiting, "New chat" button.
   - Login / logout in the sidebar (streamlit-authenticator). Admin pages are **not** in this task (T18).
9. **Start script (item 13)** `start_shopnova.ps1`: checks Ollama answers, sets `CALLVERSE_AGENTS_SET=local`, runs
   `streamlit run apps/shopnova/Home.py --server.address 127.0.0.1 --server.port 8501`. README: how to create
   accounts and start the app.
10. **Tests (item 14), offline:** store (create / reopen / new ticket after 3 days / statuses); channel with a fake LLM
    (ticket + messages + steps saved; quota-used-up path makes no call; identity check makes no agent call);
    `create_order` (all refusals + stock decrease + labels); `require_role` refuses without login / wrong role;
    Streamlit `AppTest`: each page loads, protected pages show only "please log in" without login, Buy refused
    without login. Full suite: **all pass**.
11. **Live proof (item 15), once, after Yassine has created the accounts and restarted the PC:** through
    `web_chat.send` (or the app), Sara (user 1) sends "My order 4512 is late, I want a refund please." Show: ticket
    id, status, steps saved, the reply, and the refund row written by the Coordinator in `shopnova.db`. Then reseed
    `shopnova.db` (`python -m callverse.data.seed`) and delete the test ticket DB so the demo starts clean.
    If Yassine has not created the accounts yet: call `web_chat.send` directly (no login needed for this proof).

## Checks (with numbers)
- Tests x/y (all pass); new tests listed; pinned versions listed.
- Live proof: ticket id, status, steps count + names, reply text, refund row (id, amount, rule, proposal), seconds,
  Groq tokens; 0 Gemini.
- Screenshots (or a description if not possible) of Shop, My orders (logged in as Sara), Help chat.
- `git status`: `config/accounts.yaml`, `callverse.db`, `.env` not tracked.
- One sentence each: is the app usable for a demo? what is fragile?

## Time box and stop rule
2 h. Stop and report if: `main` lacks the T16 merge, a test fails, any code would need a change to prompts / agents'
logic / Coordinator, a secret would end up in git, free RAM gets critically low, or Groq's daily limit answers.

## Git (approved by Yassine, 2026-10-29)
Commit and push `feature/t17-shopnova-app`. **No merge into `main`.** Write `tasks/T17_report.md` (In plain words ·
Done · Evidence · Problems · Questions for the Brain · Next step) and set `tasks/NEXT.md` to WAITING FOR REVIEW.
