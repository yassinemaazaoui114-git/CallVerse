# T28 — Desktop shortcut + step 09 (conversation memory, several requests in one message, bare "yes")

## Why
Yassine needs (1) to open the platform with a double-click on the Desktop, no command, and (2) step 09 of the roadmap: the system must follow a conversation, not only one message.
He approved the simplest options (2 Nov, 11:44): memory inside ONE conversation only; one decision per message; a bare yes/no is resolved by code only when an open question exists.
Main = 4aa0bf8 or later (T27 merged, 1781 tests).

## Hard limits
- Branch `feat/t28-step09` from main. Claude Code never merges into main (CLAUDE.md rule 11). No secrets; never read or print `.env`. No force push.
- Main's safety must survive: money-back words, negation check, decline by code, proof flag, hidden fields, off-topic fixed text, Coordinator rules, Layer 3 queue. Never weaken a check to make a test pass.
- **Amounts, order/booking ids and decisions are never taken from memory text.** Memory only (a) carries an order/booking id the SAME user already named in this conversation, after the identity check, and (b) holds one open question. A model never decides from memory.
- Do not tune on held-out files (`tests/data/*heldout*`); use practice sets and new Claude-written practice messages (mark them "draft" in the file name).
- Fix rule: failures are fixed in code (a check, a default, a structure), not with a prompt trick for one model.
- Models: local `callverse-m2-v3` first; Groq only as backup. Do not run `scripts/reset_demo.ps1` (it deletes the demo DB) except in the live check with a copy or fixture; do not read the accounts file.

## What to do
0. Create the branch. Commit this file + NEXT.md. Write `tasks/T28_progress.md` and update it after every step (WIP protocol).
1. **Desktop shortcut (do this first, small).** T26 made `Demo.bat` and `scripts/start_demo.ps1`. Make sure there is a shortcut **"CallVerse Demo"** on the Desktop of `C:\Users\mam83` (a `.lnk`, with an icon) whose double-click does everything: starts Ollama if it is not running, starts the API and the frontend, waits until ready, opens the browser on the login page. No typed command. Add a second shortcut **"CallVerse Reset"** that runs the reset script (it asks to type YES; that is fine). Add `scripts/make_shortcuts.ps1` that (re)creates both so it can be repeated. Test the demo shortcut once (start, health OK, then close the windows it opened). Do NOT run the reset shortcut. Say in the report exactly what is on the Desktop.
2. **Design note first:** `docs/step09_design.md` (1 page): where the conversation is kept today (read `callverse/channels/web_chat.py`, `callverse/tickets/store.py`, `callverse/pipeline.py`, `webui/api/chat.py`), the memory shape, the pending-question record, the multi-request rule, the bare yes/no rule, and the tests. Then build it.
3. **Conversation memory (within one conversation = one chat session/ticket of one user).** Keep the last 6 messages and ONE pending question (who asked: B "Please confirm…" or C's offer; the order/booking id; the proposal id/type; the original message's money-back flag; created time; expires after the next user message or 30 minutes). Intake reads the history only to find an order/booking id the user did not repeat ("and what about it?") — the id must belong to the logged-in user (identity check as today).
4. **Bare "yes"/"no".** When a pending question exists: "yes/yeah/ok/please do/confirm" (and the Arabic/French equivalents Intake already knows, if any) continues exactly that proposal through the NORMAL path (Coordinator, Layer 3, writes); "no/cancel/never mind" closes it with a short reply. For a ShopNova refund the money-back words check uses the flag stored from the original message (the user already asked for the money back). With no pending question, a bare "yes" is re-asked as today. A new unrelated message clears the pending question. Test: expired, cleared, wrong user, double "yes" (one write only).
5. **Several requests in one message.** Rule: **one decision per message.** Intake finds a second request cheaply (a second booking/order id, or a second reason above its threshold, or "and"/"also"/"?" split — choose the simplest that works and write it in the design note). The system handles the highest-priority one (money action first), answers a plain information part from facts, and the reply ends with a fixed sentence asking the user to send the other money request as a new message. No second write in the same turn. Test with the L04 style messages (refund 4512 + where is 4511).
6. **T14f follow-ups — only the small ones:** read the follow-up list in `out/T14f_report.md` and `tasks/T14f_*.md`, do those that fit (e.g. "no refund please" counted as a refusal in the negation check; real TWCS-style tweets without money-back words), put the rest in the report as limits. Held-out files stay untouched.
7. **Small fixes from T27:** (a) in `webui/frontend/src/screens/OwnerProposals.jsx` show "No sales in the last 30 days" instead of "9,999 days"; (b) find ONE fixed demo message that reliably gives A → C → [HANDOVER: B] so the **Urgent badge** shows live (try 3–4 candidate messages, max 8 live runs), add it to `docs/DEMO_RUNBOOK.md` as F5b. If none works, say so.
8. **Tests and regression.** Full suite green. The 72-message set as in T14f/T26 (`run_decline_check` + `run_t14c`; bar >= 70/72, 0 wrong writes, 0 leaks). New tests for steps 3–5 (at least 15). `npm --prefix webui/frontend test` + `run build` if the frontend changed.
9. **Live check with the real models** (fixture accounts as in T27 are fine): a 3-message conversation (B asks "Please confirm" → bare "yes" → refund proposed/written once), C offer → "yes" (already works), a two-request message, a bare "yes" with nothing open. Record message text, ticket, outcome, seconds.
10. **Docs:** `docs/DEMO_RUNBOOK.md` (shortcuts, F5b, the conversation flow), README (T28 + how to start from the Desktop). Report `out/T28_report.md` (also copy to `tasks/T28_report.md` and commit it): top line; shortcut details; design summary; test counts; regression; live flows; what is left; questions for the Brain.

## Checks (all reported)
Full suite green; regression bar met; 0 wrong writes; double "yes" = one write; wrong user's pending question not usable; the Desktop shortcut starts the platform without any typed command; nothing under `models/`, `data/raw/` or secrets in the diff.

## Time box and WIP protocol
3 hours. Commit a WIP after each step and keep `tasks/T28_progress.md` current; if the session stops, the next one reads it. Priority if time runs short: 1, 2, 4, 3, 5, 7, 6, 8–10. Push the branch. Close other apps before the live runs (7.7 GB RAM).

## Git
Branch `feat/t28-step09` from main; push; the report lists the merge line for Yassine (the Brain reviews first). Update the README at the end (CLAUDE.md rule 8).
