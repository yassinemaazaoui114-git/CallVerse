# T14d — progress (WIP, 2026-11-01)

Branch `feat/t14d-request-match`. Model: Opus 5.5 (Yassine chose to keep Opus for this task).

## Done (offline, items 0–4)
- 0. Branch from main (68b36d3). Full suite before: **1283 passed**.
- 1. ShopNova, money words are not an order cancellation: `callverse/intake/request_words.py` → `cancels_order(sentence, message)`.
  It is used by Intake (`reasons.py`), the LLM fallback (`llm_fallback.cancel_is_justified`) and the ShopNova Coordinator
  (`cancel_confirmed`: "the cancel is not about the order"). The cancel does not count when the thing cancelled is money
  ("cancel this payment"), when a cancel button was pressed by accident, or when the message talks about money and does not
  name the order. "cancel my order 4511" still wins.
- 2. Atlas, a ticket refund needs a money-back request: `asks_for_expenses(sentence)` (hotel costs, meals, taxi,
  "reimbursement", unless it is the ticket or booking itself) → Intake gives `compensation_request`, by the word.
  `atlas_coordinator.ACTION_REASONS`: a refund or hotel cancellation is confirmed only under refund_request / cancellation,
  and never on a sentence about expenses. If the proposal does not match the request, the rule's no to what the client
  asked is given (h03 → AT-FLT-06); if no rule says no, the client is asked first.
- 3. `scripts/run_t14c.py` (edited in place, no copy): `status_wrong_write` flags an order-status change that
  `expect.order_status` does not allow.
- 4. `negation.py` step 1c: "not refunded/returned/credited/reimbursed" + a time word (yet, till, until, still, since, for N,
  ... ago), or "not yet refunded", is a complaint. 8 + 8 synthetic tests.
- Tests: `tests/test_t14d.py` (52 tests). Full suite **1335 passed**.
- Two T21 tests (`test_routing_by_company.py`) moved from booking 7007 to 7004: on 7007 a refund proposed for a compensation
  request now gets the compensation decline AT-FLT-03 (intended T14d change), so the send-back path is tested on 7004.
- Dev check (offline, Intake only): of all dev/practice messages, only h03 (→ compensation_request) and h12 (→ no cancel_order)
  change their result. s03, s05, t12 and T14a's h08 still give cancel_order.

## Left (Monday, fresh Groq quota)
- 5. Practice run: `python -m scripts.run_t14c --file tests/data/t14c_heldout_messages.json --out out/t14d_practice.json`
  (with `CALLVERSE_AGENTS_SET=local`, Ollama running). Note the Groq tokens.
- 6. Held-out, once: `python -m scripts.run_t14c --file tests/data/t14d_heldout_messages.json --out out/t14d_heldout.json`.
  The file has not been opened. Do not fix anything after this run.
- Write `tasks/T14d_report.md`, set `tasks/NEXT.md` to WAITING FOR REVIEW.
