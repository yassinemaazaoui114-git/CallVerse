# P09 — Demo screen: type a user message, run the stories, see every step  ·  Dali's lane

## Why
The prototype is shown live to the teacher. Today it only runs in a terminal. P09 adds one page to Dali's P05
server where we type as a user (or press a story button) and see how CallVerse handled it, step by step:
Intake → route → agent → Coordinator checks → platform writes → final reply. It is a small first version of the
future back office, so nothing is wasted later.

## Hard limits
- Branch `feature/demo-screen` from the latest `main`. **Start when `main` contains the T08 merge**
  (`git log origin/main --oneline | grep T08`; Yassine's T09 pushes it at its step 0). Later, merging newer `main`
  into your branch is fine (needed for S3 and the notifier once T09 lands).
- **One pipeline:** the page only calls `callverse.pipeline.handle()` and the scenario code. No second pipeline,
  no copy of agent or Coordinator logic. Allowed core edit: if the pipeline result has no `run_id`, add it (one line).
- Server files, `callverse/server/*`, a new `callverse/server/demo.py` if useful, their tests. Do not touch agents,
  Coordinator, SLM, Intake, policies, `tests/data/*`.
- **Demo routes are off by default** (`config.yaml → server.demo_enabled: false`); when off they return 404.
  Server stays on 127.0.0.1. One request at a time (a lock): the demo is single-user.
- No new library. Plain HTML/CSS/JS, no build step. **Never show or log API keys.**

## What to do
1. **API (demo routes):**
   - `POST /demo/message {text}` → `pipeline.handle(text)` → `{run_id, final_reply, reply_source, route, decision, seconds}`;
   - `GET /demo/runs/{run_id}` → the trace of that run grouped into stages (below);
   - `POST /demo/story/{S0|S1|S2|S4|S3}` (`S2` with the injected error) → same answer shape. Stories not on `main` yet
     (S3 before T09) → `{"error": "not available yet"}`, no crash;
   - `POST /demo/clock/advance {hours}`, `POST /demo/clock/reset`, `POST /demo/notifier/run` (once T09's notifier exists);
   - `POST /demo/reset` → reseed the demo data + reset the clock (so every live demo starts clean).
2. **Stages** built from the trace (read only): Intake (order id, reasons + scores, main reason, emotion, sentiment,
   priority label + score) · Route (agent, layer) · Agent (each tool call with short args/result, LLM model + tokens +
   seconds, any wait or fallback) · Coordinator (each check: name, rule, PASS/FAIL, detail; outcome; send-backs) ·
   Platform writes (proposal ids, refund rows, status changes, subscriptions) · Final reply (text, source slm/template,
   seconds) · Notifications (when present).
3. **Page `/demo`:** top bar = simulation time + buttons (S0, S1, S2, S4, S3, +24 h, Send notifications, Reset demo);
   left = chat (typed message, final reply, small "AI assistant" label); right = the stages as cards, in order,
   PASS green / FAIL red, internal words allowed here (this is the back office, not the user's view).
   A small panel lists the scripted orders 4505–4515 with their current status (helps to pick an order when typing live).
4. Link `/demo` from the P05 dashboard.

## Checks (with numbers)
- Existing tests: all pass unchanged (report x/y).
- New tests (fake LLM): `/demo/message` returns the final reply and ≥ 5 stages for the S1 text; demo routes return **404**
  when `demo_enabled` is false; `/demo/reset` puts 4512 back to `stuck_at_depot` and the clock to 2026-10-09 09:00;
  a story not available → `{"error"}`, status 200 or 404, no crash; no response contains a key (scan for `gsk_`, `AIza`).
- Live (real models, your PC): typed "Order 4512 is a week late. I want my money back." → reply contains
  "Your refund of 59.90 TND is approved." and the Coordinator card shows all checks PASS; S2 button shows one send-back
  then approve; S4 shows the Layer 3 step; Reset works. Report the seconds per run and add 2 screenshots to the report.

## Time box and stop rule
2 h 30 min. Stop and report if `pipeline.handle()` can't be called from the server without changing core code
beyond the one-line `run_id`.

## Git (approved by Yassine, 2026-10-21)
Commit and push `feature/demo-screen`. No merge. Write `tasks/P09_report.md`, set `tasks/NEXT_PLATFORM.md` to WAITING FOR REVIEW.

## Notes from review (Dali, 2026-10-21)
- **S2 injection must not leak into later requests**: `scripts/run_scenario.py` replaces `pipeline.review` globally for S2.
  In a long-running server that would inject the error into every later message. Reuse the scenario helpers (import,
  don't copy) and always restore `pipeline.review` in a `try/finally`, under the demo lock. Add a test: S2 then S1 →
  S1 has no send-back.
- **One trace run per demo request**: call `trace.start_run()` per request so `run_id` names that run's file, and put the
  server's own trace back afterwards. `GET /demo/runs/{run_id}` must accept only ids like `run_YYYYMMDD_...`
  (letters, digits, `_`), never a path (`../`), else 404. Add a test.
- **Cross-site requests**: when demo routes are on, any website open in the same browser could POST to
  `127.0.0.1:8000`. Refuse demo POSTs whose `Origin` header is present and is not this server (403). Add a test.
- **Live check prerequisites** on Dali's PC: intake's libraries (`torch`, `transformers`, `sentence-transformers`) and a
  `GROQ_API_KEY` in `.env`. If either is missing, do not install or create anything: finish the code + tests, and
  report the live part as "waiting for Dali". Dali installs, then the live check runs.
