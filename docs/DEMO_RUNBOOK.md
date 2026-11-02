# CallVerse demo runbook (T26)

How to start, run and repeat the live demo with the new web UI and the real models.
Every message below was run live on 2026-11-02 (T26 step 7) with `callverse-m2-v3` (agents A, B, C) and
`qwen2.5:1.5b` (SLM, the reply writer), in queue mode, with 0 Groq tokens.

## 1. Before the demo
- Ollama is running, with `callverse-m2-v3` and `qwen2.5:1.5b` (the start script checks both).
- `config/accounts.yaml` exists (if not: `python -m scripts.create_demo_accounts`; Yassine sets the passwords).
- Close heavy apps: the PC has about 8 GB RAM and the local model needs about 3 GB.

## 2. Start and reset
- **Start**: double-click the **"CallVerse Demo"** shortcut on the Desktop (or `Demo.bat`). No command to type: it
  starts Ollama if it is not running (T28), checks the models and the accounts, opens two windows (API on
  http://127.0.0.1:8610, web UI on http://127.0.0.1:5173), waits until both answer and opens the login page.
  Measured (T28): Ollama stopped → ready in 12 seconds. Close the two windows to stop.
- **Reset** (to repeat the demo): close the two windows first, then double-click **"CallVerse Reset"** (or `Reset.bat`,
  which runs `scripts\reset_demo.ps1`) and type `YES`. It rebuilds the ShopNova and Atlas data and deletes all
  tickets, chats and approvals.
- The two shortcuts are made (again) by `powershell -ExecutionPolicy Bypass -File .\scripts\make_shortcuts.ps1`.
- Reset between flows that use the same order (F1 and F5 both use order 4512).

## 3. Demo flows, in order (exact messages)
Log in as the customer, open the order or booking ("Ask about this order / booking"), type the message.

| Flow | Account | Message | What happens (live result) | What to say |
|---|---|---|---|---|
| F1 | sara | `Hi, my order 4512 is very late. I want my money back please.` | Refund 59.90 TND approved by code, ticket **Solved** (38 s) | Agent B proposes, the Coordinator's rules approve; the model never writes to the database. |
| F2 | youssef | `My order 4515 never arrived. I want a refund.` | 378.00 TND is above the limit: **Waiting for finance** (23 s). Then log in as `admin`, Approvals, Approve: refund written once, ticket Solved, reply sent | Big money waits for a human (Layer 3); the decision is one transaction. |
| F3 | nizar | `My flight 7004 was very delayed. I want compensation.` | Compensation 839.50 TND waits (18 s); `atlas_admin` approves it | Same center, second company, its own rules. |
| F4 | amira | `Hi, where is my order 4511?` | "Your order 4511 is being prepared." (9 s) | Agent A only reads; facts come from tools. |
| F5 | sara (after a reset) | `Order 4512 is late and I need it tomorrow, it's a birthday gift!` then `Yes` | Agent C offers a free replacement and asks (25 s); after "Yes" the Coordinator approves: new order 12001 (22 s) | Agent C handles urgent needs; nothing changes before the client says yes. |
| F6 | hedi | `My flight 7005 was cancelled. Please put me on the next flight.` | **Escalated** to a colleague; the reply says "There is no later flight on this route for your booking 7005, so a colleague will contact you about your options." | Agent C looks for a later flight; the real 2015 schedule has none. T29: by code C cannot propose a flight then (the tool refuses), and the pipeline hands the case to a colleague with that fixed sentence. Nothing is written. Show this as a safety example. |
| F7 | `admin`, then `atlas_admin` | Web UI: ShopNova admin → Dashboard → "Check stock now" → Promotions → approve one; Atlas admin → Dashboard → "Check rooms now" → Hotel deals → approve one | ShopNova: 42 short products, 3 promotions proposed (pending for the owner). Atlas: 2 low-occupancy hotels, 2 hotel deals proposed (pending) | Agent D is rules, not an LLM: the same numbers give the same answer. It only proposes; the owner decides. |

F7 runs in the web UI since T27 (the Streamlit pages still work too). After F5, log in as `supervisor`: Live tickets
shows the ticket; Ticket detail lists "What was done" (waiting for the user's yes, then "Replacement created: new
order …"). A ticket Agent C passes to Agent B as an urgent refund shows the red "Urgent" badge (Live tickets, Ticket
detail, and first in the admin's Approvals).

## 4. Known limits (say them if asked)
- T28: a bare "Yes" / "No" answers only the ONE open question of this chat (Agent B's "Please confirm …" or Agent C's
  offer), for 30 minutes and only as the very next message. With nothing open, "Yes" goes the normal way (re-asked).
  A refund confirmed by "Yes" still needs money-back words in the client's first message ("I want my money back").
  Money-back words (T14e, T14f, T29): "refund", "money back", "my money", "pay me back" / "paid back", "chargeback",
  "reimburse my ticket", "reimbursed" / "reimbursement", "money returned / refunded", "returned to me" (with a money
  word close by), "repay me". Not: "return the item", "returned my order", "non-reimbursable". Said in the negative
  ("I do not want to be reimbursed") they count for nothing. At Atlas a bare "reimbursement" next to hotel costs stays
  a compensation question (T14d).
- T29: a refund for an order with nothing paid (cash on delivery, not delivered: 4514) is refused already at Agent B's
  proposal step, not only by the Coordinator.
- F5b (the Urgent badge live, A → C → B) is not in this list: in T28, 7 candidate messages were run live and none took
  that path (a message with money words goes straight to Agent B). The badge is shown by the vitest and unit tests.
- T28: one decision per message. "Refund order 4512 and where is order 4509?" → the refund is handled, 4509 gets its
  status in one sentence; a second money request gets "Please send your request about order N as a new message".
- Agent D has no seats (flights): it checks hotel rooms only at Atlas.
- F6 cannot complete a rebooking: the real flight data has no later flight on that route. Since T29 Agent C cannot
  propose a flight then (refused by code at the tool step); the case goes to a colleague with one fixed sentence.
- The C/D practice cases are Claude-written drafts and have no held-out set (P20).
- Local models are slow on this PC (9-40 s per message). If Ollama is slow or stops, the backups are Groq models
  (daily limits).

---

## Appendix: the older demo (T14d / T19, `/demo` page and stories S0-S4)
Kept as it was before T26 (still valid as a backup if the new web UI does not start).

### CallVerse — demo day runbook (Yassine's PC)

> **T19 (2026-10-30): the `/demo` page is replaced by the CallVerse Console** (`Console.bat`, http://127.0.0.1:8502, see README). Its files will be removed after Dali's OK; until then this runbook still works as written.

Everything runs on this PC: the local ShopNova server, the demo page, the local reply model (Ollama).
The agents use the free Groq models (backup chain: gpt-oss-120b → gpt-oss-20b → Gemini Flash).
> **T14d finish (2026-11-01):** Agents A and B now run on Dali's local model `callverse-m2-v3` (Ollama). Groq / Gemini are
> only Agent B's backups, used if the local model fails, so the daily Groq limit no longer blocks the demo. Before the
> demo check `ollama list` shows `callverse-m2-v3` (create it from `models/m2/Modelfile_v3`, see README).
No key is written in this file: keys stay in `.env` (never shown, never committed).

## The day before
1. **Do not run test sets or long checks in the 24 hours before the demo.** Groq's free limit is
   200,000 tokens per day per model, counted over the last 24 hours (T10b: one day of testing used it all).
   One story costs about 4,000–10,000 tokens.
2. Record a backup video of the stories (S1 → S3 → S2 → S4) on the evening before, when the quota is fresh,
   with the screen recorder (Win + Alt + R, Xbox Game Bar). Keep it on the desktop.

## On the day, in this order

### 1. Start Ollama (the reply writer, qwen2.5:3b)
Start menu → **Ollama** (the app starts the server in the background). Check in PowerShell:
```powershell
Invoke-WebRequest -UseBasicParsing http://localhost:11434/api/tags | Select-Object StatusCode
```
`200` = OK. If the app does not start: `& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" serve` in its own window.

### 2. Check the quota (a few tokens, 10 seconds)
```powershell
cd C:\Users\mam83\dev\callverse-proto
.\.venv\Scripts\Activate.ps1
python -m scripts.quota_check
```
All three lines `OK` → go on. A line `DAILY LIMIT` → that model is out for today: the backup models take over
automatically. If all three say `DAILY LIMIT`, use the backup video (see "If Groq is out").

### 3. Start the server with the demo screen on
The demo screen is off in `config.yaml` (kept off in git). Switch it on for this window only:
```powershell
cd C:\Users\mam83\dev\callverse-proto
.\.venv\Scripts\Activate.ps1
$env:CALLVERSE_DEMO_ENABLED = "1"
python -m scripts.run_platform_server
```
Leave this window open (it shows the trace file). The server answers only on this PC (127.0.0.1).

### 4. Open the page
Browser: **http://127.0.0.1:8000/demo** (use `127.0.0.1` or `localhost`, port 8000; other addresses are refused).

### 5. Warm-up
Press **S0** once (status of order 4510; only Agent A, cheap). It loads the reply model; the first answer may
take 10–20 s, the next ones 4–10 s. Then press **Reset demo**.

### 6. Stories, in this order
| Order | Button | What the teacher sees |
|---|---|---|
| 1 | **S1** | Late order 4512 → Agent B proposes 59.90 → Coordinator checks the rules → approved, order cancelled |
| 2 | **S3**, then **+24 h**, **Send notifications**, **+30 h**, **Send notifications** | "Tell me when 4510 arrives" → subscription approved → 0 messages after 24 h (only out for delivery) → 1 message after 30 h (delivered) |
| 3 | **S2** | Same as S1 with an injected wrong amount (70.00) → sent back (R-REF-05) → corrected → approved |
| 4 | **S4** | Order 4515, 378 TND → finance (Layer 3) approves → refund approved after the finance check |
| 5 | Live typing | Type freely in the chat box (typos, wrong order number, off-topic, "ignore your rules"…) |

Press **Reset demo** between stories if you want each one to start from the original data (S1 and S2 both
refund 4512).

## If something goes wrong
- **A reply says "Your case needs an extra check, so it has been passed on for review."** → an AI provider
  failed or is out of quota; the system did not crash. Check the server window / run `python -m scripts.quota_check`
  in another window.
- **Groq is out (DAILY LIMIT on 120b and 20b)**: the chain moves to Gemini Flash automatically (slower, same
  checks). If Gemini is out too: play the backup video and explain the architecture on the screen of a
  finished run (the right panel shows every step).
- **Replies are slow (> 30 s)**: a per-minute limit; the system waits up to 20 s and retries. Wait, or move on
  to the next story.
- **The reply looks like a fixed sentence list** ("Here is the latest information…") → Ollama is not
  running; the template answered. Start Ollama (step 1); no restart of the server needed.
- **Page says the demo routes are off** → the server was started without `$env:CALLVERSE_DEMO_ENABLED = "1"`.
  Stop it (Ctrl+C) and start it again as in step 3.

## How to stop
1. Server window: **Ctrl+C**.
2. Close the browser tab.
3. Ollama: right-click its tray icon → Quit (optional).
The data is a local demo database: it is rebuilt by **Reset demo** or `python -m callverse.data.seed`.
