# T19 — CallVerse Console (the main platform): Live tickets, Ticket detail, Agents, Dashboard (KPIs)

## Why
CallVerse is the main platform; ShopNova is one company it serves. The Console is the center's own screen: every
ticket of every company, **how the agents worked on each one**, and the KPI dashboard of the brief. Design:
`docs/ui_design.md` §1, §3, §6 (pages approved 2026-10-29). All T19 details approved by Yassine on 2026-10-29
(16 items, all the Brain's ⭐).

## Hard limits
- **No change** to prompts, agents' logic, tools, allow-lists, rules, Intake, RAG, SLM, Coordinator.
- **The Console is read-only:** it opens `callverse.db` and `shopnova.db` in SQLite **read-only mode**
  (`file:...?mode=ro` URI). It never writes company data or tickets. Only the channel / store (not the Console) gets
  the two new columns of step 2.
- Supervisor login only (`require_role("supervisor")` on every page). No secrets in git; never read or stage
  `.env`; never create or see passwords. Tests: 0 API calls (fake LLM). Never run `tests/data/*`. **127.0.0.1 only.**
- Before the live proof: Yassine restarted the PC / closed apps; stop if free RAM < 300 MB.

## What to do
0. **Git.** `git fetch`, `git checkout main`, `git pull` (must be **0927cbb** or later). Then merge the reviewed
   README + shortcut branch: `git merge --no-ff origin/chore/readme-shortcut` (approved by Yassine after the Brain's
   review; on a conflict: `git merge --abort`, stop and report). Run all tests (all pass). **Do not push main**
   (Yassine pushes). Then branch `feature/t19-callverse-console` from this main. Commit this task file +
   `tasks/NEXT.md` (IN PROGRESS) first.

1. **App** `apps/console/` (same structure as `apps/shopnova/`: entry file + pages via `st.navigation`, shared
   `console_ui.py`, `.streamlit/config.toml`): port **8502**, 127.0.0.1 only, **dark control-room style with teal**
   (the approved mock: dark navy/charcoal background, teal accents, compact tables). Start files like ShopNova:
   `start_console.ps1`, `Console.bat` (same Ollama-free start: the Console loads **no** models; opens
   http://127.0.0.1:8502 when up) and a "CallVerse Console" Desktop shortcut added to
   `scripts/make_desktop_shortcut.ps1` (do not run it). Login: supervisor only (sidebar login like ShopNova).

2. **Times that mean something (items 4–5).** The simulation clock does not move, so every ticket has the same time.
   In `callverse/tickets/store.py` (added on connect if missing, like `user_unread`, so an old `callverse.db` works):
   - `tickets.created_real`, `tickets.updated_real`, `messages.at_real` = the **computer's** time (ISO, local).
     The Console uses these for ages, per-day charts and reply speed. Company rules keep the simulation clock.
   - `messages.seconds` on assistant messages = how long the reply took (the channel already measures it; the admin
     decision in `approvals.py` measures its own). NULL for old rows.
   Tests for both; old rows without values are shown as "—", never crash.

3. **New ticket status "Escalated" (item 11):** add to `STATUSES`; the channel's escalate outcome → **Escalated**
   (instead of Open); a new user message on an Escalated ticket continues it (like Open). The ShopNova pages show it.
   Update the existing tests that expected Open for escalate.

4. **Read-only queries** in a new `callverse/console/reads.py` (all SQL here, read-only connections, one function
   per page block). Company list = the distinct companies in `callverse.db` plus `console.companies: [shopnova]` in
   `config.yaml`, so Atlas appears by config later (item 13).

5. **Live tickets page (item 6):** columns id, company, user (name from the company's data), reason, priority,
   status, lead agent, age (from real time); filters company, status, priority, agent; newest first; refreshes by
   itself **every 10 s** (`st.fragment(run_every=10)`); click / select a ticket → Ticket detail.

6. **Ticket detail page (item 7):** the conversation (with real times), then for each user message a step-by-step
   timeline from `steps`: Intake (reason, emotion, sentiment, priority, order id) → route / hand-over → each tool
   call and policy search (rules returned) → proposal → each Coordinator check ✅/❌ + the decision and why →
   Layer 3 (fixed rule / waiting / the admin's decision, from `approvals`) → reply writer (first try / retry /
   template) → what was written (refund row, status). Per message: **tokens** (sum of `llm` steps, by model) and
   **seconds**. The raw step data is in a closed "details" expander. Identity-check and quota steps shown too.

7. **Agents page (item 8):** one card per agent — Intake, Agent A, Agent B, Coordinator, reply writer: tickets
   handled, proposals, approved / sent back / escalated, errors, average seconds, tokens and the model(s) used.
   Period 7 / 30 days / all, default **all**.

8. **Dashboard page (item 9), Altair charts, period 7 / 30 / all (default all):**
   - tickets per day (real time) and per company;
   - % solved by the AI alone (Solved without escalate and without a finance approval), % escalated, % sent to
     finance (Layer 3 approvals);
   - average reply time (`messages.seconds`) and **late replies = over 30 s** (count + %);
   - refunds approved / refused by finance + TND paid (refunds of ticket orders, from `shopnova.db`, read-only);
   - satisfaction = average review score of ShopNova (real Olist scores; agent F later — say so on the page);
   - tokens per ticket (average, max) with **system tokens shown apart** (`system_tokens`);
   - **Groq tokens used today** out of 200,000 (sum of today's Groq `llm` steps + system tokens, real date).

9. **Data shown (item 10):** only real tickets from the apps. Every page has a clear "No tickets yet — chat in the
   ShopNova app to see them here." state (no fake data, no generator).

10. **Dali's `/demo` (item 12):** keep its code and files. README (and `docs/DEMO_RUNBOOK.md` if it exists) say
    "the `/demo` page is replaced by the CallVerse Console; its files will be removed after Dali's OK".

11. **Tests (item 14), offline, all pass:** each Console page loads for the supervisor and shows only "please log in"
    for admin, user and no login; KPI math on a temporary `callverse.db` + `shopnova.db` with known tickets
    (solved / escalated / finance / late / tokens / system tokens / today's Groq); a test that the Console's
    connections cannot write (an INSERT fails); the new columns on an old-style DB; Escalated status path; 0 API.

12. **Live proof (item 15), once**, after Yassine restarted the PC: both apps started with their start files.
    Through `web_chat.send` (or the app): (a) Sara "My order 4512 is late, I want a refund please." (b) Youssef
    "My order 4515 is very late, I want a refund please." then `approvals.decide` approve as admin, (c) Amira "Where is
    my order 4511?". Then screenshots of the 4 Console pages as supervisor (Live tickets, the 4515 Ticket detail,
    Agents, Dashboard). Expected about 16,000 Groq tokens. Then reseed `shopnova.db` and delete `callverse.db`.

13. **README (item 16, CLAUDE.md rule 8):** add the Console (what it shows, how to start it, the shortcut) and the
    task history line for T19.

## Checks (with numbers)
- Step 0: merge commit id, tests x/y.
- Tests x/y (all pass); new tests listed.
- Live proof: the 3 ticket ids + final statuses, Groq tokens, 0 Gemini, the 4 screenshots (or a description).
- The Dashboard's numbers for the 3 tickets, checked by hand against the database (write the check in the report).
- `git status`: `config/accounts.yaml`, `callverse.db`, `.env` not tracked.
- One sentence each: is the Console usable for a demo? what is fragile?

## Time box and stop rule
**2 h.** Stop and report if: main is not at 0927cbb or later, the README merge conflicts, a test fails, any change to
prompts / agents / tools / rules / Intake / SLM / Coordinator would be needed, the Console would need to write, a
secret would end up in git, free RAM < 300 MB, or Groq's daily limit answers.

## Git (approved by Yassine, 2026-10-29)
Commit and push `feature/t19-callverse-console`. **No merge into `main`** (the step-0 merge stays local; Yassine
pushes main). Write `tasks/T19_report.md` (In plain words · Done · Evidence · Problems · Questions for the Brain ·
Next step) and set `tasks/NEXT.md` to WAITING FOR REVIEW. Last line for Yassine (to tell Dali): new columns
`created_real`, `updated_real`, `at_real`, `seconds`, status "Escalated", `/demo` replaced by the Console.
