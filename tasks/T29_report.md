# T29 report — money-back words, "no later flight" check (F6), eval bench fix

**Top line:** steps 1, 2, 3, 5 and 6 are done; step 4 (optional wording) is skipped. pytest 1848/1848 (+37 new).
72-message regression 72/72, 0 wrong writes, 0 leaks. Bench: 22/26 with 1 wrong proposal (B02, a model error; the
Coordinator re-reads the real data). Branch `feat/t29-polish`, pushed.

## 1. In plain words
More ways of asking for money back now count, for example "I'd rather have the money returned to me" or "I want to
be reimbursed". Saying them in the negative ("I do not want to be reimbursed") still counts for nothing.
At Atlas, when no later flight exists on the route, Agent C can no longer offer one. The code passes the case to a
colleague, and the user gets one clear sentence.
Agent B can no longer propose a refund for an order nobody paid for (order 4514, cash on delivery). The tool step
refuses it, so this no longer depends on the Coordinator alone.
The test bench now gives Agent B the same fake facts the pipeline would give it.

## 2. Done
- **Step 1, money-back words** (`callverse/intake/request_words.py`):
  - New words: "reimburse / reimbursed / reimbursement", "money / payment / amount / funds / cash + returned /
    refunded / reimbursed / repaid", "repay me".
  - "returned to me" counts only with a money word within 6 words (before or after).
  - "reimbursable" and "non-reimbursable" are removed before the check, because they describe a fare and ask for
    nothing.
  - "paid back" and "get my money" already counted before T29.
  - The negation check (`callverse/coordinator/negation.py`, ACTION) now knows "(be) reimbursed" and "(be) paid back".
  - At Atlas, a bare "reimbursement" next to hotel costs stays a compensation question (T14d h03, unchanged). The
    reason: the Atlas Coordinator checks `asks_for_expenses` first.
  - Tests: `tests/test_t29_money_words.py`, 30 tests. All are Claude-written drafts.
- **Step 2, F6** (Atlas Agent C):
  - `atlas_c_tools.propose_rebooking` is refused by code when the route has no later flight.
  - `AgentC.run` marks `no_later_flight` when `find_alternative_flights` returns an empty list.
  - `pipeline.run_c` then returns `atlas_special.no_later_flight_decision`. That decision is escalate (ticket
    "Escalated", a human colleague), with reason "no later flight on this route", one fixed `must_say` sentence, and
    no write.
  - The Atlas C prompt line now says "a colleague will contact the client" instead of "the refund can be checked".
    This keeps the prompt consistent with the code; the fix itself is in code.
  - Tests: `tests/test_t29_no_later_flight.py`, 3 tests.
- **Step 3, bench and unpaid refund:**
  - `scripts/eval_agents.py` (`override_facts`) puts a case's fake fields into `ask_agent`'s `facts` too.
  - New `proposal_tools.nothing_paid`: a refund proposal for an order with `paid` 0 is refused at the tool step, with
    the reason "nothing was paid for order 4514 … do not propose a refund". The Coordinator still checks it too.
  - Tests: `tests/test_t29_bench_and_unpaid.py`, 4 tests.
- **Step 6:** `docs/DEMO_RUNBOOK.md` (new F6 answer, the money-back word list, the unpaid-refund check) and a README
  line.

## 3. Evidence
- **pytest:** 1848/1848 (main had 1811; +30 +3 +4).
- **Step 1:** 12 positives pass, 9 negatives / near misses stay negative.
  - The T28 live message P5 is now a money-back request. A "yes" after it writes one refund of 59.90; a second
    "yes" writes nothing more (`test_t28_live_message_then_yes_writes_one_refund`).
  - The Atlas Coordinator path is tested with "money returned to me", "reimbursed for booking 7008" and "paid back",
    plus the negative "I do not want to be reimbursed".
- **Step 2:** booking 7005 on the real seed data:
  - Result: no proposal accepted, outcome `escalate`, reason "no later flight on this route", 0 rebooking rows, and
    the booking still has flight 7005.
  - Reply sentence: "There is no later flight on this route for your booking 7005, so a colleague will contact you
    about your options."
  - Positive control: with an added later flight 9901, C proposes 9901 → `ask_user`.
- **Step 3, 26 cases, `callverse-m2-v3`, local** (`out/t29_eval_agents.json` / `.log`, 0 non-local calls):

| Agent | Pass | T26 had | Fails |
|---|---|---|---|
| A | 8/8 | 8/8 | |
| B | 5/7 | 5/7 | B02 `wrong_tool, acted_wrongly`; B06 `wrong_tool` (tried, refused by code) |
| C | 5/7 | 5/7 | C04, C06 `bad_args` (as in T26) |
| D | 4/4 | 4/4 | |
| **Total** | **22/26** (bar ≥ 22: met) | 22/26 | |

  - Wrong proposals: **1** (T26: 2).
  - B06 now has 0 proposals and 0 send-backs. B called `propose_refund` once, the tool refused it, and B answered
    "nothing was paid for it". In T26 it proposed 89.00 three times and the Coordinator escalated.
  - B02: the fake "3 days late" now reaches B (its answer says "Order 4512 is 3 days late"). B still proposed 59.90
    under R-REF-03, which needs more than 5 days. This is a model error, not a bench artifact. The Coordinator
    re-reads the real data (6 days late) and approves, so nothing wrong is written in the pipeline.
- **Step 5, 72-message set** (`out/t29_compare.txt`, same runners as T28, local models): **72/72**, wrong_writes 0,
  crashes 0, leaks 0, API calls 0, avg 19.0 s, max 26.0 s.
  - decline_practice 12, decline_heldout 12, t14b 12, t14c_practice 12, t14c_heldout 12, t14d_heldout 12.
  - The only change against T28's run: a05 went `not_your_order` → `ask_user AT-FLT-01`. This is T28's own
    year-not-an-id fix (T28's 72 run was made before that fix; its re-run showed the same `ask_user`).
  - The held-out files were run once, not tuned on.
  - The DBs were backed up to `out/t29_dbbackup/` and put back after the runs (byte-identical, checked with `cmp`).
- The diff has nothing under `models/` or `data/raw/`, and no secrets.

## 4. Problems
- B02 stays a model error: B reads "3 days late" and still proposes under R-REF-03. The Coordinator protects the
  pipeline, but the bench counts the case.
- F6's fixed sentence goes through the SLM as `must_say`. The SLM writes around it, and the sentence itself is
  checked to be present. The sentence is not sent as a fixed text with no SLM call, the way the off-topic redirect is.
- The F6 handover triggers only when C actually called `find_alternative_flights`. If C makes no tool call at all,
  nothing new happens (C makes no offer anyway, and the old path stays).
- "returned to me" with a money word in the next sentence does not count, because the check reads one sentence at a
  time.
- **Step 4 skipped:** changing "client" to "user" in the 7 P20 rule texts changes the texts that rule search embeds.
  The 72-message regression would then no longer cover the code that is merged. I left it for a separate task, with
  its own regression run.

## 5. Questions for the Brain
1. F6: is "escalate" (ticket Escalated, a human colleague) the right handover? Or should it be a recorded R-AST-01-style
   assistance request at Atlas? Atlas has no colleague-request tool today; ShopNova has one.
2. Should the F6 sentence skip the SLM completely (a fixed text, like the off-topic redirect)?
3. Step 4: run it as its own small task with a regression run, or drop it?
4. Atlas: should a bare "I want to be reimbursed" (no hotel / ticket word) count as a refund rather than a cost
   around the trip? Today it is a cost around the trip (T14d rule kept).

## 6. Next step
The Brain reviews `feat/t29-polish`. After that, Yassine merges:
`git checkout main && git pull && git merge --no-ff feat/t29-polish && git push`
Then RL5, when the team's ratings arrive.
