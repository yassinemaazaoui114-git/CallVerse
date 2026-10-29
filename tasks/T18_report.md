# T18 report: ShopNova app, part 2 (Admin dashboard, Manage, Refund approvals = real Layer 3 queue)

Branch `feature/t18-shopnova-admin` (commits 8bd4d0f task + NEXT, c4b7756 build, + this report). Not merged into `main`.
Time: 15:47 → about 16:15 (about 30 min of the 2 h box). PC rebooted at 15:37, 1,969 MB free RAM before the live proof.

## 1. In plain words
ShopNova now has a company side. When the **admin** logs in, the sidebar also shows an **Admin dashboard** (sales,
orders, late parcels, refunds, top products, reviews, low stock), a **Manage** page (add / edit products, change an
order's status, add / edit clients, see refunds and the admin log) and **Refund approvals**. Clients never see these
pages, and a typed address only shows "please log in". Big refunds (above 300 TND) no longer go to the fixed "finance"
rule in the app: they **wait for the admin**. The client is told it is with finance; the admin clicks Approve or Refuse;
the data is checked again, the refund is written by the same safe write function as before, and the client gets a new
reply in the chat with a "💬 New reply" notice. Every admin change is logged with who, when, before and after.

## 2. Done
| Step | What | Files |
|---|---|---|
| 0 | Branch from `main` at 97bc1ff; task file + NEXT.md (IN PROGRESS) committed first | — |
| 1 | `PERMISSIONS` (admin: 5 permissions), `check_permission` (pure) / `require_permission` (stops the page) | `callverse/auth/accounts.py` |
| 2 | App starts from `app.py` with `st.navigation` (all pages registered, built-in list hidden); each page draws the sidebar menu with only the pages its account may use; admin pages call `require_permission` first and again before each write | `apps/shopnova/app.py`, `shopnova_ui.py`, `start_shopnova.ps1` |
| 3 | `products.active` (soft delete; Shop + `shop_reads` show active only; `create_order` refuses inactive); new table `admin_actions` | `callverse/data/seed.py`, `shop_reads.py`, `writes.py` |
| 4 | Admin writes with input checks, each with its `admin_actions` row in the same transaction: `create_product`, `update_product`, `deactivate_product`, `reactivate_product`, `admin_set_order_status`, `create_user`, `update_user`, + `log_admin_action` (refund decisions). `set_order_status`'s writing part moved into `_apply_status` (same behaviour) so the admin's status change uses it in its own transaction | `callverse/data/writes.py` |
| 5 | Dashboard reads (7 / 30 / 90 days, default 30, from the sim clock), Altair charts | `callverse/data/admin_reads.py`, `pages/4_Admin_dashboard.py` |
| 6 | Switch `layer3.mode` (config `stub`, env `CALLVERSE_LAYER3_MODE=queue` in the start script and the app with `setdefault`); Coordinator step 6 in queue mode → `layer3_pending` (proposal undecided, nothing written) + its `user_words`; channel creates the approval + "Waiting for finance" + duplicate guard; `approvals.decide`; `tickets.user_unread` (added on connect if missing) + notice in Help chat and My orders; Refund approvals page | `callverse/data/layer3.py`, `coordinator/coordinator.py`, `channels/web_chat.py`, `channels/approvals.py`, `tickets/store.py`, `pages/6_Refund_approvals.py`, `pages/2_My_orders.py`, `pages/3_Help_chat.py` |
| 7 | Manage: tabs Products (`edit_catalogue`), Orders (`edit_orders`), Users (`edit_users`), Refunds (view, `view_dashboard`), Admin log (last 50); search + 50 rows per page; forms send only the changed fields; a refused write shows its reason | `pages/5_Manage.py` |
| 8 | "📦 About order N" already stays for the whole chat until "New chat": **no change needed** (only the docstring says so) | — |
| 9 | 69 new offline tests; conftest pins `CALLVERSE_LAYER3_MODE=stub` for every test | `tests/test_admin_writes.py` (37), `tests/test_layer3_queue.py` (15), `tests/test_shopnova_admin_app.py` (17), `tests/conftest.py` |
| 10 | Live proof once; then `shopnova.db` reseeded and `callverse.db` deleted | — |
| — | Docs: schema additions + `layer3_pending` | `docs/platform_contract.md`, `README.md`, `config.yaml` comments |

**New files in simple words.**
- `apps/shopnova/app.py` — the app's start file: lists all pages for Streamlit's navigation; the menu itself is drawn by each page.
- `callverse/data/admin_reads.py` — read-only numbers and tables for the admin pages (nothing here writes).
- `callverse/channels/approvals.py` — what happens when the admin clicks Approve / Refuse: re-check, record, write, reply.
- `pages/4_Admin_dashboard.py`, `5_Manage.py`, `6_Refund_approvals.py` — the three admin pages.
- The three test files above.

## 3. Evidence
- **Tests: 472 / 472 pass** (403 before + 69 new), 53 s, 0 API calls (fake LLM, SLM offline). `pytest -q --ignore=tests/data`.
- **Stub mode untouched:** all 403 old tests pass unchanged (incl. `test_coordinator.py::test_4515_goes_to_layer3_and_is_approved`
  and `test_600_is_refused_by_layer3`), plus `test_layer3_queue.py::test_stub_mode_is_unchanged`. Config default is `stub`.
- **New tests cover:** permissions (no login / user / supervisor refused, admin allowed, unknown permission = error);
  every admin write: success, each refusal (14 product cases, 7 user cases, order moves), log row on success, **no row
  on refusal**; price edit keeps 4512's price 59.90 in its items; inactive product hidden + not buyable + reactivated;
  cancel only from processing + stock back (4511: products 2 and 3 +1); `refunded` never by hand; **no admin write in any
  allow-list or in the tool registry**; queue mode → `layer3_pending`, proposal undecided, stub not called, nothing
  written; channel creates the approval + Waiting for finance; duplicate guard: no LLM call (a fake LLM that fails on
  any call), step `approval_pending`, other orders run normally; `decide`: approve (refund 378, order refunded, approval
  approved, admin log, message, Solved, unread 1, formal + upset style kept), refuse (reason required, no refund,
  proposal `layer3`, reason stored but not in the message and **not in the SLM prompt**), re-check failure (parcel
  delivered meanwhile → nothing written, not even steps; R-REF-05 after a partial refund), double decide refused,
  platform refusal → escalate + Open; unread notice cleared without moving `updated_at`; an old `callverse.db` gets
  `user_unread`. AppTest: the 3 admin pages load for admin and show only "please log in" for no login / sara /
  supervisor (9 cases); `app.py` sidebar of sara = Home · Shop · My orders · Help chat, of admin = + the 3 admin pages;
  dashboard period 90 days; Manage adds a product (+ log row) and shows "Not saved: name must not be empty"; Refund
  approvals: Refuse without reason refused, Approve → refund 378 written.
- **Live proof** (`start_shopnova.ps1` settings: Intake + Agent A local, Agent B on Groq, queue on; via `web_chat.send` /
  `approvals.decide`; trace `traces/t18_live_proof.jsonl`):
  - Youssef (user 2): "My order 4515 is very late, I want a refund please." → ticket **T-0004** (3 older tickets were in
    `callverse.db`), outcome `layer3_pending`, status **Waiting for finance**, 29.7 s, reply source `slm`, 38 steps.
    Reply word for word: *"I'm sorry for the trouble. Your refund of 378.00 TND for order 4515 needs approval from our
    finance team. We will reply here as soon as it has been reviewed."*
  - Approval **1** pending (T-0004, order 4515, 378.0, proposal **P-0001**, decision NULL); refunds of 4515: none.
  - `decide(1, "admin", approve)`, 2.5 s → refund **92** (4515, 378.00 TND, `approved`, R-REF-03, P-0001); order 4515
    **refunded**; approval 1 approved by admin at 2026-10-09T09:00:00 with the reason; `admin_actions` row 1
    (`approve_refund`, refunds, 92); P-0001 decision `approve`. New reply word for word: *"I'm sorry for the trouble.
    Your refund of 378.00 TND is approved after a check by our finance team. Your order 4515 is now refunded."*
    Ticket **Solved**, `user_unread` 1.
  - Tokens: **Groq gpt-oss-120b 8,656** (+ 96 quota-check system tokens; a row of 94 was already in the old
    `callverse.db`), Ollama qwen2.5:1.5b 1,341 (696 + 645),
    **0 Gemini**. Expected ~7,500 Groq: 15 % more.
  - Then `python -m callverse.data.seed` and `callverse/data/callverse.db` deleted (demo starts clean).
- **Screens (description; the Chrome extension was not connected, so no real screenshot — checked with AppTest):**
  - *Admin dashboard*: period radio (Last 7 / 30 / 90 days), date range caption, 5 metrics (Sales, Orders, Late
    deliveries, Stuck at depot, Refunds paid), bar chart sales per day (coral), orders by status (navy), review scores +
    average, top 10 products, top categories, low stock (≤ 5), late deliveries list.
  - *Manage*: tabs Products · Orders · Users · Refunds · Admin log; each with search, page number, 50-row table; add /
    edit forms; deactivate / put back; status change with only the allowed next statuses.
  - *Refund approvals*: "Waiting (n)" cards (amount, order, client, ticket, proposal, rule + title, 4 metrics, the
    agent's facts, reason box, Approve / Refuse), then "Decided (n)" table.
  - *A user's sidebar*: logo, Home · Shop · My orders · Help chat, login box — no admin pages.
- `git status`: only `.vscode/` untracked; `git ls-files config/accounts.yaml callverse/data/callverse.db .env
  callverse/data/shopnova.db` → nothing tracked.

## 4. Problems / fragile
- **The SLM has no guide for `layer3_pending`** (SLM prompts may not change in T18): it uses its "info" guide; the
  must_say + next_step carry the content. Live it passed on the first try. If it ever fails twice, the template starts
  with "Here is the latest information about your order 4515." before the two exact sentences (correct but plain).
- **The approval's log line is a separate write** from the refund: `create_refund` (the Coordinator's write function,
  with its safety net) writes the refund, then `log_admin_action` the row. The product / order / user writes are one
  transaction with their log line; the refund approval is two. If the process died between the two, the refund would
  exist without its admin_actions row (the proposal's `decision_reason` still names the admin).
- **Double decide:** guarded by a lock (one Streamlit process), the proposal's "decided once", `create_refund`'s
  "proposal already used" and `close_approval`'s `WHERE status = 'pending'`. Two app processes at once would rely on
  the last two only (still no double refund).
- The duplicate guard runs after the quota check and Intake: if Groq is busy, the user gets the busy reply instead.
- A new message about **another** order on a "Waiting for finance" ticket changes that ticket's status to the new
  outcome (e.g. Solved) while the approval stays pending; the admin's decision later still posts its reply and Solves it.
- The re-check uses `proof_received = False` (case state is not stored); today an R-DMG-01 refund never reaches Layer 3
  (it always asks for a photo first), so this has no effect yet.
- The admin's reason is stored in the approval row, the proposal's `decision_reason` and the ticket's steps (the
  `record_decision` write step): visible to the Console supervisor (T19), never to the client.
- The admin write functions require an admin username but do not look up the accounts file themselves; the permission
  check is done by the page (`require_permission`) just before each call, as the task says.
- Running the old way (`streamlit run Home.py`) would show the admin pages in Streamlit's automatic page list for
  everyone (each page still says "please log in"). `start_shopnova.ps1` now runs `app.py`.
- Not checked in a real browser (only AppTest): please click through once (login as admin, approve a refund).
- My own slip: the first PowerShell edit of `tasks/NEXT.md` (commit 8bd4d0f) garbled its non-ASCII characters
  (— · ⭐); repaired in the report commit (the diff against 97bc1ff now shows only the status / task lines).

## 5. Questions for the Brain
1. `layer3_pending` reply: add an SLM outcome guide (and a template opening) for it in a later task? (Needs an SLM
   prompt change, not allowed here.)
2. Admin cancel of a **card-paid** order in "processing": today the order is cancelled and the stock goes back, but
   nothing is refunded (`paid` stays). Should cancelling also create a refund (through which path)?
3. Should the refund + its admin_actions row become one transaction (e.g. an optional log argument in `create_refund`)?
4. Duplicate guard: also answer it before the quota check (it needs no agent), or keep the order as in the task?

## 6. Next step
Yassine: start `.\start_shopnova.ps1`, log in as `youssef`, send the 4515 refund message, then as `admin` approve it in
Refund approvals and check the "💬 New reply" notice as `youssef`. Then the Brain reviews; after the OK, merge into
`main`; then T19 (Console).

Tell Dali (for Yassine): schema changes `products.active`, new table `admin_actions` (shopnova.db),
`tickets.user_unread` (callverse.db); new Coordinator outcome `layer3_pending` (layer3 mode `queue`). Reseed needed.
