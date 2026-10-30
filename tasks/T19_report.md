# T19 report — CallVerse Console (Live tickets, Ticket detail, Agents, Dashboard)

Branch `feature/t19-callverse-console` · 2026-10-30 · Builder: Claude Code

## 1. In plain words
CallVerse now has its own screen, the **CallVerse Console** (port 8502, supervisor login only). It shows every ticket
of every company as it comes in, and for each ticket **how the agents worked on it**, step by step: what Intake
understood, which agent took it, which tools and rules it used, what it proposed, each check the Coordinator made,
finance's decision, how the reply was written, plus tokens and seconds. An Agents page and a KPI Dashboard summarise
everything. The Console can only **read**: it opens both databases in read-only mode, so it cannot change anything.
Tickets now also keep the computer's real time (the simulation clock does not move) and how long each reply took,
and a ticket passed to a human is now "Escalated".

## 2. Done
- **Step 0 (git) — changed, see Problems 1:** the merge of `origin/chore/readme-shortcut` into `main` was **blocked
  by Claude Code's permission check** ("merge without review"). I did not touch `main`. Instead
  `feature/t19-callverse-console` was branched from `chore/readme-shortcut` (= main 0927cbb + the reviewed README
  commit 36666f9), so the content is exactly what step 0 asked for. Baseline tests on it: **477/477**.
- **App `apps/console/`** (same structure as ShopNova): `app.py` (st.navigation), `console_ui.py` (setup, style,
  sidebar login, menu), `pages/1_Live_tickets.py`, `2_Ticket_detail.py`, `3_Agents.py`, `4_Dashboard.py`,
  `.streamlit/config.toml` (dark navy/charcoal, teal, 127.0.0.1:8502, no file watcher). Start files
  `start_console.ps1` + `Console.bat` (no Ollama check: the Console loads no model; opens the browser when up);
  `scripts/make_desktop_shortcut.ps1` now makes **ShopNova** and **CallVerse Console** (not run).
  Login: supervisor only, own cookie name (`..._console`), because the browser shares cookies between the two ports.
- **Times (items 4–5)** in `callverse/tickets/store.py`, added on connect if missing (like `user_unread`):
  `tickets.created_real`, `tickets.updated_real`, `messages.at_real`, `messages.seconds`; also **`steps.at_real` and
  `system_tokens.at_real`** (needed for "Groq tokens used today", see Question 2). The channel saves each reply's
  seconds; `approvals.decide` measures its own (re-check + write + reply writer).
- **Status "Escalated" (item 11):** added to `STATUSES`; the channel's escalate outcome (Coordinator or error) →
  Escalated; a new message on it continues the same ticket. An old `callverse.db` gets its tickets table rebuilt once
  (SQLite cannot change a CHECK): new table, copy all rows, drop, rename — rows kept (tested). ShopNova's Help chat
  shows the status text as it is, so it shows "Escalated" with no page change.
- **`callverse/console/reads.py`** (item 4): all the Console's SQL, read-only connections (`file:...?mode=ro` URI),
  a missing file is never created. Companies = `config.yaml console.companies: [shopnova]` + those in `callverse.db`.
  Also `console.late_reply_s: 30` and `console.groq_daily_tokens: 200000` in config.
- **Pages (items 6–10):** Live tickets (filters company/status/priority/agent, newest first, `st.fragment(run_every=10)`,
  click a row → Ticket detail); Ticket detail (conversation with real times and reply seconds; per user message the
  timeline, tokens by model, seconds, closed "details" expander with the raw steps; identity / quota / approval steps
  included); Agents (5 cards, period All / 7 / 30, default All); Dashboard (Altair; every KPI of item 9). Each page:
  "No tickets yet — chat in the ShopNova app to see them here." when empty. No fake data.
- **`/demo` (item 12):** code kept; README and `docs/DEMO_RUNBOOK.md` say it is replaced by the Console and its files
  go after Dali's OK.
- **Tests (item 14):** `tests/test_console.py` (33 tests) + 1 updated test (escalate → "Escalated").
- **README (item 16):** Console section, start files, folders, test count, T19 history line.

## 3. Evidence
- **Tests: 510/510 pass** (`python -m pytest -q --ignore=tests/data`; 477 before + 33 new; ~2 min). `tests/data` not run.
  New tests: pages load for the supervisor (4); only "please log in" for admin / sara / no login (12); "No tickets
  yet" when empty + the file is not created (4); Live tickets order + status filter; Ticket detail timeline of the
  finance ticket; KPI math on 4 known tickets (solved 25 % / escalated 25 % / finance 25 % / late 1 of 3 timed /
  refunds 437.90 TND of which 378 finance / tokens avg 1,175 max 3,100 / system 120 / Groq today 4,050 with
  yesterday's rows excluded); period filter on computer time; Agents cards; every step has a description; router
  and ask_agent steps belong to no agent; **INSERT / UPDATE refused on both read-only connections**; old-style DB
  gets the columns + accepts Escalated; new rows get computer time; escalate path → Escalated and the next message
  continues it; admin decision saves its seconds. 0 API calls (`llm.chat` is made to fail in these tests).
- **Live proof (once, 2026-10-30 08:19, PC restarted 07:15, free RAM 2.4 GB):** both apps started with their start
  files (8501 and 8502 answered `/_stcore/health`); I started Ollama (`ollama serve`) first, it was not running.
  Messages through `web_chat.send` with the app's settings (Intake + A + SLM local, B on Groq, queue mode):

  | Ticket | User / message | Outcome | Final status | Reply seconds |
  |---|---|---|---|---|
  | T-0001 | Sara: "My order 4512 is late, I want a refund please." | approve, 59.90 TND (R-REF-03) | Solved | 29.85 |
  | T-0002 | Youssef: "My order 4515 is very late, I want a refund please." | layer3_pending → admin approved 378.00 TND | Solved (after Waiting for finance) | 28.26 + 2.67 (admin decision) |
  | T-0003 | Amira: "Where is my order 4511?" | info ("being prepared") | Solved | 15.80 |

  **Groq tokens: 14,139** (14,044 in tickets + 95 system tokens of the quota ping); **Gemini: 0**. (Expected ~16,000.)
  One Groq per-minute limit (429) on gpt-oss-120b in T-0002: the backup gpt-oss-20b took over (902 tokens); the
  Console counts it as 1 error for Agent B and shows it in the timeline.
- **Dashboard numbers checked by hand** (raw SQL on the two DBs, read-only):
  - tickets 3; approvals = 1 (T-0002, approved, P-0002); no escalate decision → solved by the AI alone = T-0001 +
    T-0003 = 2/3 = **66.7 %**, escalated **0 %**, finance 1/3 = **33.3 %** ✓
  - reply seconds 29.85, 28.26, 15.80, 2.67 → average 76.58 / 4 = **19.14 s**; none > 30 s → late **0** ✓
    (29.85 s is just under the limit)
  - refunds with a ticket proposal: 4512 59.90 (P-0001) + 4515 378.00 (P-0002) = **437.90 TND**, finance **378.00** ✓
  - tokens (sum of `llm_call` steps): T-0001 7,606, T-0002 8,377, T-0003 3,033 → avg 19,016 / 3 = **6,339**, max
    **8,377** ✓; system tokens **95** ✓; Groq today 14,044 + 95 = **14,139** ✓; reviews 1,989, average **4.0** ✓
  - Agents: Intake 3 tickets (avg 6.83 s, local models only); Agent A 3 tickets / 2,470 tokens (cv-qwen3.5-4b: T-0003,
    plus its answers to B's "ask Agent A" on T-0001/T-0002); Agent B 2 tickets, 2 proposals, 1 approved, 1 to finance,
    1 error (the 429), 14,044 tokens; Coordinator 2 proposals reviewed; Reply writer 2,502 tokens, avg 3.01 s.
- **The 4 pages as supervisor, on the live data** (rendered with Streamlit's AppTest and a temporary test-only
  supervisor account — I cannot log into the browser: I never see passwords). No error on any page.
  Live tickets: T-0003 Amira / T-0002 Youssef / T-0001 Sara, reasons, priority, Solved, lead agent A/B/B, ages 3–4 min.
  Ticket detail T-0002: "Finance approval 1: approved · 378.00 TND on order 4515 · decided by admin", the 3 messages
  with real times, "Tokens: 8,377 (groq/openai/gpt-oss-120b 6,134 · groq/openai/gpt-oss-20b 902 · ollama/qwen2.5:1.5b
  1,341) · reply seconds: 28.3 s, 2.7 s", then the full timeline. Agents: 5 cards. Dashboard: the numbers above.
  **Browser screenshots: not taken** (they need the supervisor login). A copy of the live-proof databases is kept
  outside the repo (`...\scratchpad\t19_live_dbs\`) if Yassine wants them.
- **Cleanup:** `shopnova.db` reseeded (0 refunds on 4512/4515, 0 proposals), `callverse.db` deleted, both apps stopped.
- **`git status`:** `config/accounts.yaml`, `callverse/data/callverse.db`, `.env` not tracked (checked with
  `git ls-files`). `.vscode/` untracked, not mine, not committed.

## 4. Problems
1. **Step 0 merge not done by me.** Claude Code's permission check refused `git merge --no-ff origin/chore/readme-shortcut`
   on `main` ("merge without review"). The T19 branch starts from `chore/readme-shortcut` instead, so merging
   `feature/t19-callverse-console` into `main` later also brings the README commit. Yassine: either merge
   `chore/readme-shortcut` into `main` yourself first (as planned), or merge only the T19 branch (it contains it).
2. **Who did a step** is worked out from the order of the steps (Intake's LLM fallback = "agents" calls before the
   intake step; "agent_b" calls = B, also B's question to A; "slm" = writer). It is right for today's pipeline, but
   a new kind of model call would need one line in `reads._actor`.
3. **Live tickets click → Ticket detail** uses a dataframe row selection + `st.switch_page` inside the 10 s fragment.
   AppTest cannot click a dataframe row, so this one path is **not covered by a test**: please click a row once.
4. The Live tickets refresh reruns the table only; the filter lists are read when the page loads (a new status
   appears in the filter after a page reload).
5. Not fragile but worth knowing: in T-0001 the Coordinator logged "Rule R-REF-03 was cited but not searched"
   (Agent B did not call `search_policy` that time; the rule still passed every check). The Console shows this
   warning, which is good for the demo's "why".
6. ShopNova pages still use `use_container_width` (Streamlit 1.66 warns it is deprecated); the Console uses
   `width="stretch"`. Not changed in ShopNova (not this task).

## 5. Questions for the Brain
1. Step 0: OK that the README branch reaches `main` through the T19 branch (or Yassine merges it first)?
2. I added `at_real` also to `steps` and `system_tokens` (the task listed `tickets` and `messages` only): without it
   "Groq tokens used today (real date)" cannot be computed. OK to keep?
3. "Solved by the AI alone" counts Solved **or Closed** tickets that were never escalated and had no finance approval;
   "escalated" = status Escalated **or** any escalate decision in the ticket's steps (a later message may have solved
   it). OK?
4. Agent A's card counts the tickets where A answered B's "ask Agent A" question (its tool calls), while the tokens
   of that sub-call count for B (they run on B's Groq models). OK, or should A count only its own routed tickets?

## 6. Next step
Yassine: start `Console.bat`, log in as `supervisor`, click a Live tickets row once (Problem 3) and take the 4
screenshots if wanted; merge as decided in Question 1. Then retire Dali's `/demo` files after his OK.

**For Dali:** new columns `created_real`, `updated_real` (tickets), `at_real` (messages, steps, system_tokens),
`seconds` (messages); new ticket status "Escalated"; `/demo` replaced by the CallVerse Console.
