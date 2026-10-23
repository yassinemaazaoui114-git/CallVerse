# CallVerse — demo day runbook (Yassine's PC)

Everything runs on this PC: the local ShopNova server, the demo page, the local reply model (Ollama).
The agents use the free Groq models (backup chain: gpt-oss-120b → gpt-oss-20b → Gemini Flash).
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
