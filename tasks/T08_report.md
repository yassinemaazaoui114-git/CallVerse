# T08 report — Join the Coordinator and the SLM: one correct, polite final reply

## 1. In plain words
The Coordinator (T07) and the reply writer (SLM, T05/T05b) are now both in `main` and connected. The user no
longer sees the agent's own text. The agent proposes, the Coordinator decides and writes the key sentence
for the user ("Your refund of 59.90 TND is approved."), and the small local model writes the final reply
around it in the client's style. All four demo scenarios give one clean reply, with none of the internal
words (Coordinator, proposal, rule ids…). When Ollama is not running, a fixed template answers instead,
and nothing crashes.

## 2. Done
- **Step 0 — merges.**
  - `origin/feature/coordinator` → `main` (`8feec23`, no conflict).
  - `origin/feature/slm` → `main` (`66cd5f4`). Only the 2 expected conflicts, combined:
    - `config.yaml`: Gemini `tool_call_extras` + the `llm` block + the `ollama` provider + the `slm` models
      and settings;
    - `tasks/NEXT_PLATFORM.md`: the text from the task file.
  - `callverse/llm.py` merged on its own. T07's `options` and T05's `SAMPLING_SETTINGS` / `key_env: null`
    both work.
  - 223/223 tests, `main` pushed, branch `feature/reply` created.
- **Coordinator → user words** (`callverse/coordinator/coordinator.py`):
  - `user_words()` replaces `NEXT_STEPS` and gives `must_say` + `next_step` exactly as in the T08 table,
    with no timing and no payment method.
  - `slm_facts()` gives the decision's `facts` in the SLM's format: `order_status`, `days_late`,
    `amount_tnd`, `event`, and `threshold_tnd` + `layer3_decision` when Layer 3 was involved. All other
    checked facts (paid, refunded_total, …) stay in the trace (`checked_facts`).
  - After R-REF-03, `order_status` is the new status (`refunded`).
  - `STATUS_WORDS` is the fixed map from status codes to words (e.g. `stuck_at_depot` → "delayed at the
    delivery depot").
  - `for_user()`: `send_back` / `refused` stay internal. If the loop ends on one of them (the agent did not
    correct), the user gets the `escalate` words (traced `internal_outcome_to_escalate`).
- **`info` decisions** — `info_decision(order_id)` reads `get_tracking` itself and fills `order_status`,
  `days_late`, `promised_date`, `carrier`. It sets `must_say` "Your order N is …" and, in the R-DEL-02 case
  (1–5 days late, not delivered), the delivery-message offer. With no known order, it asks for the order
  number.
- **Final reply = SLM** (`callverse/pipeline.py`):
  - after the decision, `write_reply(decision + style, [client message])`;
  - the style comes from the ticket (`formality`, `length`, `shouting`, `emotion`, `sentiment`);
  - the result has `final_reply` and `reply_source` (`slm` / `slm_retry` / `template`) and keeps
    `agent_text`. The old `answer` key is removed, so agent text cannot reach the user by mistake;
  - trace step `final_reply`;
  - `slm_chat_fn` lets tests pass a fake SLM.
- **Dali's 3 fixes** (`callverse/slm/writer.py`), all plain code, applied to SLM replies **and** template
  replies (`polish`):
  - ", Your …" → two sentences, and every sentence starts with a capital. After a greeting, "Hi, Your" →
    "Hi, your"; "I" is kept;
  - each `must_say` sentence appears once (later copies removed, case-insensitive);
  - formal client → the reply starts with "Dear customer," before the calm opener ("Dear customer, please
    accept our apologies…"). Casual and neutral clients get no fixed greeting.
- **T07 follow-ups:**
  - `reasoning_effort: low` kept;
  - trace warning `rule_not_searched` (no refusal): the pipeline passes the rule ids that `search_policy`
    returned in that turn to the Coordinator;
  - simulator model → `gemini-3.5-flash`.
- **Scenarios** — `scripts/run_scenario.py`:
  - new `S0` ("Hi, where is my order 4510?");
  - prints the agent text marked "trace only", then **FINAL REPLY [source]**, a **leak check**, the seconds
    and the SLM model;
  - `run_pipeline.py` prints the reply too.
- **Ollama installed on this PC** (your OK): `winget install Ollama.Ollama` (0.40.6) + `ollama pull qwen2.5:3b`
  (1.9 GB).
- Tests:
  - new `tests/test_reply.py` (20);
  - `tests/conftest.py`: the SLM is offline in every test (behaves like a stopped Ollama → template), so
    tests never call Ollama;
  - 5 older tests moved from `answer` to `agent_text` / `final_reply`.
  - README updated.

## 3. Evidence
- Tests: after the merges **223/223**; now **243/243** (`python -m pytest -q`, no API, no Ollama).
- **S1** (`traces/run_20261021_013101_680958.jsonl`): "I'm sorry for the trouble. Your refund of 59.90 TND is
  approved. Your order 4512 is now cancelled." [slm]. The must_say sentence appears **once**. Order 4512 →
  **refunded**, refund row 59.90 R-REF-03 approved.
- **S2 `--inject-error`** (`traces/run_20261021_013135_590547.jsonl`): P-0001 70.0 → send_back, P-0002 59.9 →
  approve. **One** final reply after the approval, the same text as S1: it contains 59.90 and **no 70**.
- **S4** (`traces/run_20261021_013217_976930.jsonl`): "I'm sorry for the trouble. Your refund of 378.00 TND is
  approved after a check by our finance team. Your order 4515 is now cancelled." [slm].
- **S0** (`traces/run_20261021_013641_974855.jsonl`): "Hello, your order 4510 is on its way." [slm]. The status
  comes from tracking (`shipped`); no refund wording.
- **Leak check** on the final replies of S0, S1, S2, S4: **0 matches** for coordinator / agent / proposal / P-0 /
  R-+digits / "sent for checking". The leak check worked the first time, so no second try was needed.
- **Angry** "ORDER 4512 IS A WEEK LATE!!! I WANT MY MONEY BACK" → "**I'm sorry for the trouble.** ORDER 4512 Your
  refund of 59.90 TND is approved. Your order 4512 is now cancelled." The calm opener comes first
  (`…013733_014062`).
- **Formal** "Dear ShopNova, could you please tell me the status of my order 4510? Kind regards" →
  "**Dear customer,** your order 4510 is on its way. Kind regards" (`…013755_471672`).
- **Same S1 twice** (`…013101_680958`, `…013711_771717`): **identical** final reply.
- **Ollama stopped** (before the install), S1 → `[template]`: "I'm sorry for the trouble. Your request has been
  approved about your order 4512. Its current status is refunded; it is 6 days late; the amount is 59.90 TND.
  Your order 4512 is now cancelled. Your refund of 59.90 TND is approved." No crash, leak check clean
  (`traces/run_20261021_010614_509185.jsonl`).
- **Seconds per scenario** (Groq + SLM): S0 6.9 · S1 6.9–9.3 · S2 18.2 · S4 20.9.
  - SLM alone: **2.6–3.0 s** per reply.
  - SLM model: **qwen2.5:3b** (GPU RTX 4050 Laptop, 6 GB; 2.6 GB used with the model loaded).
  - First S0 after Ollama started: 82.3 s. See Problems.

## 4. Problems
- **Cold start**: the first SLM call after Ollama starts loads the model and timed out at 60 s
  (`APITimeoutError`). The retry passed (`slm_retry`). Later calls take ~3 s. For the demo, run one
  scenario first, or load the SLM at start-up the way Intake loads its models (not done: outside the
  task's steps).
- **Angry reply keeps a shouted fragment** "ORDER 4512" with no punctuation after it. The rule check passes
  it (the order number is there, the must_say sentence is there).
- **Formal reply ends with "Kind regards"**. `clean()` only removes a sign-off on its own line. Copying the
  client's sign-off is harmless, but the SLM prompt says "no signature".
- The template reply is plain and a bit odd ("Your request has been approved about your order 4512"). It is
  correct and safe; the wording is Dali's template.
- `layer3_refused` is not one of the SLM's known outcomes (its `layer3` means "needs approval"). The
  writer falls back to the `info` guide, and the `must_say` sentence carries the refusal (covered by the
  test of the words).
- A damaged-item request where Agent B asks for a photo (no proposal) becomes an `info` decision (the
  status), not `ask_proof`. `ask_proof` exists only when an R-DMG-01 proposal comes without proof.
- The tests got slower once (154 s), most likely while the Ollama installer was running; the final run took 33 s.
- `.vscode/` is untracked and not mine; it is not committed.

## 5. Questions for the Brain
1. Load the SLM at start-up (a warm-up call) so the first demo reply is not 60+ s?
2. Should `clean()` also drop a trailing sign-off on the same line ("… Kind regards"), and should
   `fix_punctuation` end a shouted fragment ("ORDER 4512 Your …")? Both are small code fixes in Dali's
   writer.
3. Should a damaged-item case without a proposal give `ask_proof` words ("Please send us a photo of the
   damage.") instead of `info`?
4. Add `layer3_refused` to the SLM's outcome guide and templates?

## 6. Next step
Review T08, merge `feature/reply`, then S3 (Agent A proposes `subscribe` → Coordinator → notifier, with Dali's
P08 clock) and the Client Simulator.
