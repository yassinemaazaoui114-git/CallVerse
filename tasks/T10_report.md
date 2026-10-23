# T10 report — Live-typing test (PARTIAL: held-out run and S0–S3 regression not run, API quotas used up)

## 1. In plain words
The system now copes much better with free typing:
- typos, a missing or unknown order number, off-topic questions, insults and tricks ("ignore your rules")
  all get a sensible, polite answer;
- if the agent forgets to look up an order it was given, it is asked once more;
- if any AI provider fails mid-way, the user gets a polite "extra check" reply instead of a crash.

On my own 24 practice messages, every check passes (21/24 before the fixes). The final exam (the Brain's 20
held-out messages) could **not** be run: all three AI providers hit their daily limits during testing. I
stopped here as agreed with Yassine, so the one allowed held-out run is still unused.

## 2. Done
- **Step 0 — merge**: `origin/feature/s3-notify` → `main` (`3daab60`, no conflict), 265/265 tests, pushed.
  Branch `feature/live-check`, commit `ecfe484` (pushed).
- **1a — safety net**: in `pipeline.run_agent_with_coordinator`, if Intake found an order id and the agent
  ended with **no tool call** and no proposal, it runs once more with "The order id is {id}. Check it with
  your tools before answering." (trace `agent_retry`, max 1).
- **1b — warmer subscribe wording**: the SLM guide for an approved `subscribe` asks for one friendly
  sentence ("Sure, …"), and the template starts "Sure, we can do that for your order N.". `must_say` is
  unchanged.
- **Fixes found with the dev set**:
  - **Unknown order** → "We could not find order X." + "Please check the order number and send it again."
    (`info_decision`).
  - **Off-topic** (main reason `other`, no order) → `off_topic_decision`: "I can help with your ShopNova
    orders: delivery, refunds, returns and damaged items." + ask for the order number if it is about an order.
  - **Insult echoed back**: the SLM copied the client's message ("You useless idiots, …") into the reply.
    The pipeline no longer gives the client's text to the SLM: the tone comes from Intake's style, the
    content only from the decision.
  - **Status replies padded with invented comments** ("not met", "mix-up"): the `info` guide now asks for
    at most two short sentences and no comments.
  - **Near-duplicate sentence** ("Hello, order 4510 is on its way. Your order 4510 is on its way."): code
    drops a sentence that only repeats part of a must_say sentence.
  - **Crash guard**: an error in the agents' part (any exception) is traced as `pipeline_error` and gives
    the `escalate` reply. Test asserts still go through.
  - **Groq 400 `tool_use_failed`** (gpt-oss-20b wrote the tool name `ask_agent<|channel|>commentary`): this
    is the model's own error, so it now falls back to the next model like a 429. Every other 400 is still
    raised.
  - **Gemini after a Groq fallback** gave a 400 "Function call is missing a thought_signature": earlier
    tool calls in the turn were made by Groq. `llm.messages_for` now adds Google's documented placeholder
    signature to tool calls from another model. Checked with one real call: raw → 400, fixed → accepted.
- **Checker** `scripts/run_live_check.py --file <json>`:
  - for each message: seed + `clock.reset()`, snapshot of paid / refunded / tracking, `pipeline.handle()`,
    the new refund and subscription rows;
  - global checks: crash, empty or > 120 words, internal words incl. tool names, every refund row allowed
    (amount ≤ paid − refunded and the rule condition true on the data before the run), "approved" only on
    approve, rude words repeated;
  - all 13 `expect` keys;
  - one line per message + summary; full results in `out/live_check_<file>.json` (`out/` git-ignored).
- **Dev set** `tests/dev/live_dev_messages.json`: 24 messages (typos, no / unknown / two order ids, rude,
  off-topic, French, 2 prompt tricks, very short, emoji, formal, all caps, return, damage, refund cases,
  notify, two problems, "?").
- **Held-out file** `tests/data/live_typing_test_messages.json` committed **unchanged** (git blob `c07b83c`).
  To write the checker, I read only its `_note`, its `global_checks` list and the **names and types** of its
  `expect` keys, never the message texts or expected values. It was **not run**.
- Tests: new `tests/test_live.py` (9) and 2 new tests in `tests/test_llm.py`.

## 3. Evidence
- Tests: after the merge **265/265**; now **276/276**.
- **Dev set**: **21/24 before** the fixes → **24/24 after**, run twice:
  - `traces/run_20261021_030820_689802.jsonl`, then on the final code `out/live_check_live_dev_messages.json`;
  - crashes 0 · leaks 0 · wrong writes 0;
  - final run: avg **12.1 s**, max **35.1 s** per message.

  The 3 failures before:
  - d03: unknown order, no "could not find";
  - d05: the insult copied back;
  - d09: crash, Gemini 400 after a Groq fallback.
- **S4 five times in a row**: **4/4 approve** (378.00, "approved after a check by our finance team"). The 5th
  run got `escalate`: all three providers were out of quota (see Problems). It did not crash, the reply was
  polite, and leak check 0.
- **S0–S3 regression: not run cleanly.** The attempt came after the quotas ran out; all 4 ended as polite
  `escalate` replies (no crash, leak check 0), but that proves nothing about the stories.
- **Held-out run: NOT RUN** (kept for one clean run).
  - T10b (2026-10-21 ~09:55): the run started and was **ABORTED, NOT SCORED** at message L16 (gpt-oss-120b
    daily limit). It does not count as the one run. Numbers still pending: see `tasks/T10b_report.md`.

## 4. Problems
- **Daily quotas are the demo's biggest risk.** The traces show 429 "tokens per day":
  - Groq gpt-oss-120b and gpt-oss-20b: 200,000 TPD each, used up;
  - Gemini: "exceeded your current quota", retry in 16,139 s.

  The dev runs (2 × 24 messages) plus scenarios used about a day of free quota. During the last dev run the
  agents ran mostly on gpt-oss-20b (89 calls) with 3 on 120b and 4 on Gemini, and still passed 24/24.
- When every provider is out of quota, every message gets the "extra check" reply. That is safe, but the
  demo would show nothing.
- The SLM sometimes still ignores the "Sure, …" guide for subscriptions (the code-made template has it).
- Removing the client text from the SLM input also removes the language hint: French messages are answered
  in English, as the SLM prompt already says.

## 5. Questions for the Brain
1. Quotas: for the held-out run and the demo day, add a paid key (Groq dev tier) or an OpenRouter model to
   the agents' chain? Both change a locked model decision, so they need your OK. Or simply avoid running
   test sets on the demo day.
2. When should the held-out run happen? I suggest the start of the next session, right after the Groq quota
   resets: first S0–S4 (regression), then the held-out file once.
3. Keep "no client text to the SLM" (safer, no echo), or give it a cleaned version (rude words removed)
   for tone?

## 6. Next step (what is left of T10)
1. When the quotas are back: S0, S1, S2 (`--inject-error`), S3, S4 ×5 (regression, leak check 0).
2. `python -m scripts.run_live_check --file tests/data/live_typing_test_messages.json`, **once**. Report the
   table as it is.
3. Fill in the held-out numbers here (crashes, leaks, wrong writes, x/20, avg / max seconds).
