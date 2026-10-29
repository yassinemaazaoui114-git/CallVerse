# T18 — ShopNova app, part 2: Admin dashboard, Manage (CRUD), Refund approvals (real Layer 3 queue)

## Why
T17 built the user side of the ShopNova app. T18 builds the company side (option A: one **Admin**, permission per
action, every action logged) and turns Layer 3 into a **real approval queue**: a refund above 300 TND (R-ESC-01)
waits for the ShopNova admin instead of the stub's fixed rule. Design: `docs/ui_design.md` §4, §5, §7, §8.
All details approved by Yassine on 2026-10-29 (21 T18 items + implementation choices, all the Brain's ⭐).
Console = T19.

## Hard limits
- **No change** to prompts, agents' logic, tools, allow-lists, rules, Intake, RAG, SLM. The only Coordinator change
  allowed is the **queue mode at step 6** (described in step 6 below). Default behaviour (`layer3.mode: stub`) must
  stay exactly as today: all existing tests and the practice set unchanged.
- **Every write to company data goes through `callverse/data/writes.py`** (new admin functions there, with input
  checks and tests, **never** in an agent allow-list). No raw SQL writes from the app. No delete on orders, refunds,
  users, tickets, approvals.
- Role checked at the top of every admin page **and** again just before every write (`require_permission`), never
  only by hiding a button.
- **No secrets in git.** Never read or stage `.env`. Never create or see passwords (`config/accounts.yaml` is
  Yassine's). Tests: 0 API calls (fake LLM). Never run `tests/data/*`. App on **127.0.0.1 only**.
- Before the live proof: Yassine has restarted the PC / closed apps; stop if free RAM < 300 MB.

## What to do
0. **Git.** `git fetch`, `git checkout main`, `git pull` (must be at **97bc1ff** or later = T17 merged; if not, stop
   and ask). Branch `feature/t18-shopnova-admin`. Commit this task file + `tasks/NEXT.md` (IN PROGRESS) first.

1. **Permissions** (`callverse/auth/accounts.py`): `PERMISSIONS = {"admin": ("view_dashboard", "edit_catalogue",
   "edit_orders", "edit_users", "approve_refunds")}` (users and supervisor: none of these).
   `check_permission(session, perm)` / `require_permission(perm)` like `check_role` / `require_role`. The existing
   `admin` account gets all 5. Tests: no login, user role, supervisor role → refused; admin → allowed.

2. **Navigation** (`apps/shopnova/`): switch the app to Streamlit's `st.navigation` so the sidebar shows
   **Shop · My orders · Help chat** to everyone and **Admin dashboard · Manage · Refund approvals** only when the
   logged-in account is admin. Each admin page still calls `require_permission` first (a typed URL shows only
   "please log in"). Same style as T17 (cream / navy / coral). Existing user pages keep working.

3. **Schema changes** (`callverse/data/seed.py`, `docs/platform_contract.md`):
   - `products.active INTEGER NOT NULL DEFAULT 1` (soft delete, item 6). The Shop and `shop_reads` show only active
     products; `create_order` refuses an inactive product. Old orders keep showing it.
   - New table **`admin_actions`** in `shopnova.db` (item 12): id, at (sim clock), admin (username), action, target
     table, target id, before (JSON), after (JSON). Written by each admin write function **in the same transaction**
     as the change (a change without its log line cannot happen).
   - Reseed needed after these changes (`python -m callverse.data.seed`); say so in the report.

4. **New admin write functions** in `writes.py` (all take `admin` = username; all return the new row or
   `{"error": ...}`; all add an `admin_actions` row; none in any agent allow-list):
   - `create_product(admin, name, category, price, stock)` · `update_product(admin, product_id, **fields)` (name,
     category, price, stock) · `deactivate_product(admin, product_id)` / `reactivate_product(admin, product_id)`.
     New ids = max + 1; `source = 'app'`, `ai_generated = 0`, `scripted = 0`; category from the existing list.
   - `admin_set_order_status(admin, order_id, new_status)`: only the moves in `STATUS_MOVES` + **`cancelled` only
     from `processing`** (not yet shipped); `refunded` is never set by hand (refunds only through Refund approvals).
     Cancelling puts the stock back.
   - `create_user(admin, name, email, phone, city)` · `update_user(admin, user_id, **fields)`. No login is created.
     City from `company_profile.json` `cities_served`. New ids = max + 1, `source = 'app'`.
   - **Input checks (item 9):** name not empty (after trim, ≤ 100 chars); price > 0 and ≤ 100,000 TND, 2 decimals;
     stock whole number 0–100,000; email contains "@" and is unique; phone = 8 digits, stored as
     `+216 XX XXX XXX`, unique.
   - **Price edits (item 10):** old orders keep the price stored in their `items` JSON. Add a test that proves it.

5. **Admin dashboard** page (permission `view_dashboard`), read-only queries in a new `callverse/data/admin_reads.py`.
   Period filter **7 / 30 / 90 days, default 30**, counted back from the simulation clock's today. **Altair** charts
   (bundled with Streamlit, no new library). Content (item 3):
   - sales in TND per day (sum of `total` of orders not cancelled, by `order_date`);
   - orders by status (count);
   - late deliveries (delivered after `promised_date`, or not delivered and past it) and stuck parcels
     (`stuck_at_depot`);
   - refunds paid (count + TND, statuses approved + completed);
   - top 10 products and top categories by quantity sold (the Delivery line not counted);
   - review scores (average + count per score 1–5);
   - low stock: active products with stock **≤ 5**.

6. **Real Layer 3 queue** (items 13–18):
   - **Switch:** `config.yaml` `layer3: {mode: stub, stub_max_approve_tnd: 500}` — default **stub** (today's
     behaviour). Env var `CALLVERSE_LAYER3_MODE=queue` turns the queue on: set by `start_shopnova.ps1` and by
     `shopnova_ui.py` with `setdefault` (same pattern as `CALLVERSE_AGENTS_SET`).
   - **Coordinator, step 6, queue mode only:** instead of calling `layer3_decide`, it returns a new outcome
     **`layer3_pending`**. The proposal stays **undecided** in the `proposals` table (decision NULL), so the admin's
     decision is the one recorded later ("decided once" kept). Nothing is written. `user_words` for
     `layer3_pending`: must_say "Your refund of X TND for order N needs approval from our finance team.", next_step
     "We will reply here as soon as it has been reviewed." (no time promise).
   - **Channel** (`web_chat.py`): on `layer3_pending`, create the `approvals` row (ticket, order, amount,
     proposal_id, status pending) and set the ticket to **Waiting for finance**.
     **Duplicate guard:** before the pipeline, if Intake's order already has a **pending** approval, reply
     "Your refund request for order N is already with our finance team. We will reply here as soon as it has been
     reviewed." with **no agent call** (a step "approval_pending" is saved). Other orders: pipeline as normal.
   - **Admin decision** (new module `callverse/channels/approvals.py`, called by the page):
     `decide(approval_id, admin, approve: bool, reason)`:
     1. the approval must be **pending** (checked inside a transaction: two clicks cannot decide twice);
     2. **re-check on fresh data before anything is written** (item 15): the Coordinator's own checks for this
        proposal run again — order exists, the cited rule's condition still holds, R-REF-05 (amount ≤ paid −
        already refunded). If a check fails on Approve: **nothing is written**, the approval stays pending, the
        page shows the reason in plain words (the admin can then Refuse);
     3. Approve: `record_decision(proposal, "approve", reason)` → `create_refund` (its safety net runs again) →
        R-REF-03: order status `refunded` (same as today's Coordinator path) → the `admin_actions` row.
        Refuse: **reason required**; `record_decision(proposal, "layer3", reason)`; nothing paid.
     4. the approval row: approved / refused, decided_by, decided_at (sim clock), reason;
     5. the **SLM writes a new assistant message** on the ticket from the decision: approve = today's words
        ("Your refund of X TND is approved after a check by our finance team." + the order's new status);
        refuse = today's `layer3_refused` words. **The admin's reason is never shown to the user** (stored only).
        The style comes from the Intake data saved in that ticket's steps (neutral style if missing);
     6. ticket → **Solved**, `user_unread = 1` (below). If `create_refund` still refuses (rare), the ticket gets
        the "extra check" (escalate) message, status Open, and the approval is marked refused with the reason.
   - **Notice (item 17):** new column `tickets.user_unread INTEGER NOT NULL DEFAULT 0` (added on connect if
     missing, so an old `callverse.db` keeps working). Help chat and My orders show "💬 New reply on T-00NN" with a
     button that opens that ticket; opening it sets `user_unread = 0`.
   - **Refund approvals page** (permission `approve_refunds`): pending list first (ticket, order, user name, amount,
     rule id + rule title, the agent's `facts_used`, order status / paid / already refunded, days late), then
     decided ones. **Approve** (reason optional) / **Refuse** (reason required). No amount limit (item 14).
   - **Seed:** no pending approvals (item 18).

7. **Manage** page (permissions per tab): Products (`edit_catalogue`), Orders (`edit_orders`), Users
   (`edit_users`), Refunds (view only, `view_dashboard`). Each table: search box + **50 rows per page** (item 11);
   add / edit forms with the checks of step 4; the error text of a refused write shown to the admin; an "Admin log"
   view of the last 50 `admin_actions`.

8. **Ticket label (T17 open question):** keep "📦 About order N" for the whole chat until "New chat" (no change if
   it already works that way; say so).

9. **Tests (item 19), offline, all pass:** permissions; every new write (success + each refusal + admin log row +
   no row on refusal); price edit keeps old order prices; inactive product hidden + not buyable; cancel only from
   processing + stock back; Coordinator queue mode → `layer3_pending`, proposal undecided, nothing written, and
   **stub mode unchanged**; channel creates the approval + Waiting for finance; duplicate guard makes no agent call;
   `decide`: approve writes the refund + message + Solved + unread; refuse writes no refund, admin reason not in the
   user message; re-check failure writes nothing; double decide refused; **no new write function in any allow-list**;
   AppTest: each admin page loads for admin and shows only "please log in" for no login / user / supervisor;
   admin pages not in a user's sidebar. 0 API calls.

10. **Live proof (item 20), once**, after Yassine restarted the PC: `start_shopnova.ps1` setup (queue on).
    Youssef (user 2, owner of order 4515, 378 TND, stuck at depot) sends "My order 4515 is very late, I want a
    refund please." through `web_chat.send` (or the app) → show the pending approval + ticket Waiting for finance +
    the user's reply. Then `decide(approve)` as admin → show the refund row, order status, approval row,
    admin_actions row, the new assistant message, ticket Solved. Groq tokens (about 7,500 expected), 0 Gemini.
    Then reseed `shopnova.db` and delete `callverse.db` so the demo starts clean.

## Checks (with numbers)
- Tests x/y (all pass); new tests listed.
- Live proof: approval id, ticket id + statuses (Waiting for finance → Solved), both replies word for word, refund
  row (id, amount, rule, proposal), seconds, Groq tokens, 0 Gemini.
- Stub mode: the practice-set path is untouched (show the stub tests still pass; no practice run needed).
- Screenshots (or a description) of Admin dashboard, Manage, Refund approvals, and a user's sidebar without admin
  pages.
- `git status`: `config/accounts.yaml`, `callverse.db`, `.env` not tracked.
- One sentence each: is the admin side usable for a demo? what is fragile?

## Time box and stop rule
**2 h.** Stop and report if: main is not at 97bc1ff or later, a test fails, any change to prompts / agents / tools /
rules / Intake / SLM would be needed, the default stub behaviour would change, a secret would end up in git, free
RAM < 300 MB, or Groq's daily limit answers.

## Git (approved by Yassine, 2026-10-29)
Commit and push `feature/t18-shopnova-admin`. **No merge into `main`.** Write `tasks/T18_report.md` (In plain words ·
Done · Evidence · Problems · Questions for the Brain · Next step) and set `tasks/NEXT.md` to WAITING FOR REVIEW.
Tell Dali (in the report's last line, for Yassine): schema changes `products.active`, `admin_actions`,
`tickets.user_unread`; outcome `layer3_pending`.
