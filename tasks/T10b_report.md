# T10b report — Finish T10 on this PC (STOPPED at the daily limit: held-out run aborted unscored)

## 1. In plain words
Everything is merged and runs on this PC, and the demo screen works here. The quota guard worked:
- before starting, all three AI models answered;
- the S1 refund story passed;
- during the held-out live-typing test, Groq's main model hit its daily limit at message 16 of 20, and the
  test stopped itself **without scoring**.

So the one official held-out run is **still unused**, as the task requires. I then stopped all AI runs
(stop rule) and finished the parts that need no AI: the demo switch, a screenshot of the demo page, and the
demo-day runbook.

## 2. Done
- **Step 0 — merges.**
  - `origin/feature/live-check` → `main` (`4944c0d`).
  - `origin/feature/demo-screen` (P09, P09b, fixes 3f0333d) → `main` (`4cba464`).
  - No conflicts. **297/297** tests. `main` pushed. Branch `feature/t10b`.
- **Quota guard** (step 1):
  - `llm.is_daily_limit()` recognises a daily quota: Groq "tokens/requests per day (TPD/RPD)", Gemini
    "exceeded your current quota". A per-minute limit is not counted.
  - `llm.chat` records each daily-limit hit in `llm.DAILY_LIMIT_HITS` (trace `llm_daily_limit`) and
    moves to the next model.
  - New `scripts/quota_check.py`: one "Say OK." call per agents model, alone. Exit 2 on a daily limit.
  - `scripts/run_live_check.py` runs that check first. During the run, a daily-limit hit **aborts the
    whole run without scoring**: no results printed, `out/live_check_<file>_aborted.json`, trace
    `live_check_aborted`, exit 2. Results are printed only for a finished run.
- **Demo switch** (step 5): `CALLVERSE_DEMO_ENABLED=1` turns the demo routes on without editing
  `config.yaml` (`callverse/server/demo.py`, `demo_enabled()`). `config.yaml` stays
  `server.demo_enabled: false`. Only the value "1" switches it on. Test: `tests/test_demo_env.py`.
- **Demo page on this PC**: server started with the env var; `/demo` → 200. Screenshot
  `docs/screenshots/t10b_demo_this_pc.png` (page loaded, scripted orders table, buttons S0–S3, +24 h,
  +30 h, Send notifications, Reset demo). **S0 was not pressed**: the stop rule after the daily limit means
  no more AI calls. The server was then stopped.
- **`docs/DEMO_RUNBOOK.md`**: the day before (no tests, record a backup video), then in order: start Ollama →
  `quota_check` → start the server with `$env:CALLVERSE_DEMO_ENABLED = "1"` → open `http://127.0.0.1:8000/demo`
  → warm-up S0 + Reset demo → S1 → S3 (+24 h / notify / +30 h / notify) → S2 → S4 → live typing; what to do
  if Groq is out, Ollama is off, or replies are slow; how to stop. No keys.
- Tests: 2 new in `tests/test_llm.py` (daily limit detected and remembered; a per-minute limit is not
  daily), plus `tests/test_demo_env.py`.

## 3. Evidence
- Tests: after the merges **297/297**; after step 5 **300/300**.
- **Quota guard**: `python -m scripts.quota_check` → gpt-oss-120b **OK**, gpt-oss-20b **OK**,
  gemini-3.5-flash **OK** (exit 0).
- **S1 smoke** (`traces/run_20261021_095155_411083.jsonl`): approve, refund **59.90** R-REF-03, order 4512 →
  refunded. Reply: "I'm sorry for the trouble. Your refund of 59.90 TND is approved. Your order 4512 is now
  cancelled." [slm]. Leak check clean. 8.5 s.
- **Held-out run**: `python -m scripts.run_live_check --file tests/data/live_typing_test_messages.json` →
  "ABORTED, NOT SCORED: daily limit during message L16: ['groq/openai/gpt-oss-120b', …]. Messages finished
  before the stop: 15 (results not shown)." Exit 2. Record: `out/live_check_live_typing_test_messages_aborted.json`.
  **Not scored, so it does not count as the one run.** I did not look at the 15 finished results; they are
  not saved.
  - **Done in T12 (2026-10-24 10:19–10:25), the one official run:** 20/20 passed · crashes 0 · leaks 0 ·
    wrong writes 0 · avg 16.4 s · max 51.3 s. Pass rule (0 · 0 · 0 · ≥ 18/20) met. Details: `tasks/T12_report.md`.
- **Regression S0, S2, S3, S4**: **not run** (stop rule: first daily-limit error).
- **Tokens used today** (from the traces, `llm_call` lines):

  | Window | gpt-oss-120b | gpt-oss-20b | Gemini | qwen2.5:3b (local, free) |
  |---|---|---|---|---|
  | T10b (since 09:00, 4 runs) | 65,927 | 3,617 | 145 | 10,548 |
  | Whole day 2026-10-21 (52 runs) | 213,288 | 319,886 | 17,771 | 89,308 |

  - Agent B average over today's T10b turns: **4,349 tokens per turn** (`scripts/token_report.py`, 14 turns).
  - Groq's limit is 200,000 tokens per **rolling 24 h** per model, so last night's T10 runs (around 03:00)
    still counted: 120b reached the limit after only ~66k tokens this morning.

## 4. Problems
- **The free quota is the blocker.** The held-out test needs about 80,000–120,000 gpt-oss-120b tokens in one
  go. That fits only when the rolling 24 h window is nearly empty, i.e. about 24 h after the last heavy run.
  Last heavy runs: T10 dev runs ~03:00–03:30 and T10b ~09:40–10:00 on 2026-10-21.
- The quota check passed, then 120b ran out at message 16. A "few tokens" check cannot tell whether
  100,000 tokens are left. Groq's answer headers (`x-ratelimit-remaining-tokens`) are per minute, not per day,
  so they do not help either.
- `/demo` was checked by loading the page only, not by pressing a story (no AI calls allowed after the stop).

## 5. Questions for the Brain
1. When to run the held-out file? Proposal: the first thing in a session **≥ 24 h after 2026-10-21 10:00**,
   with nothing else before it except `quota_check` (no smoke test), so the full quota goes to the test.
   Then the S0–S4 regression on another day, or after it if quota is left.
2. Should the live check fall back to gpt-oss-20b instead of aborting when only 120b is out (20b passed the
   dev set 24/24)? Today any daily-limit hit aborts (task rule).
3. The runbook says to record a backup video the evening before. OK, or should someone else's free Groq
   account be the demo backup? That is still the same free tier, but a different quota.

## 6. Next step
1. In ≥ 24 h: `python -m scripts.quota_check`, then the held-out run **once**, then fill the numbers into
   `tasks/T10_report.md` and here.
2. Then S0, S2 (`--inject-error`), S3, S4 regression.
3. Then press S0 on `/demo` and add that screenshot.
