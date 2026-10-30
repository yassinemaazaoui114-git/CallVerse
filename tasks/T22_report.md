# T22 report — Atlas Travel app (routing by company, part B)

## 1. In plain words
Atlas Travel now has its own website, like ShopNova: a client sees their flights and hotel stays and chats with CallVerse;
the Atlas admin approves the refunds and compensation that wait for finance, and every decision is logged with the money,
all or nothing. Every account now belongs to a company, so ShopNova's admin can never approve an Atlas case, and Sara
(user 1) can never see the bookings of Hedi (also user 1). The code's own "did the client really ask?" decision is now
stored with its reason, and shown in Approvals and in the Console. In the live test both Atlas cases came out exactly as
expected. Yassine still has to run the account script once; **nobody has logged in through a real browser yet**.

## 2. Done
- **Accounts (items 4, 5):** `callverse/auth/accounts.py`: 6 new accounts, a company per account, `check_role` /
  `require_role` / `check_permission` / `require_permission` take the app's company (no company given = ShopNova, so
  ShopNova's pages did not change). `scripts/create_demo_accounts.py` adds only the missing accounts, keeps every hash and
  the cookie key, and adds the company to old entries. `config/accounts.example.yaml` updated.
- **App (`apps/atlas/`, port 8503, 127.0.0.1 only, cookie `..._atlas`):** `app.py`, `Home.py`, `atlas_ui.py`, pages
  My bookings, Help chat, Admin dashboard, Approvals, Records, `.streamlit/config.toml`. Sky blue + white + orange,
  "Atlas Travel ✈" logo, rounded cards, floating help button. `start_atlas.ps1`, `Atlas.bat`, "Atlas Travel" shortcut added
  to `scripts/make_desktop_shortcut.ps1` (not run).
- **Reads:** new `callverse/data/atlas/atlas_app_reads.py` (read only).
- **"About booking N":** `web_chat.with_order` takes the company and adds " (booking N)" at Atlas.
- **Atlas admin log:** table `admin_actions` in `atlas.db`, written inside `writes.admin_decide`'s one transaction
  (actions `approve_refund`, `approve_compensation`, `approve_cancel_hotel`, `refuse_...`).
- **Code's confirmation (item 11):** proposal columns `confirmed_by_code`, `confirmation_reason`, next to the agent's flag.
  `atlas_coordinator.confirmation()` gives the yes / no + the reason (`client_confirmed` is now only its yes / no);
  `writes.set_proposal_confirmation` stores it. The decision itself is unchanged. Console Ticket detail shows
  "Confirmed by code: yes / no (reason)" for Atlas (or "not checked" if the proposal was sent back earlier); ShopNova's
  line is unchanged. `atlas/db.py` adds the columns and the table to an old `atlas.db` on connect.
- **README** updated (the app, accounts, shortcut, folders, history).

## 3. Evidence
**Tests: 1043/1043 passed** (`python -m pytest -q --ignore=tests/data`, 2 min 9 s, 0 API calls): the 937 existing + **106 new**
in `tests/test_atlas_app.py` (accounts and company, the script on a temp file with fake hashes, every page per role, "please
log in" for all the others, own bookings only, About booking N, Approvals approve / refuse, forced log failure, confirmation
columns, old `atlas.db`, Console line, the wall between the companies, dashboard, Records).

**Existing tests changed: 1 file, `tests/test_atlas_data.py`, 2 tests:**
1. `test_proposals_have_the_same_columns_as_shopnova` → renamed `..._shopnova_columns_plus_the_code_confirmation`: follows item 11.
2. `test_every_table_has_the_labels`: `admin_actions` left out, because it has ShopNova's columns (no labels), as the task
   orders. **This one is outside the task's "only item 11" limit:** item 10 cannot be built without it. See question 1.

**Untouched:** `git diff main` is empty for `apps/shopnova`, `apps/console`, `callverse/agents`, `callverse/pipeline.py`,
`callverse/coordinator/coordinator.py`, `callverse/slm`, `callverse/intake`, `callverse/kb`, `callverse/data/seed.py`,
`callverse/data/writes.py`, `config.yaml`.

**Live proof, run once** (Atlas app's settings; free RAM 2,492 MB; PC restarted 21:31):

| | (a) Nizar, flight 7004 | (b) Hedi, hotel 7011 |
|---|---|---|
| Ticket | T-0001 | T-0002 |
| Status | Waiting for finance → **Solved, unread 1** | **Solved** |
| Proposal | AP-0001, AT-FLT-03, agent flag 1, code 1 "compensation request + quote found" | AP-0002, AT-HOT-02, agent flag 1, code 1 "cancellation + quote found" |
| Money | compensation row 1: 839.50 TND, approved | refund row 1: 220.00 TND, approved, automatic |
| Seconds | 22.18 | 30.31 |

Replies, word for word:
- (a) first: "I'm sorry for the trouble. Your compensation of 839.50 TND for booking 7004 needs approval from our finance team. We will reply here as soon as it has been reviewed."
- (a) after `approvals.decide` approve as `atlas_admin`: "I'm sorry for the trouble. Your compensation of 839.50 TND for booking 7004 is approved after a check by our finance team."
- (b): "I'm sorry for the trouble. Your hotel booking 7011 is cancelled. Your refund of 220.00 TND for booking 7011 is approved."

Admin log row: id 1, at 2026-10-09T09:00:00, admin `atlas_admin`, action `approve_compensation`, target `compensations` 1,
before NULL, after = the row + AP-0001 + approval 1. Booking 7011: **cancelled**, cancelled_date 2026-10-09.
The live `atlas.db` was made before T22: it got the new table and columns on connect.

Tokens: **Groq 13,341** = gpt-oss-120b 11,574 + gpt-oss-20b 1,676 + quota ping 91 (about 16,000 expected). **Gemini 0**.
Local SLM 1,825 (not Groq).

Pages rendered with AppTest on this data (fake-hash temp accounts file): 8 runs, 0 exceptions. My bookings shows Nizar's
compensation + "New reply on T-0001", and Hedi's refund; Approvals "Waiting (0)", "Decided (1)"; Records 6 tables;
dashboard hotel cancellation 37.5 %, flight delay 19.1 %, flight cancellation 1.9 %, refunds 1 · 220.00, compensation
1 · 839.50, upcoming 108 arrivals + 1 departure. ShopNova's `admin` and `sara` got only "please log in".

Clean-up: both databases reseeded, `callverse.db` deleted. `git status`: `config/accounts.yaml`, `*.db`, `.env` not tracked
(0 tracked). No password created or seen; `config/accounts.yaml` and `.env` not opened.

**Usable for a demo?** Yes for the flows proven above, once the account script has been run and after one login check in a
real browser.
**Fragile?** Groq's per-minute limit: two tickets within a minute already hit it (below).

## 4. Problems
- **Not tested:** real login in a browser (Claude Code has no passwords), `start_atlas.ps1`, `Atlas.bat` and the shortcut were
  not run, and no one has looked at the pages. AppTest checks content and rights, not the look.
- **Groq per-minute limit (8,000 tokens):** in T-0002, Agent B's last call got a 429 on gpt-oss-120b, and the existing
  fallback finished on gpt-oss-20b. The result was correct, and it was not the daily limit, so the stop rule did not apply.
  In a demo, two tickets close together can mean waits or the backup model.
- **My error, fixed:** the first status edit of `tasks/NEXT.md` went through PowerShell and damaged its accents and dashes;
  corrected in the next commit (eb4022e). The first commit of the branch (55e4fe1) still holds the damaged version.
- **Choices to review:**
  - the menu follows the task word for word: Home, My bookings, Help chat for Atlas users only, so `atlas_admin`, a
    visitor and a ShopNova account have no Home link (the app still opens on Home);
  - `approvals.decide` got an optional `company` argument, not named in the task: the Atlas page passes it, so an approval of
    another company is "not found". ShopNova's page does not pass it and works as before;
  - the Atlas accounts are in `DEMO_ACCOUNTS`, and `check_role` still returns the same 4 keys (company through
    `accounts.company_of`), because two existing tests pin those shapes;
  - the script no longer offers "Replace the file": to reset a password, delete the account from the file and run it again;
  - dashboard: "next 14 days" counts today too (2026-10-09 to 2026-10-23);
  - README: the Python "to try it" snippet for Atlas was replaced by the app, and the stale test count updated.
- **Small, left alone (would need other changes):** a ShopNova account logged in at Atlas (and back) sees "Hello, name" in the
  sidebar and "please log in" on the pages; Atlas's Home then still says "Log in". The Console's approval lines say "on order
  7004" for an Atlas booking. `use_container_width` gives a deprecation warning, as in the other apps. `.vscode/` is untracked
  and not committed.

## 5. Questions for the Brain
1. Is the second test change (`admin_actions` without labels) accepted, although it is outside the "only item 11" limit?
2. Should `atlas_admin` get a Home link? It is a one-word change in `MENU`.
3. Should the Console's "on order N" lines say "booking" for Atlas? Not done: not in T22.

## 6. Next step
1. Yassine: run `python -m scripts.create_demo_accounts` once, then log in once as `nizar` and as `atlas_admin` in the browser.
2. Brain: review; merge only after the owners' OK.
3. Tell Dali: accounts have a company, Atlas has `admin_actions`, proposal columns `confirmed_by_code` / `confirmation_reason`.

**Last line for Yassine:** run `python -m scripts.create_demo_accounts` once to add the 6 Atlas accounts; tell Dali: accounts
have a company, Atlas `admin_actions`, proposal columns `confirmed_by_code` / `confirmation_reason`.
