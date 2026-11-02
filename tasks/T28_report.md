# T28 report — Desktop shortcuts + step 09 (conversation memory, bare yes/no, one decision per message)

**Top line:** Done, except one live proof and F5b. The Desktop shortcut starts the platform with a double-click (tested).
Step 09 is built and tested: 1811/1811 pytest (+30 new), 62/62 vitest, build OK, 72-message regression **72/72**,
0 wrong writes, 0 leaks, 0 API calls. Two things were not shown live:
- "bare yes → refund written": the yes reached the Coordinator, which asked again because the first message had no
  money-back words the code knows;
- F5b (the Urgent badge, A → C → B): none of 7 candidate messages took that path.

## 1. In plain words
You can now start CallVerse from the Desktop with one double-click, and reset it with another. The assistant now
remembers the conversation inside one chat. It knows which order "it" means. It keeps the one question it asked
("Please confirm…"), so a plain "yes" or "no" answers that question. When one message asks for two things, it handles
one decision and tells the user to send the other money request as a new message. A model never decides from memory:
the "yes" goes through the same rule checks as before.

## 2. Done
- **Step 1, shortcuts.** On the Desktop (`C:\Users\mam83\OneDrive\Desktop`, the real Desktop folder):
  - `CallVerse Demo.lnk` → `Demo.bat` (play-arrow icon, shell32 #137);
  - `CallVerse Reset.lnk` → new `Reset.bat` → `scripts/reset_demo.ps1` (asks YES; recycle-bin icon, shell32 #31).

  New `scripts/make_shortcuts.ps1` (re)makes both. `scripts/start_demo.ps1` now starts Ollama (`ollama.exe serve`,
  minimized) if it does not answer, and waits up to 60 s. The Reset shortcut was NOT run.
- **Step 2:** `docs/step09_design.md`.
- **Step 3, memory:** `callverse/channels/conversation.py` + table `pending_questions` (tickets DB, `store.py`).
  - Earlier id: last 6 messages, user messages only, only when the message refers back (it / that / the order …),
    then the same identity check.
  - Pending question: who asked, order / booking, proposal id + action, Intake reason, flags from the first message,
    status, 30-minute expiry.
- **Step 4, bare yes/no** (`web_chat._send`, step 0):
  - yes + open question of A/B → `conversation.resume`. It reads the proposal back from the company DB by id, makes a
    NEW proposal and runs the normal `review` (Layer 3, write).
  - The Coordinators read `case["yes_answer"]` (`negation.yes_confirmation`): a refund needs `money_back` (Atlas:
    and no `expenses`); a ShopNova cancel needs `cancel_order`. Atlas also keeps its reason ↔ action check.
  - yes + C's offer → the P20 path (unchanged). no → closed, fixed reply, status Solved. Any other message → cleared.
  - Double yes: an atomic `UPDATE … WHERE status='open'`.
- **Step 5, one decision per message:** 2+ different ids = several requests. The money part goes through the
  pipeline. Each other part gets one sentence by code: its status, "not on your account", or the fixed "Please send
  your request about order N as a new message…" (always last).
- **Step 6, T14f follow-ups:**
  - "no refund please / needed / thanks" counts as negative (`negation.NO_WISH_RE`). "still no refund please help",
    "got no refund" and "no refund yet" stay requests.
  - TWCS-style draft tweets as tests (Claude-written, marked draft in the test).
  - The other T14f follow-ups → section 5.
- **Step 7a:** Promotions shows "No sales in the last 30 days" instead of 9,999 days (+1 vitest).
- **Step 7b:** no reliable message found (see Evidence).
- **Docs:** `docs/DEMO_RUNBOOK.md` (shortcuts, conversation rules, F5b not found), README (Desktop start, T28).
  Live-check script: `scripts/run_t28_live.py`.

## 3. Evidence
- **Shortcut test:** Ollama stopped → double-click `CallVerse Demo.lnk` → Ollama started, web UI + `/api/docs`
  answered after **12 s**, browser opened on 5173 (redirects to `/login`). Both windows closed afterwards (API and UI
  down). No command typed.
- **pytest:** 1811/1811 (main had 1781; +30 in `tests/test_t28_conversation.py`). **vitest:** 62/62; `npm run build` OK.
  `Chat.test.jsx` ("a failed request … is shown") failed 1 of 3 runs while pytest was running in parallel. That file
  is not changed by T28; it is a timing flake.
- **Regression (72 messages, same runners as T14f/T26, local models), `out/t28_compare.txt`:**
  decline_practice 12, decline_heldout 12, t14b 12, t14c_practice 12, t14c_heldout 12, t14d_heldout 12.
  **72/72**, wrong_writes 0, crashes 0, leaks 0, API calls 0, avg 19.2 s, max 25.9 s.
  Changed vs T26: h10 and s02 now pass. a05 went `ask_user` → `not_your_order`, still "pass" but wrong: my splitter
  read "May **2018**" as a second booking. Fixed: an id without an order word must not look like a year and must exist
  in the data (+1 test). a05 re-run: `ask_user AT-FLT-01`, 0 refunds (`out/t28_a05_rerun.json`). The held-out files
  were only run, never tuned on.
- **Live flows** (`out/t28_live*.json`, user Sara, order 4512, fresh seed each scenario):

| Scenario | Messages → outcome (seconds) | Result |
|---|---|---|
| S1 | "Where is my order 4512?" → info (12.1) · "It is so late. Can I get my money back for it?" → **approve** (24.0) · "yes" → info (20.8) | memory found 4512 for "it"; B approved at once, so no question was open; the later "yes" wrote nothing (1 refund row) |
| P5 | "Order 4512 is late and I need it tomorrow for a birthday. If it can't arrive in time, I'd rather have the money returned to me." → **ask_user** "Please confirm that you want a refund of 59.90 TND for order 4512." (27.1) · "yes" → ask_user (**2.7 s**: Coordinator only, no agent) · "yes" → info (20.9) | the yes went through the Coordinator; "money returned" is not a known money-back phrase, so it asked again; **0 refunds** |
| S2 | C's offer (F5 text) → ask_user (27.4) · "Yes" → **approve** (40.9) | replacement, as before |
| S3 | "Please refund order 4512, it is very late, and where is order 4509?" → **approve** (23.8) | refund once + "Order 4509 is delivered." |
| S4 | "yes" (new chat) → info (20.8) | normal path, nothing written |
| U1–U7 | 7 urgent candidates (max 8) | all `B by router` (refund_request goes to B directly): **no A → C → B**, F5b not found |

## 4. Problems
- The live "yes → write" was not seen. With the real model, B asked "Please confirm" only when the code's money-back
  check failed, and then a yes correctly cannot pass it. When B's model said user_confirmed false although the words
  were there (the case a yes can complete), it did not happen in these runs. Unit tests cover it, including one write
  on double yes.
- Agent C's "yes" path still uses the P20 rule (any message while C waits goes back to C). The new pending row only
  adds "no" and expiry for C.
- After a bare "yes" the Coordinator may ask again (P5). The next "yes" then goes the normal way (re-asked). Safe, but
  the user can loop until they type the money words.
- Several requests: only id-based. One message with two money actions on ONE order ("refund and cancel 4512") is
  still one request.
- The memory "refers back" rule is wide ("it", "that"): a message with "it" and no id gets the user's earlier order
  (own order only, after the identity check).
- The runners and `run_t28_live.py` rebuild `shopnova.db` / `atlas.db` from the seed. I made a copy first
  (`out/t28_dbbackup/`) and put it back after each run.

## 5. Questions for the Brain
1. Should "money returned (to me)", "reimbursed", "paid back" count as money-back words
   (`request_words.asks_for_money_back`)? Then P5's yes would write. It widens the T14f safety check, so I did not
   change it.
2. F5b: the Urgent badge needs A → C → B, but any message with money words is routed to B directly. Show it with a
   fixture ticket instead, or change routing (architecture: needs your decision)?
3. Should C's "yes" also require the open pending row (stricter: an unrelated message would no longer go to C)?
4. T14f Q1 (ShopNova refunds fully by code, like Atlas) is still open.

## 6. Next step
Brain review → Yassine merges: `git checkout main && git pull && git merge --no-ff feat/t28-step09` (then the tests
run on main and NEXT is set to DONE). After that: RL5.
