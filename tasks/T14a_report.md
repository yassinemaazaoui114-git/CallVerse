# T14a report — practice 12/12 with option A; held-out set still to run

# Follow-up 2 (option A) — latest state

**In plain words.** `cancel_order` now comes only from a sentence that says "cancel"; it never wins by meaning alone. Intake
then passed the stop rule, so I built the practice runner and ran the 12 practice messages live: all 12 were correct on the
first run, with no crash, no leak and no wrong write. No fix was needed. The docs are done. The held-out set was **not** run:
it runs once tomorrow on a fresh Groq quota, so T14a's pass bar is not proven yet.

| Check | Result |
|---|---|
| ShopNova macro-F1 on original val (328), limit >= 0.391 | **0.4117, pass** (0.4108 before T14a) |
| ShopNova critical errors, limit <= 29 | **26, pass** (26 before T14a) |
| Needs LLM | 40.6% (40.6% before T14a) |
| Val messages predicted `cancel_order` | **1**: abcd-3573 "I would like to cancel my shipping order" (labelled other, a true cancel request) |
| `cancel_order` on t07-t12, Intake | 6/6 |
| Rule search top-2 | 30/30; R-CAN-01 in the top 2 for a cancel question |
| Atlas macro-F1 | 0.8838, unchanged; average of both 0.6478 |
| Tests | **1122 passed / 1122** (0 API calls) |
| Practice run | **12/12, 0 crashes, 0 leaks, 0 wrong writes**, 0 fix re-runs, avg 13.3 s, max 25.1 s, 53,958 Groq tokens |

`pc_check.json`, the val set and the mapping are main's versions (restored after measuring).

**Practice run** (`python -m scripts.run_decline_check`, B on Groq, Intake fallback + Agent A local, stub finance; each
message on a fresh database as its `user_id` through `web_chat.send`; all replies came from the SLM, none from the template):

| Id | Case | Outcome | Rule | Writes | Order after | Seconds | Groq tokens |
|---|---|---|---|---|---:|---:|---:|
| t01 | return too late | decline | R-RET-01 | none | delivered | 10.6 | 7,535 |
| t02 | return too late | decline | R-RET-01 | none | delivered | 25.1 | 6,015 |
| t03 | already refunded | decline | R-REF-05 | none | refunded | 19.8 | 3,042 |
| t04 | already refunded | decline | R-REF-05 | none | refunded | 11.1 | 3,100 |
| t05 | refund, not late | decline | R-REF-03 | none | shipped | 20.6 | 4,789 |
| t06 | refund, not late | decline | R-REF-03 | none | shipped | 16.4 | 4,753 |
| t07 | cancel, paid | approve | R-CAN-01 | refund 54.40 | cancelled | 9.3 | 2,597 |
| t08 | cancel, paid | approve | R-CAN-01 | refund 54.40 | cancelled | 4.0 | 1,832 |
| t09 | cancel, cash on delivery | approve | R-CAN-01 | no refund | cancelled | 3.5 | 2,273 |
| t10 | cancel, shipped | decline | R-CAN-01 | none | shipped | 16.2 | 7,489 |
| t11 | cancel, shipped | decline | R-CAN-01 | none | shipped | 4.3 | 3,083 |
| t12 | cancel, shipped | decline | R-CAN-01 | none | shipped | 18.3 | 7,450 |

Replies, for example t10: "I'm sorry for the trouble. Order 4510 is already on its way, so it can no longer be cancelled. An
order can be cancelled only while it is being processed. Once it is delivered, you can return it within 14 days."
t07: "I'm sorry for the trouble. Your order 4511 is now cancelled. Your refund of 54.40 TND is approved."
All 12 replies: `out/decline_check_decline_practice_messages.json` (git-ignored).

**Done in this round:** option A in `reasons.py`; `scripts/run_decline_check.py` (new; a small script, because the app's path
needs a user id); `run_live_check.py` knows the new tool and the `status` fact; `docs/decision_format.md`, `DATA_LICENCES.md`
(TWCS), README; both databases reseeded. `callverse.db` did not exist, so there was nothing to delete: the runner uses its own
tickets file and removes it.

**Problems and limits**
- The practice set was used to choose the rules in this task, so 12/12 says less than the held-out result will.
- Practice ran in stub finance mode: the > 300 TND path is tested offline only, in both modes.
- A cancel request without the word (or the typo "cancle"), like "I don't want this order any more", no longer gets
  `cancel_order`. Accepted with option A.
- The Intake LLM fallback can still answer `cancel_order` when no sentence passes the threshold. That is not a win by meaning
  in the matcher, but it is a second way in. Not changed: option A was about the matcher.
- `leave_one_out` (report only) still scores `cancel_order` by meaning; the running system does not use it.
- A sent-back refund proposal the agent then drops would end as "escalate" (see below): not seen in this run.
- A bare "yes" after "Please confirm" stays out of scope (step 09).

**Safe for the demo?** The practice run says yes for these cases, but keep it off the demo until the held-out run passes.

**Next step.** Tomorrow, on a fresh quota: `python -m scripts.run_decline_check --file tests/data/decline_heldout_messages.json`
with `CALLVERSE_AGENTS_SET=local`, once. Pass bar: 0 crashes, 0 leaks, 0 wrong writes, >= 10/12. The runner reads the same
fields; any new `expect` key in that file would be ignored, so check the key names (not the texts) first.

Everything below is the earlier history, kept as it was. Option A replaces the "cancel word" change and answers the questions there.

# Follow-up 1 — critical errors failed

**In plain words.** The follow-up's code is done and all tests pass, but its stop rule failed: macro-F1 passes and critical
errors do not (37, limit 29). So the practice runner, the practice run and the docs were **not** done, as the follow-up
says. The held-out set is still unused. Narrowing the keyword rule could not help, because the false cancels do not come
from that rule: 13 of the 14 come from the embedding match, which fires on messages that never say "cancel".

| Follow-up item | State |
|---|---|
| 1. val + mapping restored to main; `pc_check.json` restored after re-measuring | done |
| 1. Rule: macro-F1 >= 0.391 | **pass, 0.4157** (328 messages; 0.4108 before T14a) |
| 1. Rule: critical errors <= 29 | **FAIL, 37** (26 before T14a) |
| 2. `CANCEL_WORD_RE` stays out of subscription / membership / prime / account / plan (`NOT_AN_ORDER_RE`) | done |
| 3. The other 4 changes kept | done |
| 4. R-CAN-01 `next_step` by status, 7 test cases (no proposal and proposal) | done |
| 5. Practice runner, practice run, docs, DATA_LICENCES, README | **not done: the rule failed** |
| Held-out set | not run |

Tests: **1119 passed / 1119** (0 API calls). Rule search top-2: 30/30. Atlas macro-F1 0.8838, unchanged. Average 0.6498.

**cancel_order on the 6 practice messages (t07-t12), Intake only:** 6/6 main reason `cancel_order`. Not a live result.

**Critical errors, 37:** other → refund_request 13, other → cancel_order 11, other → return_item 4, order_status →
cancel_order 2, order_status → refund_request 2, other → damaged_item 2, damaged_item → order_status 2, refund_request →
order_status 1. So 13 of the 37 are `cancel_order`.

**Val messages still predicted cancel_order: 14**

| Id | True label (subflow) | Message |
|---|---|---|
| abcd-3573 | other (manage) | I would like to cancel my shipping order |
| abcd-7362 | order_status (status_delivery_time) | hi, i am trying to check on the status for an order because the delivery time is wrong and i need to change it |
| abcd-2758 | other (status_quantity) | Can you please check an order for me. I ordered 1 but my e-mail confirmation states two? |
| abcd-4793 | other (promo_code_invalid) | I got a promo code a few days ago, but when I try to use it, it's telling me that it's invalid. |
| abcd-8317 | other (timing_4) | Yes i would like to know when the promo expires because i was thinking about buying some things |
| abcd-2362 | refund_request (mistimed_billing_already_returned) | Hi I have a question about my account. |
| abcd-4640 | order_status (status) | Hi, I made an order and I just looked at the order confirmation and the prices weren't right. |
| abcd-2453 | other (manage_change_name) | I have an issue with my account |
| abcd-9808 | other (shopping_cart) | I am trying to make a purchase but my cart doesn't seem to be updating |
| abcd-7941 | other (shopping_cart) | I'm trying to purchase an item, but the cart will not update when I add another item to it, |
| abcd-5190 | other (recover_username) | Hi Anne, I am trying to log into my account to check my order status but i have forgotten my username, can you |
| abcd-6170 | other (credit_card) | I want to buy something and my credit card keeps getting rejected |
| abcd-7704 | other (credit_card) | HI! I am trying to get something but my credit card keeps getting rejected. I only have one card. What to do? |
| abcd-651 | other (timing_4) | Hey there...i am shopping for myself and thinking of buying. But. I want to know when your promo codes expire |

Only abcd-3573 says "cancel", and it is a true cancel request despite its label. The other 13 are matched by meaning, against
the broad real tweets.

**What would pass (measured, NOT committed):**

| Option | macro-F1 | Critical | Needs LLM | Predicted cancel_order |
|---|---:|---:|---:|---:|
| Today | 0.4157 | 37 | 38.1% | 14 |
| A. `cancel_order` only for a message that says cancel (no win by meaning) | 0.4117 | **26** | 40.6% | 1 |
| B. Do not count `cancel_order` as a money reason | 0.4157 | **25** | 38.1% | 14 |

**Questions for the Brain**
1. Which way? My recommendation is **A**: it passes both limits and stops 13 false cancels reaching Agent B. Its cost is
   that a cancel request without the word (or the typo) "cancle" no longer gets this reason. The practice 6 all contain it,
   by Intake's scores above. The what-if tested the whole message; the real change would be per sentence. It is a small
   code change in `reasons.py`, but the 10 real examples would then only matter when the word is there.
   B only changes the count: the same 14 messages still go to Agent B, and `cancel_order` does route to B, so I do not advise it.
2. Once decided: runner, practice run, docs as listed in item 5. Held-out stays for tomorrow.

Everything below is the first stop's report, kept as it was, except: val, mapping and `pc_check.json` are now main's; the
delivered `next_step` question is closed by item 4; a bare "yes" is out of scope (step 09).

# First stop (before the follow-up)

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
