# T14a — "Say no with the reason" + ShopNova cancellation (R-CAN-01)

## Why
Since T12, "no / why" requests (return too late, refund not allowed, already refunded, cancel) get only the order
status: a case **without a proposal** falls back to `info_decision`. Users never learn **why**. ShopNova also has no
cancellation rule, so "please cancel my order" cannot be handled. T14a adds (1) a **decline** decision written by code
with the rule and the reason, and (2) a real **cancel** action for orders still being processed. All details approved by
Yassine on 2026-10-31 (all ⭐). T14b (later) does the SLM fixes, hidden fields, Atlas declines, the off-topic opener and
the R-DMG-01 proof flag; "second question in one message" moves to step 09.

## Hard limits
- **ShopNova only.** Atlas files, prompts and behaviour unchanged (Atlas tests still pass).
- **Decline = code, no LLM.** The Coordinator decides "no" from fresh data and the rules; the words of the reason are
  written by code (`must_say`), the SLM only writes around them. Agents never write to the database.
- Every write in `callverse/data/writes.py`, one transaction for cancel + refund + stock + log.
- **Real data first (CLAUDE.md rule 10):** the test messages and the 10 `cancel_order` examples are real tweets
  (TWCS, CC BY-NC-SA 4.0) chosen by the Brain and approved by Yassine. Do not edit their text.
- **Held-out set** `tests/data/decline_heldout_messages.json`: run **once**, at the very end, never used to fix anything.
  Locked M3 test sets: not opened. Never read `.env`. Tests: 0 API calls. Stop if free RAM < 300 MB.

## What to do
0. **Git.** `git fetch`, `git checkout main`, `git pull`. main must contain the **CLAUDE.md update** (merge of
   `chore/claude-md`, done by Yassine) — if not, stop and say so. Branch `feature/t14a-decline`. Commit first: this task
   file, `tasks/NEXT.md` (IN PROGRESS) and the Brain's files already on the PC, untracked and unchanged:
   `tests/dev/decline_practice_messages.json`, `tests/data/decline_heldout_messages.json`,
   `callverse/intake/data/cancel_order_examples_twcs.json`, `scripts/build_twcs_candidates.py`.

1. **Rule R-CAN-01** in `callverse/kb/policies_shopnova.json` (approved text):
   "An order can be cancelled while it is still being processed (not yet shipped). If it was paid, the full amount paid
   is refunded." Condition for `check_condition`: status is `processing`. Refunds above 300 TND keep going to finance
   (R-ESC-01). The rule-search index rebuilds (fingerprint); check that a cancel question finds R-CAN-01 in the top 2.

2. **Intake reason `cancel_order`** (ShopNova): add the 10 real examples from
   `cancel_order_examples_twcs.json` to `callverse/intake/data/reason_examples.json` under `cancel_order` (keep the
   tweet ids in the file's note). Route `cancel_order → B`; handover text "Your request is passed on for a cancellation
   check."; priority base like `refund_request`. Main-reason order: `[damaged_item, cancel_order, refund_request,
   return_item, late_delivery, order_status, other]` ("cancel and refund" = a cancellation). Thresholds and top-k stay
   (0.69, top-k 5). **Re-measure Intake on val only** (T24 `pc_check`): if ABCD has cancel subflows, relabel them
   `cancel_order` in `benchmarks/m3/data/abcd_mapping.json` for val (a label fix, not tuning; say which subflows); report
   macro-F1 before / after. Update the tests that pin the reason list.

3. **Cancel action.** New Agent B tool `propose_cancellation(order_id, user_quote)` (allow-list: ShopNova B only; it
   writes nothing). Agent B's ShopNova prompt gets one short line saying when to use it (no other prompt change).
   Coordinator check for a cancel proposal, on fresh data:
   - R-CAN-01: status must be `processing`; else → **decline** (step 4).
   - **Confirmation decided by code** (like Atlas T21): Intake main reason is `cancel_order` AND the agent's `user_quote`
     is found in the user's message AND that sentence is not negative ("do not / don't / never cancel" → ask the user
     instead: "Please confirm that you want to cancel order N.").
   - Refund amount = paid − refunded_total (0 for cash on delivery → cancel only, no refund row).
   - Amount > 300 TND → finance (queue mode: approval row + `layer3_pending`, as for refunds; stub mode: R-ESC-01).
   - Approved → `writes.cancel_order_by_user(order_id, proposal_id, amount)`: status `cancelled`, stock back, refund row
     (rule R-CAN-01) if amount > 0 — **one transaction**, all or nothing. The admin cancel (T18) stays as it is.
   - Words (code): "Your order N is now cancelled." + if refunded "Your refund of X TND is approved." (existing sentence).

4. **Decline decision (code).** When a ShopNova case ends **without a proposal**, the Coordinator re-reads the order
   and, by Intake's main reason, returns `outcome: "decline"` with `rule_id` + `facts` + `must_say` from this table
   (otherwise today's behaviour is unchanged):

   | Main reason | Condition (fresh data) | rule_id | must_say (code) |
   |---|---|---|---|
   | return_item | delivered and days_since_delivery > 14 | R-RET-01 | "Returns are possible within 14 days of delivery. Order N was delivered D days ago, so it can no longer be returned." |
   | refund_request | refunded_total ≥ paid (and paid > 0) | R-REF-05 | "Order N has already been fully refunded (X TND), so no further refund is possible." |
   | refund_request | not delivered and days_late ≤ 0 | R-REF-03 | "Order N is S and is not late: it is due by DATE. A refund for a late delivery is possible when an order is more than 5 days late." |
   | cancel_order | status not `processing` | R-CAN-01 | "Order N is already S, so it can no longer be cancelled. An order can be cancelled only while it is being processed." |
   | cancel_order | status `processing`, no proposal | — | ask: "Please confirm that you want to cancel order N." |

   A cancel **proposal** on a non-processing order gives the same R-CAN-01 decline (not a send-back). For R-CAN-01 on a
   shipped / delivered order, `next_step`: "Once it is delivered, you can return it within 14 days." The SLM gets the
   decline like any decision (must_say copied word for word; rule check unchanged); the template fallback says the same.
   Console / ticket: `decline` shows as Solved, with the rule id in the timeline.

5. **Practice runner.** Extend `scripts/run_live_check.py` (or a small new script) for the new sets: each message on a
   **fresh database**, sent as its `user_id` through the same path the app uses; checks: `outcome`, `rule_id`,
   `order_status` after, `refund_rows`, `refund_amount`, the decision's `must_say` present in the final reply, plus the
   global checks (0 crashes, 0 leaks, 0 wrong writes).

6. **Offline tests (0 API):** every decline row of the table; cancel processing paid / cash on delivery / > 300 TND
   (finance, using a processing order above 300 TND from the real sample or a test fixture) / shipped / negative
   sentence / quote not in the message; one-transaction rollback; allow-list (A has no cancel tool; Atlas unaffected);
   Intake reason list. All tests pass.

7. **Live run (PC restarted, Ollama running, B on Groq).** Quota guard first. **Practice set (12)**: fix only through
   code (CLAUDE.md fix rule), re-run at most twice. Then the **held-out set (12), once**. Report per message: outcome, rule,
   writes, reply, seconds, Groq tokens. Pass bar (held-out): **0 crashes, 0 leaks, 0 wrong writes, ≥ 10/12 correct**.
   Stop if Groq's daily limit answers (abort unscored, as T10b). Reseed both databases and delete `callverse.db` after.

8. **Docs:** `docs/decision_format.md` (decline outcome), `DATA_LICENCES.md` (TWCS, CC BY-NC-SA 4.0: test sets and
   Intake examples), README (CLAUDE.md rule 8).

## Checks (with numbers)
- R-CAN-01 found in top-2 for a cancel question; Intake val macro-F1 before / after (+ relabelled subflows); tests x/y;
  practice runs table; held-out table (x/12, crashes, leaks, wrong writes, avg / max s, Groq tokens); `git status` clean
  of `models/`, `data/raw/`, `.env`.
- One sentence: is it safe for the demo?

## Time box and stop rule
**2.5 h.** Stop and report if: the CLAUDE.md merge is missing, a test fails and cannot be fixed inside the task, Intake
val macro-F1 drops by more than 0.02, a held-out run would be needed twice, free RAM < 300 MB, or Groq's daily limit
answers. **If Yassine has to leave:** stop at a safe point, write `tasks/T14a_progress.md`, commit "T14a WIP: …" and push.

## Git (approved by Yassine, 2026-10-31)
Commit and push `feature/t14a-decline`. **No merge into `main`** (Yassine merges after the Brain's review). Write
`tasks/T14a_report.md` (In plain words · Done · Evidence · Problems · Questions for the Brain · Next step) and set
`tasks/NEXT.md` to WAITING FOR REVIEW. Last step: update the README (CLAUDE.md rule 8).
