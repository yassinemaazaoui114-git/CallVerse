# T14a report — STOPPED at the macro-F1 stop rule (live runs not done)

## 1. In plain words
The code for "say no with the reason" and for cancelling an order is built and tested without any API call.
The task says to stop if Intake's val macro-F1 drops by more than 0.02, and it dropped by 0.049, so I stopped before
the live runs. The practice set and the held-out set were **not run**: the held-out set is still unused.
The drop looks like a measuring effect, not damage: on the old labels the score went slightly up. The new class is
scored on ABCD messages that mostly say "remove an item from my order", which is not what the 10 real examples teach.
The Brain must decide whether that is acceptable before the live runs go ahead.

## 2. Done
- **Step 0:** branch `feature/t14a-decline`; the Brain's files committed unchanged.
- **Step 1:** rule R-CAN-01 (`status == 'processing'`), `cancel: [R-CAN-01]` in `allowed_rules`.
- **Step 2:** reason `cancel_order` (10 real examples, tweet ids in the note, route B, handover text, priority 0.5,
  main-reason order). `manage_cancel` relabelled in `abcd_mapping.json`; val rebuilt with `benchmarks.m3.build_data`.
  The Intake fallback prompt also got the new reason. `MONEY` in `benchmarks/m3/common.py` now includes `cancel_order`.
- **Step 3:** `propose_cancellation` (ShopNova B only, writes nothing), one prompt line, Coordinator check, confirmation by
  code, `writes.cancel_order_by_user` (one transaction: status, stock, refund, log row), finance path in stub and queue mode.
- **Step 4:** `no_proposal_decision` and `decline_words`; `decline` in the SLM guide, the template and the ticket status (Solved).
- **Step 6:** `tests/test_decline_cancel.py`; pinned tests updated (rule list, reasons, prompt and schema fingerprints,
  leave-one-out).

**Not done:** step 5 (practice runner), step 7 (live runs: practice and held-out), step 8 (`docs/decision_format.md`,
`DATA_LICENCES.md`). README not updated yet: there is no finished result to describe.

## 3. Evidence
Tests: **1107 passed / 1107** (0 API calls). R-CAN-01 in the top 2 for a cancel question: yes (offline test); rule search
top-2 on val 30/30.

ShopNova Intake, **val only** (locked test sets not opened):

| Measure | n | macro-F1 | Critical errors | Needs LLM |
|---|---|---:|---:|---:|
| Before T14a (old val) | 328 | 0.4108 | 26 | 40.6% |
| New system, old labels | 328 | **0.4157** | 37 | 38.1% |
| New system, new val (`pc_check`) | 344 | **0.3614** | 33 | 37.8% |
| Same, without the cancel keyword rule | 344 | 0.3508 | 33 | 37.8% |
| New val without the 16 cancel messages | 328 | 0.4222 | 33 | 38.7% |

- Drop: **−0.0494** on ShopNova. Average of both companies 0.6473 → 0.6226 (−0.0247). Atlas unchanged (0.8838).
- Relabelled subflow: `manage_cancel` only (16 val messages). `manage` was not relabelled: it is mostly shipping address.
- `cancel_order` on val: F1 0.065, recall 1/16. The other 15: 11 refund_request, 3 needs LLM, 1 return_item.
- Rebuilding val also resampled "other" (the pool changed), so the before and after sets are not identical.
- Leave-one-out at 0.69: 47 exact, 8 wrong, 15 needs LLM, of 70 (was 40, 5, 15, of 60).
- `git status`: nothing from `models/`, `data/raw/` or `.env`.

Live numbers: none (practice table, held-out table, seconds and Groq tokens were not measured).
Safe for the demo? **Not shown yet:** nothing has been tested live, so this branch should not be merged yet.

## 4. Problems
- **False cancels on val:** 14 old-val messages are now predicted `cancel_order` (critical errors 26 → 37, partly because
  `cancel_order` now counts as a money reason). The real tweets are broad. No write follows from this alone: B must propose
  and the client's quote must be in the message.
- **Changes the task did not list** (decided from the practice set's Intake scores and offline tests; please review):
  1. `CANCEL_WORD_RE` in `reasons.py`: a sentence with "cancel" / "cancle" / "cancelling" is `cancel_order`. Without it,
     "I want to cancel order 4510" and 5 of the practice cancel messages go to refund_request (partly because two AI-written
     refund examples mention cancelling). It runs before the threshold check, on ShopNova only.
  2. `refund_request` on an order delivered more than 14 days ago also declines with R-RET-01 (t02 is only refund_request).
  3. `R-REF-03` decline skipped for refunded / cancelled orders ("it is due by" would be false).
  4. A cancel proposal must be about the ticket's own order, else send-back.
  5. The negative check looks only around "cancel" (`NOT_CANCEL_RE`), narrower than Atlas's, so "didn't arrive, please
     cancel" still counts as a request.
- **Text split:** the table's two-sentence `must_say` is stored as two items, same words. As one item, the reply writer's
  echo filter deleted both sentences (a bug found by an offline test).
- **`next_step` on a delivered order:** the task's sentence "Once it is delivered, you can return it within 14 days."
  reads wrongly for an order that is already delivered. Implemented as written.
- **`decline` is a new value in the database CHECK:** every `shopnova.db` must be reseeded after the merge
  (`python -m callverse.data.seed`), or a declined proposal hits the old CHECK. Done on this PC. `atlas.db` shares the list:
  it needs no reseed today (no Atlas decline yet), but it gets the same CHECK on its next seed.
- **"Yes" after "Please confirm":** a bare "yes" on the next message has no cancel reason or order number, so it will not
  cancel. Not handled in this task.
- **Possible escalate instead of decline:** a refund proposal sent back that the agent then drops ends as "escalate", not as
  a decline. Not seen yet; the practice run would show it.
- `benchmarks/m3/results/pc_check.json` now holds the new numbers.

## 5. Questions for the Brain
1. **Accept the drop and continue?** My recommendation: yes. Judge Intake on the old labels (0.4157, no loss) and report
   `cancel_order` apart, because `manage_cancel` means "remove an item", which ShopNova's cancel does not do.
2. **Or keep `manage_cancel` as "other"?** The task said to relabel "if ABCD has cancel subflows", and I did, but its
   messages are a poor test for full-order cancellation.
3. Approve or remove the five changes listed in Problems, above all the keyword rule.
4. Should a delivered order get a different `next_step`, or none?

## 6. Next step
After the Brain's answer: step 5 (runner), step 7 (practice, then held-out once), step 8 (docs), README, final report.
