# P09 report — Demo screen: type a user message, run the stories, see every step

## 1. In plain words
The local ShopNova server now has a demo page (`/demo`) for showing CallVerse live. On the left you type as a client
(or press a story button) and see the reply the client gets. On the right you see, step by step, how CallVerse handled
it: what Intake understood, which agent got it, which tools it used, each check of the Coordinator (green PASS / red
FAIL), what was written in the database, and how the final reply was made. It uses the one real pipeline; nothing is
copied or faked. The page is off by default and only works on this computer. The code and tests are finished, but the
live run with real models could not be done on this PC yet: the intake libraries and the Groq key are missing
("waiting for Dali", as the task says).

## 2. Done
- **`callverse/server/demo.py`** (new). Routes, all **off by default** (`config.yaml → server.demo_enabled: false` → 404):
  - `GET /demo` (the page);
  - `POST /demo/message {text}` → `pipeline.handle(text)` → `{run_id, final_reply, reply_source, route, decision, seconds, stages}`;
  - `POST /demo/story/{name}` → the stories from `scripts/run_scenario.py` (`SCENARIOS`, `inject_first_amount`,
    **imported, not copied**). Each story re-seeds first, so it always starts from the same data. A story not on this
    branch (S3) → `{"error": "not available yet"}`;
  - `GET /demo/runs/{run_id}` → the stages of that run, read from its trace file;
  - `POST /demo/clock/advance {hours}`, `POST /demo/clock/reset`, `POST /demo/notifier/run` (looks for T09's notifier;
    until then → "not available yet"), `POST /demo/reset` (re-seed + clock reset).
- **Safety**:
  - a lock: one request at a time, 409 when busy;
  - each request gets its **own trace run** (`run_id` = that file), and the server's trace is put back after;
  - S2's injection is wrapped in `try/finally`, so `pipeline.review` is always restored;
  - `run_id` must match `run_[A-Za-z0-9_]+` and resolve inside the trace folder (no `../`);
  - a POST whose `Origin` header isn't this server → 403;
  - every answer is scanned for key-like strings (`gsk_…`, `AIza…`, `sk-…`) and they are replaced by `[redacted]`;
  - a failing pipeline (e.g. missing model) → HTTP 200 with `error` and the stages so far, never a crash.
- **Stages** (built from the trace, read only): Intake (order id, reasons + scores, main reason, emotion, sentiment,
  priority), Route (agent, layer, handover), Agent (tool calls with short args/results, policy search, proposals,
  LLM model + tokens + seconds, waits/fallbacks, injected error, send-backs), Coordinator (each check with rule and
  PASS/FAIL + detail, Layer 3, decision), Platform writes (`db_write` / refused), Final reply (SLM checks, template,
  reply + source + seconds), Notifications (any notifier steps, once T09 exists), Clock.
- **`callverse/server/demo.html`** (new): the top bar has the simulation time and S0 / S1 / S2 / S4 / S3 / +24 h /
  Send notifications / Reset demo. Left: the chat (the reply is labelled "AI assistant") and the scripted orders
  4505–4515 with their current status. Right: stage cards (green PASS, red FAIL, amber NOTE). Plain HTML/CSS/JS, light
  and dark themes, `textContent` only.
- **`callverse/server/app.py`**: includes the demo router. **Dashboard**: link to `/demo`.
- **`config.yaml`**: `server: {demo_enabled: false}`.
- **Contract**: §8 note on the demo screen.
- **No core edit**: `run_id` comes from the per-request trace run, so the optional one-line pipeline edit wasn't needed.
  No new library.
- **Tests**: new `tests/test_demo.py` (15).

## 3. Evidence
- **Tests**: **266 passed / 269**. The 251 tests that existed before all pass unchanged; the 15 new ones pass. The 3
  failures are the known intake ones (`sentence_transformers` not installed); `main` has the same 3 (251/254).
- **New tests (fake LLM, fake Intake, stubbed policy search, offline SLM → template)**:
  - `/demo/message` with the S1 text → reply contains "Your refund of 59.90 TND is approved."; **6 stages** (Intake,
    Route, Agent, Coordinator, Platform writes, Final reply); every Coordinator check PASS; writes show `record_proposal` +
    `create_refund`;
  - demo routes → **404** when `demo_enabled` is false (page, message, story, runs, reset, clock, notifier); `/clock`
    still works; `config.yaml` ships with `false`;
  - `/demo/reset` → 4512 back to `stuck_at_depot`, 4510 `shipped`, clock `2026-10-09T09:00:00`;
  - S3 and the notifier → `{"error": "not available yet"}`, HTTP 200;
  - **S2 then S1**: S2 decisions = `SEND_BACK, APPROVE` with the injected error shown; afterwards `pipeline.review` is
    the original, and S1 = `APPROVE` only, with nothing injected;
  - run ids: `..%2F..%2Fconfig`, `run_..`, `abc`, `run_x%2F..%2Fy`, an unknown id → **404**;
  - `Origin: http://evil.example` → **403**; the same origin and no Origin header → 200;
  - lock held → **409**; the server trace comes back after each request; two requests get two different runs;
  - key scan: with `GROQ_API_KEY=gsk_…` in the environment, and a pipeline error message containing `gsk_…` and
    `AIza…`, **no** response contains `gsk_` or `AIza` (the error shows `[redacted]`).
- **Real code without models (this PC)**: with the demo turned on in memory, `POST /demo/story/S1` → HTTP 200,
  `error: "ModuleNotFoundError: No module named 'sentence_transformers'"`, its own run id, no crash; `/demo` → 200; S3 →
  "not available yet"; reset → OK. The real DB was re-seeded afterwards (MD5 `e18ff80b…`, as before).
- Page JavaScript: `node --check` OK.
- **Live check (real models): NOT DONE — waiting for Dali.** Missing on this PC: `torch` / `transformers` /
  `sentence-transformers` (intake) and `GROQ_API_KEY` in `.env` (count 0). As the review note says, I didn't install or
  create anything. To do, once installed:
  1. set `server.demo_enabled: true`;
  2. run `python scripts/run_platform_server.py` and open `http://127.0.0.1:8000/demo`;
  3. type "Order 4512 is a week late. I want my money back." → expect "Your refund of 59.90 TND is approved." and an
     all-PASS Coordinator card;
  4. press S2 (one send-back then approve), S4 (Layer 3 step) and Reset;
  5. note the seconds per run and take 2 screenshots.

## 4. Problems
- **Conflict with a P08 test**: `test_clock.py::test_server_shows_the_clock_read_only` fails if *any* POST route path
  contains "clock" in the OpenAPI listing, and P09 asks for `POST /demo/clock/advance`. I kept the P08 test unchanged
  and set `include_in_schema=False` on the demo router. The demo routes don't appear on `/docs` (they are 404 by
  default anyway), and the normal server API still has no route that moves the clock. Please confirm this is acceptable.
- **Stories re-seed the database** before running (as `run_scenario.py` does), so pressing S1 twice approves twice.
  Typed messages do **not** re-seed: after S1, typing the same message again finds 4512 already refunded.
- **`/demo/reset`** leaves the (empty) clock tables in the DB, so its MD5 differs from a plain seed. The data is identical.
- **Single user**: while one run is going (it can take several seconds with real models), other demo requests get 409.
- A pipeline that fails mid-run (e.g. a missing model) returns the error; the stages show what ran before it.
- No screenshots yet (live check pending).

## 5. Questions for the Brain
1. Is hiding the demo routes from `/docs` OK, or should the P08 test be narrowed to "no clock route outside `/demo`"?
2. Should typed messages also re-seed (like the stories), or keep the data between messages (more realistic)?
3. When T09 lands: confirm the notifier function name (I look for `run`, `send_pending`, `notify_pending` or
   `run_notifier` in `callverse/notifier/notifier.py`) and how S3 is defined (one message, or message + clock + notifier).

## 6. Next step
Dali: install the intake libraries and add `GROQ_API_KEY` to `.env`, then run the live check above (2 screenshots, seconds
per run). After T09 is on `main`, merge `main` into `feature/demo-screen` to enable S3 and "Send notifications".

Git: branch `feature/demo-screen` created from the latest `main` (6a7a1d5, contains T08), committed and pushed. Not merged.
