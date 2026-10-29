# T17 report: ShopNova app, part 1 (tickets, logins, Shop, My orders, Help chat)

Branch `feature/t17-shopnova-app` (commits c403b02, 22fb26b, + this report). Not merged into `main`.
Time: 13:29 → 13:52 (about 25 min of the 2 h box).

## 1. In plain words
ShopNova now has its own small website (Streamlit, on this PC only). Anyone can browse the shop. A logged-in
client can buy, see only their own orders, and chat with CallVerse. Every chat is a **ticket** saved in CallVerse's own
database (`callverse.db`), separate from ShopNova's data, together with every step the AI took. The website never talks
to the agents itself: it calls **one channel function** that first checks Agent B's free quota, then checks that the
order in the message belongs to the logged-in client, and only then runs the unchanged pipeline. A live test with Sara's
message "My order 4512 is late, I want a refund please." gave an approved refund of 59.90 TND, written by the Coordinator.

## 2. Done
| Step | What | Files |
|---|---|---|
| 0 | Branch from `main` (T16 merge 76fa16c included), task file + `docs/ui_design.md` (unchanged) + NEXT.md committed first | — |
| 1 | Pinned libraries, installed in `.venv` | `requirements.txt` |
| 2–3 | Tickets store: `tickets`, `messages`, `steps`, `approvals` (approvals created now, unused until T18); 6 statuses; sim-clock times; the ticket rule (`ticket_for_message`, `current_ticket`) | `callverse/tickets/store.py` |
| 4 | Logins: `load_accounts`, `check_role` (pure, testable), `require_role` (Streamlit, stops the page), `authenticator()`; account script run by Yassine; example file without passwords; `.gitignore` | `callverse/auth/accounts.py`, `scripts/create_demo_accounts.py`, `config/accounts.example.yaml` |
| 5 | Channel `send(user_id, company, text, ticket_id=None, on_step=None)`: quota check → Intake → identity check → `pipeline.handle_ticket` → reply + steps + ticket fields saved; never crashes (escalate reply + `error` step) | `callverse/channels/web_chat.py` |
| 5 | Quota check reused: `check_models(role_key, stop_at_first_ok)`; the script now prints the `agents` AND `agent_b` lists | `scripts/quota_check.py` |
| 6 | Trace listener: `add_listener` / `remove_listener`, called by `trace.log` after the line is written (an error in a listener is ignored). No other change on the pipeline side | `callverse/trace.py` |
| 7 | `create_order` with checks; in no allow-list (test) | `callverse/data/writes.py` |
| 8 | App: Home, Shop (Featured 6 + all products, search, category filter, 24 per page, icon per category, Buy), My orders (own orders, dates, lines incl. Delivery, refunds, "Ask about this order"), Help chat (history, ticket number + status, live steps in `st.status`, "New chat"), sidebar login/logout, floating help button, approved colours | `apps/shopnova/…`, `callverse/data/shop_reads.py` (read-only) |
| 9 | Start script (checks Ollama, sets `CALLVERSE_AGENTS_SET=local`, starts on 127.0.0.1:8501) + README section | `start_shopnova.ps1`, `README.md` |
| 10 | 49 new offline tests | `tests/test_tickets_channel.py` (14), `tests/test_create_order_auth.py` (20), `tests/test_shopnova_app.py` (15) |
| 11 | Live proof once, then reseed + `callverse.db` deleted | — |

**New files in simple words.**
- `store.py` is the center's filing cabinet: one folder per ticket, holding the conversation and how the AI worked.
- `web_chat.py` is the center's front desk for website chats.
- `accounts.py` answers "who is logged in, and may they do this?"
- `shop_reads.py` is read-only lists for the shop pages.
- `shopnova_ui.py` is the parts every page shares (style, login box).

## 3. Evidence
- **Tests: 395/395 pass** (346 before + 49 new), 0 API calls (fake LLM, SLM offline, quota check replaced). `tests/data/*` not run.
- **Pinned versions** (the latest stable releases on 2026-10-29; `pip check`: no broken requirements, Python 3.12.10): `streamlit==1.66.1`, `streamlit-authenticator==0.4.2`, `bcrypt==5.0.0`.
- **Live proof** (`web_chat.send` called directly, because `config/accounts.yaml` does not exist yet; `CALLVERSE_AGENTS_SET=local`; trace `traces/t17_live_proof.jsonl`):
  - ticket **T-0001**, status **Solved**, main_reason refund_request, priority high, lead_agent **B**;
  - reply (source `slm`, first try): *"I'm sorry for the trouble. Your refund of 59.90 TND is approved. Your order 4512 is now cancelled."*;
  - **38 steps** saved: intake 1, route 2, tool_call 8, llm 8, proposal 1, coordinator 11 (9 checks all pass + decision), write 4, slm 3;
  - live texts shown in order: Reading your message… → Checking your order… → Checking with our refund team… → Checking your order… → Checking the rules… → Writing the reply…;
  - refund row written by the Coordinator in `shopnova.db`: **id 92**, order 4512, **59.90 TND**, status approved, rule **R-REF-03**, proposal **P-0001** (decision approve, "all checks passed under R-REF-03"); order 4512 → `refunded`;
  - **25.3 s** total; **Groq 7,053 tokens** (7 Agent B calls on gpt-oss-120b = 6,956 + the quota ping = 97); SLM qwen2.5:1.5b local (598 tokens); **0 Gemini**.
  - After the proof: `python -m callverse.data.seed` (4512 has 0 refunds again, 0 proposals, status stuck_at_depot) and `callverse/data/callverse.db` deleted.
- **App running:** started from `apps/shopnova` and listening on **127.0.0.1:8501 only** (netstat); `/_stcore/health` = ok; `/` and `/Shop` = HTTP 200; no errors in the log. Stopped afterwards.
- **Screenshots: not possible.** The Chrome extension was not connected, and without `config/accounts.yaml` no one can log in as Sara. What `AppTest` checked instead:
  - Shop has 6 Featured + 24 product cards per page with icons; search ("earbuds" → 1) and category ("Gaming PCs" → 1) work; Buy without a login shows only "Please log in to buy" and creates no order. Logged in as Sara, Buy ×2 creates an order for user 1.
  - My orders as Sara shows 4512 and 4509, not Youssef's 4510 / 4515. "Ask about this order" fills "About my order 4512: ".
  - Help chat sends through the channel and shows ticket T-0001 with 2 chat bubbles; "New chat" clears it. Logged out (or as admin), both pages show only "Please log in to see this page."
- **git status:**
  - `config/accounts.yaml`, `callverse/data/callverse.db` and `.env` are ignored (`git check-ignore` confirms) and not tracked.
  - `.vscode/` is left untracked. It is not mine, so I didn't commit it.

## 4. Problems
**Deviations from the task (open questions in section 5):**
- **`source = 'app'` was not possible.** The `orders.source` CHECK only allows `scripted` / `olist` / `generated`, and `docs/platform_contract.md` says "NULL = written at run time". So I followed the contract and used `source NULL` (+ `ai_generated 0`, `scripted 0`). An app order can still be told apart: `source IS NULL` and `id > 12000` (the highest seeded order id).
- **The payment method is not stored**, because orders have no column for it. `paid = total` for card, `0` for cash on delivery (like order 4514).
- **No Delivery line on app orders.** The shop's delivery fee is 0 for now, and the Buy box says so. Real Olist orders still show their real Delivery line in My orders.
- **Categories are not in the database.** Real products take theirs from the sample file. The 6 scripted products get a display-only category in `shop_reads.SCRIPTED_CATEGORIES`. Products added later (T18) will show as "Other" unless a category column is added.
- **Channel choices not fixed by the task:**
  - **escalate → status Open** (a human must look).
  - **"not your order" → Waiting for user.**
  - An order id that **does not exist** gets the same "not on your account" reply, so the message doesn't reveal whether the order exists.
  - "Busy" = **no B model answered OK** (daily limit *or* unreachable), not only a daily limit.
- **Step kinds beyond the design list:**
  - `llm` (needed for the Console's tokens per ticket).
  - `quota` and `identity` (the channel's own checks).
  - `search_policy` is split out of `tool_call`.
  - Each step keeps `trace_step` (the original trace name) in its data.
- **The start command differs a little from the task.** Streamlit reads `.streamlit/config.toml` from the folder it starts in, so the script runs `streamlit run Home.py` from `apps/shopnova`. The flags are the same.

**Fragile or limited:**
- **The quota ping costs about 97 Groq tokens per 5 minutes of chat use** (cache = 5 min, one model pinged).
- **One message at a time** (a lock in the channel): a second user waits. That's fine for a demo, slow for many users.
- **The ticket rule depends on the sim clock.** In a demo the clock stays at 2026-10-09 09:00, so a Solved ticket always reopens: "after 3 days" only happens if the clock is advanced. All ticket times are the same sim minute.
- **The live steps are not perfect:**
  - "Checking your order…" shows twice: Intake reads the order, then the agent does.
  - When the channel itself errors, the trace lines of the escalate reply are not saved as steps (the listener is already removed).
- **`st.chat_input` cannot be prefilled.** "Ask about this order" shows a small prefilled form above the chat box instead.
- **streamlit-authenticator waits about 0.7 s on every page run while logged out** (library default, to read the cookie).
- **The channel imports `scripts.quota_check`.** The quota logic lives with its script, as the task said; moving it into `callverse/` would be cleaner.
- **Ollama was not running at the start** (after the restart). I started `ollama serve` for the live proof and stopped it afterwards. `start_shopnova.ps1` stops with a clear message if Ollama is down.
- **Not checked by eye in a browser:** the floating help button, the colours, and the live `st.status` animation. Only AppTest and HTTP checks were run.

## 5. Questions for the Brain
1. `source` of app orders: keep `NULL` (contract), or add `'app'` to `seed.SOURCES` + the contract (Dali's lane, reseed needed)?
2. Add `category` (products) and `payment` (orders) columns, now or in T18 (the admin's "add product" needs a category)?
3. Statuses: is **escalate → Open** and **not your order → Waiting for user** right? Should an escalated ticket get its own status later?
4. Quota: "busy" when B is unreachable too (not only out of quota). OK?
5. T18: the tokens per ticket can come from the `llm` steps. Should the quota ping's tokens count too (today they don't)?

## 6. Next step
- Yassine runs `python -m scripts.create_demo_accounts`, starts Ollama, runs `.\start_shopnova.ps1`, and tries Shop / My orders / Help chat as Sara (screenshots for the review).
- Then T18 (Admin dashboard, Manage, Refund approvals with the real Layer 3 queue, using the `approvals` table that already exists).
