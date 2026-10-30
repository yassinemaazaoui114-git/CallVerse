# T22 — Atlas Travel app (routing by company, part B)

## Why
Since T21, Atlas messages go through the same center, but only through `web_chat.send` in code. T22 gives Atlas its
own company website, like the ShopNova app: users see their bookings and chat with CallVerse; the Atlas admin approves
the refunds and compensation that wait for finance, with every decision logged. It also shows the **code's**
confirmation decision (T21) in the proposal row and the Console. All details approved by Yassine on 2026-10-30
(14 items, all the Brain's ⭐).

## Hard limits
- **No change** to the pipeline's behaviour, agents, prompts, tools, rules, Intake, Coordinator decisions, reply writer
  or ShopNova's app. All 937 existing tests pass (only tests that must follow item 11's display change may be updated,
  listed in the report).
- The Atlas app reaches CallVerse **only** through `web_chat.send(company="atlas")` and `approvals.decide`; every write
  goes through `callverse/data/atlas/writes.py`; nothing is deleted.
- Role **and company** checked at the top of every protected page **and** before every write.
- Never read or stage `.env`; never create or see passwords (Yassine runs the account script); tests 0 API calls;
  never run `tests/data/*`; **127.0.0.1 only**.
- Before the live proof: Yassine restarted the PC; stop if free RAM < 300 MB.

## What to do
0. **Git.** `git fetch`, `git checkout main`, `git pull` (must be **19562f8** or later). Branch `feature/t22-atlas-app`.
   Commit this task file + `tasks/NEXT.md` (IN PROGRESS) first.

1. **Accounts (items 4, 5)** — `callverse/auth/accounts.py`:
   - every account gets a **company** (`shopnova` / `atlas`; the supervisor has none: it serves the whole center).
     New accounts: `hedi`, `sonia`, `tarek`, `lobna`, `nizar` (role user, company atlas, user ids 1–5 of `atlas.db`)
     and `atlas_admin` (role admin, company atlas, the same 5 permissions as ShopNova's admin, for Atlas only).
     Existing accounts get `company: shopnova` (supervisor: none); `config/accounts.example.yaml` updated.
   - `check_role` / `require_role` / `check_permission` / `require_permission` take the **company** of the app: an
     account of the other company is refused (ShopNova's admin can never approve Atlas cases, and back). A missing
     company in an old accounts file = shopnova.
   - `scripts/create_demo_accounts.py`: when `config/accounts.yaml` exists, **add only the missing accounts** (ask
     passwords for those only) and keep every existing hash; add the company field to the old entries. Yassine runs
     it once; Claude Code never runs it with real passwords.

2. **App** `apps/atlas/` (same structure as `apps/shopnova/`: `app.py` with `st.navigation`, `atlas_ui.py`,
   `pages/`, `.streamlit/config.toml`), port **8503**, 127.0.0.1 only, own cookie name (`..._atlas`). **Look (item 3):**
   travel feel — sky blue + white + an orange accent, "Atlas Travel ✈" logo, rounded cards, a floating "Need help?
   Chat with us" button. Start files `start_atlas.ps1` and `Atlas.bat` (same Ollama check and browser opening as
   ShopNova; sets `CALLVERSE_AGENTS_SET=local` and `CALLVERSE_LAYER3_MODE=queue`); add an **"Atlas Travel"**
   shortcut to `scripts/make_desktop_shortcut.ps1` (do not run it).

3. **User pages (items 6–8):** sidebar shows Home, My bookings, Help chat to Atlas users only.
   - **Home:** short welcome (hotel stays in Portugal, flights in the US, for Tunisian travellers) + links.
   - **My bookings:** the logged-in user's own bookings only. Flights: route (cities + airports), airline, flight
     number, scheduled departure, status, delay minutes and cause (plain words), or "cancelled (cause)". Hotels:
     hotel, arrival date, nights, room booked / room given, deposit type in plain words, total and paid. Under each:
     its refunds and compensation (amount, status, date). Button **"Ask about this booking"** → Help chat with
     "📦 About booking N" (the channel adds " (booking N)" if the message names none, like ShopNova's F1).
   - **Help chat:** same as ShopNova's page (one ticket per chat, ticket number + status, live steps, New chat,
     "💬 New reply on T-00NN" notice from `user_unread`), with `company="atlas"`.
   - Read functions for these pages in `callverse/data/atlas/reads.py` (or a new `atlas_app_reads.py`), read-only.

4. **Admin pages (items 9, 10):** sidebar shows Admin dashboard, Approvals, Records only to `atlas_admin`.
   - **Admin dashboard** (Altair; period 7 / 30 / all, default all, from the simulation clock): bookings by status
     (hotel and flight), hotel cancellation rate, flight delay and cancellation rates, refunds paid and compensation
     paid (TND), upcoming arrivals and departures (next 14 days).
   - **Approvals:** waiting cases first — ticket, booking (type + id), user name, action (refund / compensation),
     amount, rule id + title, the facts the agent used, the code's confirmation decision (item 11) — then decided
     ones. **Approve** (reason optional) / **Refuse** (reason required) through `approvals.decide`.
   - **Records:** read-only tables with search + 50 rows per page: hotel bookings, flight bookings, users, refunds,
     compensation, and the admin log (last 50). **No editing** in T22.
   - **Atlas admin log:** new table `admin_actions` in `atlas.db` (id, at, admin, action, target table, target id,
     before, after — same as ShopNova's), written **in the same transaction** as each Atlas approve / refuse (the
     decision, the refund or compensation row, any booking status change and the log line: all or nothing). Test
     with a forced log failure (nothing written, approval stays pending).

5. **Code's confirmation decision (item 11):** the Atlas proposal row stores the code's decision
   (`confirmed_by_code` 0/1 + a short `confirmation_reason`, e.g. "refund request + quote found", "negative
   sentence", "quote not in the message"), next to the agent's own flag (kept for the record). The Console's Ticket
   detail timeline shows "Confirmed by code: yes / no (reason)" for Atlas proposals instead of the agent's flag;
   ShopNova's line is unchanged. The same columns are added on connect if missing (old `atlas.db` keeps working).

6. **Tests (item 12), offline, all pass, 0 API:** accounts with company (old file without company = shopnova; the
   script keeps existing hashes and adds only the missing accounts — test on a temp file with fake hashes); every
   Atlas page loads for the right role; only "please log in" for no login, a ShopNova user, ShopNova's admin, the
   supervisor (on admin pages), and an Atlas user on admin pages; My bookings shows only the user's own bookings;
   "About booking N" added only when no booking number is typed; Approvals approve / refuse with a fake LLM (rows +
   admin log + new message + Solved + unread); forced log failure writes nothing; the confirmation columns + the
   Console line; the Atlas admin pages never show ShopNova cases and ShopNova's Refund approvals never show Atlas
   cases.

7. **Live proof (item 13), once**, after Yassine restarted the PC, with the Atlas app's settings, through
   `web_chat.send(company="atlas")` + `approvals.decide` (Claude Code cannot log in: no passwords):
   (a) Nizar (user 5): "Flight 7004 got me to Chicago more than three hours late. I want the compensation I am owed."
   → pending 839.50 → `approvals.decide` approve as `atlas_admin` → compensation row, admin log row, new message,
   ticket Solved + unread. (b) Hedi (user 1): "Please cancel my hotel booking 7011, I can't travel anymore." →
   booking cancelled + refund 220.00 (automatic). Pages rendered with AppTest on that data (no browser screenshots).
   Report Groq tokens (about 16,000 expected), 0 Gemini. Then reseed both databases and delete `callverse.db`.

8. **README (item 14, rule 8):** the Atlas app (accounts to create, how to start it, the shortcut), folders, task
   history.

## Checks (with numbers)
- Tests x/y (all pass); new tests listed; existing tests changed (with why).
- Live proof: ticket ids + statuses, both replies word for word, compensation row, refund row, admin log row,
  booking 7011 status, Groq tokens, 0 Gemini.
- `git status`: `config/accounts.yaml`, `*.db`, `.env` not tracked.
- One sentence each: is the Atlas app usable for a demo? what is fragile?

## Time box and stop rule
**2.5 h.** Stop and report if: main is not at 19562f8 or later, a test fails, any change to the pipeline's behaviour,
prompts, rules or ShopNova's app would be needed, the account script would need to see or replace existing passwords,
a secret would end up in git, free RAM < 300 MB, or Groq's daily limit answers. If Yassine has to leave: stop at a
safe point, write `tasks/T22_progress.md`, commit "T22 WIP: …" and push the branch (like T21).

## Git (approved by Yassine, 2026-10-30)
Commit and push `feature/t22-atlas-app`. **No merge into `main`.** Write `tasks/T22_report.md` (In plain words ·
Done · Evidence · Problems · Questions for the Brain · Next step) and set `tasks/NEXT.md` to WAITING FOR REVIEW.
Last line for Yassine: run `python -m scripts.create_demo_accounts` once to add the 6 Atlas accounts; tell Dali:
accounts have a company, Atlas `admin_actions`, proposal columns `confirmed_by_code` / `confirmation_reason`.
