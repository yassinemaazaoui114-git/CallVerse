# P09b — Demo screen: S3 + notifications, Host check, live check  ·  Dali's lane

## Why
P09 is accepted (Brain re-run 266/269, 3 = intake models). `main` now contains T09 (3daab60: story S3 + notifier),
so the demo screen can show the full S3 story. Plus one security hardening and the live check with real models.

## Hard limits
- Continue `feature/demo-screen`. First `git fetch` and **merge `origin/main` into your branch** (allowed: your own branch).
- Server files and their tests only. Do not touch agents, Coordinator, SLM, Intake, notifier, `tests/data/*`.
- Demo routes stay off by default and hidden from `/docs` (approved). No new library. Never show or log keys.

## What to do
1. **S3 button** = the whole story, like `scripts/run_scenario.py S3`: reset the clock and data → message
   "Hi, can you let me know when my order 4510 arrives?" → show the reply → the page then offers **+24 h**, **+30 h**,
   **Send notifications**. "Send notifications" calls `callverse.notifier.notifier.run_notifier()` and shows each message
   (order, text) in the chat as a new message from ShopNova, and as a "Notifications" stage.
2. **Typed messages keep the data** between messages (no re-seed; more realistic). The Reset button is the only reset.
   Show a small line under the chat: "Data changes stay until you press Reset demo".
3. **Host check (approved):** demo routes also refuse a request whose `Host` is not `127.0.0.1:8000` or
   `localhost:8000` (port from config if set) → 403. One test.
4. **Live check** with real models on your PC (intake libraries + `GROQ_API_KEY` in `.env`, Ollama running):
   S1, S2, S4, S3 (+30 h → 1 notification), and one typed message. 2–3 screenshots in `docs/screenshots/`
   (no key visible). Report seconds per run.

## Checks (with numbers)
- All tests pass (x/y), existing tests unchanged.
- S3 on the page: 1 subscription; notifications 0 after +24 h, 1 after +30 h, 0 when pressed again.
- Wrong Host → 403 (test). Demo off → 404 (unchanged).
- Live: S1 reply contains "Your refund of 59.90 TND is approved."; S2 shows 1 send-back then approve; S4 shows the
  finance step; seconds per run.

## Time box and stop rule
90 minutes. Stop and report if the merge of `main` conflicts outside server files.

## Git (approved by Yassine, 2026-10-21)
Commit and push `feature/demo-screen`. No merge into main. Write `tasks/P09b_report.md`, set `tasks/NEXT_PLATFORM.md`
to WAITING FOR REVIEW.

## Notes from review (Dali, 2026-10-21)
- **This PC is ready for the live check**: intake libraries installed (torch 2.14.1+cpu, sentence-transformers),
  `GROQ_API_KEY` set in `.env`, Ollama running. Before P09b the full suite passed (intake tests included).
- **`demo_enabled` stays `false` in every commit.** Turn it on only in the working copy for the live check, then put it
  back (`test_default_config_has_the_demo_off` guards this). Restart the server after changing it.
- **Clock buttons add time**: +24 h then +30 h = 54 h after the start. Check the numbers both ways (+24 h → 0,
  then +30 h → 1 notification; pressing "Send notifications" again → 0), and say in the report what the buttons do.
- **Screenshots**: crop or check that no `.env` content, terminal with keys, or browser autofill is visible.
- After the live runs, press **Reset demo** (or re-seed) so the local DB is back to the seed state.
