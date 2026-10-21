# T09 report — Story S3 (delivery notification) + 4 small fixes from T08

## 1. In plain words
The last demo story works. The client asks "tell me when my order 4510 arrives". Agent A asks for a
notification, the Coordinator checks and approves it, and only then does the client get the promise. Time
moves forward on the simulation clock, the order is delivered, and the client gets exactly one message;
running the notifier again sends nothing. The replies are also cleaner now:
- the first reply is fast, because the small model is loaded at start-up;
- shouted words and copied sign-offs are removed;
- a broken item gets "Please send us a photo of the damage.";
- a refusal by finance has its own wording.

## 2. Done
- **Step 0 — merges.**
  - `origin/feature/reply` → `main` (`34fec2f`, no conflict).
  - `origin/feature/sim-clock` → `main` (`6a7a1d5`). Only the expected conflict, `tasks/NEXT_PLATFORM.md`: set
    to the P08 state, "Last done: P08 — accepted by the Brain 2026-10-21; merged in T09", Status "WAITING FOR TASK".
  - 254/254 tests, `main` pushed, branch `feature/s3-notify`.
- **Fix a — SLM warm-up**: `writer.warm_up()` makes one tiny call (traced `slm_warmup`) with the longer
  timeout `slm.warmup_timeout_s: 120` (`config.yaml`). For that, `llm.chat()` now takes an optional
  `timeout` (default still 60 s). If Ollama is off, it prints a warning and the replies use the templates;
  nothing crashes. It is called at start-up in `run_scenario`, `run_pipeline` and `run_notifier`.
- **Fix b — writer**:
  - `clean()` drops a sign-off at the end of the text ("… Kind regards", "Best regards", "Thanks, ShopNova").
    A closing "Thank you." sentence is kept (Dali's existing test);
  - `unshout()` turns "ORDER 4512 Your refund…" into "Order 4512: your refund…", and the same for
    "Order 4515 Your…". All-caps client words become lower case; numbers and real abbreviations
    (TND, OK, …) stay;
  - `must_say_once()` now also restores the Coordinator's **exact wording** of the one copy it keeps, as its
    own sentence ("Order 4507, please send…" → "Order 4507. Please send us a photo of the damage."). Right
    after a greeting it stays one sentence ("Hello, your order …").
- **Fix c — damaged item without a proposal** → `coordinator.proof_decision()`: outcome `ask_proof`,
  rule R-DMG-01, `must_say` "Please send us a photo of the damage.". The pipeline uses it when the ticket's
  `main_reason` is `damaged_item` and there is no proposal.
- **Fix d — `layer3_refused`** and the new **`notify`** outcome are added to the SLM's outcome guide and to the
  templates (refusal wording, no promise).
- **Agent A proposes a notification**: new tool `propose_subscription(order_id, event, user_quote)`
  (`callverse/tools/proposal_tools.py`). It checks the event against R-NOT-01 and defaults to `delivered`.
  It is on A's allow-list only, with its schema in the registry. A's prompt says: call it when the client
  asks to be told or accepts the offer, never promise the message in its own text, and put the client's
  exact words in `user_quote`. `AgentA.run()` returns the proposal (action `subscribe`, rule R-NOT-01), and
  the Coordinator reviews it like B's refunds; on approve it calls `create_subscription` and adds the
  `must_say` "You will get a message here when your order is delivered.".
- **Handover guard**: in one S3 run, Agent A proposed the subscription and also wrote `[HANDOVER: B]`. Agent B
  then ran and its "no proposal" result replaced A's approved decision. Now, when A already has a Coordinator
  decision, the handover tag is ignored (trace `handover_ignored`).
- **Notifier** — `callverse/notifier/notifier.py` (`callverse/notifier/` was already a package, so the file
  sits inside it instead of `callverse/notifier.py`). `run_notifier()`:
  - reads `get_pending_notifications()`;
  - builds a `notify` decision (`facts: {event, event_at}`, `must_say` "Your order N has been delivered." /
    "is out for delivery." / "has been shipped.");
  - the SLM writes the message;
  - trace `notification_sent`, then `mark_subscription_sent()`.

  `scripts/run_notifier.py` prints the messages.
- **S3** in `scripts/run_scenario.py`: message → A → Coordinator → reply → `advance(24)` → notifier →
  `advance(6)` → notifier → notifier again, then the subscription rows. **Every scenario** now rebuilds the
  data, calls `clock.reset()` and warms up the SLM first.
- Tests: new `tests/test_notify.py` (12). README updated.

## 3. Evidence
- Tests: after the merges **254/254**; now **265/265** (`python -m pytest -q`, no API, no Ollama).
- **S3** (`traces/run_20261021_024312_459995.jsonl`):
  - A called `propose_subscription(delivered, user_quote "when my order 4510 arrives")`;
  - P-0001 subscribe → approve; **1** subscription recorded;
  - reply: "Hello, order 4510, your request is approved. **You will get a message here when your order is
    delivered.**";
  - notifier after +24 h (4510 out_for_delivery) → **0**; after +30 h (delivered) → **1**: "Hello, your
    **order 4510 has been delivered.**"; notifier again → **0**;
  - subscription status **sent**. `python -m scripts.run_notifier` afterwards → "Messages sent: 0".
- **A called `propose_subscription` in 6/6 S3 runs** (the stop rule needed 2 of 3).
  - 1 of the first 3 runs hit the handover bug above (subscription recorded and sent, but the reply did
    not promise it). After the guard: 5/5 correct.
  - S3 twice in a row (with reset) → **same result**: same reply, same notification, same rows
    (`…023904_097896`, `…023927_923337`).
- **Status only** ("Hi, where is my order 4510?", S0) → **0** subscription rows.
- **Regression** (final code):

  | Scenario | Final reply | Trace |
  |---|---|---|
  | S0 | "Hello, your order 4510 is on its way." | `…024249_678765` |
  | S1 | "I'm sorry for the trouble. Your refund of 59.90 TND is approved. Your order 4512 is now cancelled." | `…023738_837533` |
  | S2 | P-0001 70.0 → send_back, P-0002 59.9 → approve; the same reply as S1, no 70 | `…023801_389227` |
  | S4 | "…Order 4515. Your refund of 378.00 TND is approved after a check by our finance team. Your order 4515 is now cancelled." | `…024055_530116`, `…024122_874642` |

  **Leak check: 0** on every final reply and on every notification text.
- **Fixes:**
  - **fresh Ollama start** (server restarted, no model loaded): warm-up **6.5 s**, then the first reply after
    5.3 s (S3) — well under 60 s. Warm-up afterwards: ~2.5 s;
  - **angry** "ORDER 4512 IS A WEEK LATE!!! I WANT MY MONEY BACK" → "I'm sorry for the trouble. Order 4512: your
    refund of 59.90 TND is approved. Your order 4512 is now cancelled." No all-caps client words;
  - **formal** "Dear ShopNova, … Kind regards" → "Dear customer, your order 4510 is on its way." No copied
    "Kind regards";
  - **damaged** "The speaker from order 4507 arrived broken" → `ask_proof` (R-DMG-01): "I'm sorry for the
    trouble. Order 4507. **Please send us a photo of the damage.**";
  - **`layer3_refused`** (unit test, template): "We cannot approve a refund of 600.00 TND for order 4515." +
    "we cannot approve this refund"; the rule check passes (no refund promise).
- Seconds (message → reply, Groq + SLM): S0 4.6 · S1 6.9 · S2 26.9 · S3 5.5 · S4 ~14. The SLM is qwen2.5:3b,
  ~2.6–3 s per reply.

## 4. Problems
- **S4 failed once in 3 runs**: Agent B answered "May I please have the order number?" without calling any
  tool, although 4515 is in the message and in the Intake note. The decision was `info`, so the user got
  the status, not the refund. The next 2 runs were correct. T09 did not change Agent B's prompt; this is the
  `reasoning_effort: low` kind of slip seen in T07.
- **Reply wording is still a bit stiff in places**: "Hello, order 4510, your request is approved. You will get
  a message…" and "Order 4515. Your refund…". Correct and leak-free, not elegant.
- `run_pipeline` runs do not reset the clock (only `run_scenario` does). That is fine for single messages.
- **Ollama on this PC**: to measure the fresh start, I stopped the Ollama app and started the server with
  `ollama serve` from this session. If that server stops with the session, restart the Ollama app (Start
  menu) before the demo.
- `.vscode/` is untracked and not mine; it is not committed.

## 5. Questions for the Brain
1. S4 slip (B asks for the order number although it is given): add one code safety net, e.g. when the
   Intake ticket has an order id and B made no tool call, run B once more? Or accept it as model noise?
2. Should the notifier use the client's style from the original ticket (today it uses a neutral style)?
3. Is the tone of "order 4510, your request is approved" OK for the demo, or should the subscribe outcome
   guide ask the SLM for a warmer sentence?

## 6. Next step
Review T09, merge `feature/s3-notify`, then the Client Simulator (M1, `gemini-3.5-flash`) playing S0–S4 end to end.
