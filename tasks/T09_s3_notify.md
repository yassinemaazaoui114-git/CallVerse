# T09 — Story S3 (delivery notification) + 4 small fixes from T08

## Why
S3 is the last demo story: the user asks to be told when the order arrives, the system promises it only after the
Coordinator approves, time passes (Dali's P08 clock), the order is delivered, and the user gets one message.
The 4 fixes make the replies demo-ready (no 82 s first reply, no shouted fragment, right words for damaged items
and for a finance refusal).

## Hard limits
- Only the steps below. Do not touch Intake, the policies file, the platform write functions, `tests/data/*`.
- Semah's branches and PR #1 stay parked (final version): no merge, no change.
- No new provider or library. No secrets; never read or stage `.env`.
- A notification is promised to the user **only** after `create_subscription` succeeded (R-NOT-01).
- The notifier never sends the same subscription twice.

## What to do
0. **Merges (approved).** On `main` (pull first): merge `--no-ff` `origin/feature/reply` (T08), then
   `origin/feature/sim-clock` (P08 + fix 9053ed4). Expected conflict: `tasks/NEXT_PLATFORM.md` → keep the
   P08 report state from `feature/sim-clock` and set "Last done: P08 — accepted by the Brain 2026-10-21; merged in T09",
   Status "WAITING FOR TASK". Run all tests; if they pass, push `main`. Then branch `feature/s3-notify`.
1. **Fixes from T08 (approved 2026-10-21)**
   a. **SLM warm-up**: load the SLM at pipeline/scenario start-up (one tiny call, traced `slm_warmup`), and let the
      first SLM call use a longer timeout (e.g. 120 s, in `config.yaml`). Ollama off → warning, no crash.
   b. `writer.clean()`: drop a client sign-off copied at the end of a line ("… Kind regards", "Best regards", "Thanks,");
      `fix_punctuation`: a shouted fragment like "ORDER 4512 Your refund…" becomes "Order 4512: your refund…"
      (never leave all-caps words from the client in the reply, except the order number).
   c. **Damaged item without a proposal**: when the ticket's main reason is `damaged_item` and there is no proof yet,
      the pipeline builds an `ask_proof` decision (R-DMG-01): `must_say` "Please send us a photo of the damage."
      (not the `info` status reply).
   d. **`layer3_refused`** added to the SLM's outcome guide and templates (refusal wording, no promise).
2. **Agent A proposes a notification.** New tool `propose_subscription(order_id, event, user_quote)` in A's
   allow-list (registry + schema). `event` ∈ shipped · out_for_delivery · delivered (default `delivered` when the user
   says "when it arrives"). A's prompt: propose it when the user asks to be told, or accepts the R-DEL-02 offer;
   never promise it in its own text. The proposal goes to the Coordinator (action `subscribe`, rule R-NOT-01) like
   B's refunds; on approve: `create_subscription`, `must_say` "You will get a message here when your order is
   {event in words}."
3. **Notifier** — new `callverse/notifier.py` `run_notifier() -> list[dict]`:
   - reads `get_pending_notifications()`;
   - for each: builds a decision `{outcome: "notify", action: "notify", order_id, facts: {event, event_at},
     must_say: ["Your order {id} {has been delivered | is out for delivery | has been shipped}."], next_step: ""}`;
   - the SLM writes the message (add `notify` to the SLM outcome guide + template);
   - "sending" = trace step `notification_sent` (order, subscription, text) + returned in the list;
   - then `mark_subscription_sent(subscription_id)`. Second run → 0 messages.
   - `scripts/run_notifier.py` (prints the messages).
4. **Scenario S3** in `scripts/run_scenario.py`:
   reset the clock → user: "Hi, can you let me know when my order 4510 arrives?" → A proposes `subscribe(delivered)`
   → Coordinator approves → final reply → `advance(24)` → notifier (expect 0: out_for_delivery not subscribed)
   → `advance(6)` → notifier (expect 1) → notifier again (expect 0). Print each step.
   **Every scenario (S0, S1, S2, S4, S3) resets the clock and the scenario data first**, so the order of runs never matters.

## Checks (with numbers)
- All tests pass (report x/y).
- **S3:** subscription recorded **1**; reply contains "You will get a message here when your order is delivered.";
  notifier after +24 h → **0**; after +30 h → **1** message containing "Your order 4510 has been delivered.";
  notifier again → **0**; subscription status `sent`.
- A user who asks about status only ("where is order 4510?") gets **no** subscription (0 rows).
- **Regression:** S0, S1, S2 (`--inject-error`), S4 still pass with the T08 checks; leak check 0 on every final reply and
  on the notification text.
- Fixes: first SLM reply after a fresh Ollama start **< 60 s** (report the time); angry reply has no all-caps client words;
  formal reply has no copied "Kind regards"; "The speaker from order 4507 arrived broken" → reply contains
  "Please send us a photo of the damage."; a `layer3_refused` decision (unit test) → refusal wording, no promise.
- S3 run twice in a row (with reset) → same result.

## Time box and stop rule
2 h 30 min. Stop and report if Agent A does not call `propose_subscription` in 2 of 3 S3 runs after one prompt fix.

## Git (approved by Yassine, 2026-10-21)
Step 0 merges into `main` and push. Then commit and push `feature/s3-notify`. **No other merge.**
Write `tasks/T09_report.md`, set `tasks/NEXT.md` to WAITING FOR REVIEW.
