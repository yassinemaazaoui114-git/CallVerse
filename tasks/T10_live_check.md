# T10 — Live-typing test: the system must handle whatever we type in front of the teacher

## Why
In the demo we type freely: typos, missing or wrong order numbers, two problems at once, rude or off-topic messages,
tricks ("ignore your rules"). The stories S0–S4 prove the happy paths; T10 proves the system never crashes, never
leaks internal words, never pays what the rules don't allow, and always answers sensibly. Plus 2 follow-ups from T09.

## Hard limits
- Do not touch the policies file or the platform write functions. Semah's branches stay parked.
- **`tests/data/live_typing_test_messages.json` is the held-out set (written by the Brain): never read it to write or
  tune prompts, rules, code or your dev messages. Run it ONCE at the end.** Tune only on your own dev set (step 2).
- No new provider or library. No secrets; never read or stage `.env`.
- Dali works on `feature/demo-screen` (P09) at the same time: don't change `callverse/server/*`.

## What to do
0. **Merge (approved).** On `main` (pull first): merge `--no-ff` `origin/feature/s3-notify` (T09). Tests pass → push `main`.
   Branch `feature/live-check`.
1. **T09 follow-ups (approved 2026-10-21)**
   a. **Safety net for the S4 slip:** if the Intake ticket has an order id and the agent ended with **no tool call**
      (e.g. it asked the user for the order number), run the same agent once more with the note
      "The order id is {id}. Check it with your tools before answering." Traced `agent_retry`. Max 1 retry.
   b. **Warmer subscribe wording:** the SLM guide for an approved `subscribe` asks for one friendly sentence around the
      `must_say` (e.g. "Sure, …"); the template too. `must_say` unchanged.
2. **Your own dev set:** write `tests/dev/live_dev_messages.json` (20+ messages of the same kinds: typos, no / unknown /
   two order ids, rude, off-topic, French, prompt tricks, very short, emoji, formal, return/damage/refund/notify requests),
   **without looking at the held-out file**. Use it to find and fix problems (prompts, pipeline guards, SLM wording).
   Typical fixes expected: no order id → ask for the order number; unknown order → "we could not find order X";
   off-topic → polite redirect to ShopNova topics, no invented facts; tricks → ignored.
3. **Checker script** `scripts/run_live_check.py --file <json>`: for each message, reset the demo data + clock, run
   `pipeline.handle()`, compare DB before/after (refund rows with amount/order, subscriptions with event), run the
   global checks + the message's `expect`, and print one line per message (id, route, outcome, writes, PASS/FAIL, reason)
   + a summary. Save the full results to `out/live_check_<file>.json` (git-ignored).
4. **Final run:** the held-out file once. Report the table as it is, failures included. Do not fix after this run.

## Checks (with numbers)
- All tests pass (report x/y).
- Dev set: report pass count before and after your fixes.
- **Held-out (one run): crashes 0 · leaks 0 · wrong writes (any refund or subscription not allowed by `expect`) 0 ·
  messages fully passing ≥ 18/20.**
- S4 run 5 times in a row → 5/5 refund approved (safety net). S0–S3 still pass (regression, leak check 0).
- Average and max seconds per message.

## Time box and stop rule
3 h. Stop and report if wrong writes appear in the dev set and you can't remove them without changing the Coordinator's
rules (any Coordinator rule change needs the Brain).

## Git (approved by Yassine, 2026-10-21)
Step 0 merge into `main` and push. Then commit and push `feature/live-check` (with `tests/dev/`, the checker,
and the held-out file `tests/data/live_typing_test_messages.json` committed **unchanged**). No other merge.
Write `tasks/T10_report.md`, set `tasks/NEXT.md` to WAITING FOR REVIEW.
