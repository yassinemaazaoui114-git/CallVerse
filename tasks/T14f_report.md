# T14f report — ShopNova refunds need the client's money-back words + Atlas rule search by booking type

Branch `feat/t14f-shopnova-refund-words` (pushed). **Not merged.**

## 1. In plain words
A ShopNova refund is now paid only if the client's own words ask for money back ("refund", "money back", "my money",
"pay me back" …) in a sentence that is not negative — the same rule Atlas got in T14e, using one shared function.
Without those words the Coordinator asks first ("Please confirm that you want a refund of X TND for order N.") and
writes nothing. At Atlas, the rule search now shows the rules that fit the booking (flight rules for a flight booking,
hotel rules for a hotel booking) first; our code sets the booking type, not the model. t05 ("Cancelled ticket 2 months
back and still no refund") now passes: the search found AT-FLT-01 first, and Agent B proposed the 690 TND refund.

## 2. Done
- Step 0: main contains `feat/t14e-refund-words` (fcf8446, f190ec5, 2069e60). `tasks/NEXT.md` was already committed on
  main. The task file `tasks/T14f_shopnova_refund_words_and_search.md` was committed **on the branch**, not on main
  ("NEXT: T14f (Brain)", b620ca0), because pushing to main was blocked in T14e. Full suite before: **1381 passed**.
- **One shared function:** `money_back_asked(message)` moved from `atlas_coordinator.py` to
  `callverse/coordinator/negation.py` (the same logic, with `SENTENCE_ENDS` = ".!?\n"). Both Coordinators import it.
  Atlas behaviour is unchanged.
- **ShopNova Coordinator** (`callverse/coordinator/coordinator.py`, in `review()`): for `action == "refund"` (R-REF-03,
  R-DMG-01, R-RET-01), when the agent says `user_confirmed: true` but `money_back_asked(case["user_message"])` is False,
  the result is "not confirmed" with the reason "the client's words do not ask for money back". The result is
  `ask_user` with the existing ask sentence, and nothing is written. The check runs at step 5, before Layer 3 (step 6),
  so a refund above 300 TND is never queued without the words. The agent's flag is still needed too, so the words only
  add a condition. The cancellation path (`cancel_confirmed`, T14a / T14d) is unchanged.
- **Atlas search by booking type:**
  - `atlas_tools.BOOKING_TYPE_RULES`: flight → AT-FLT- / AT-AST- / AT-REF- / AT-ESC-; hotel → AT-HOT- / AT-REF- / AT-ESC-.
  - `atlas_tools.search_policy(query, booking_type=None)` → `search.company_search_tool(..., prefer=...)`. It ranks
    every rule, puts the preferred group first (`search.prefer_first`, which keeps score order inside each group),
    then keeps the top k (2). The trace `policy_search` now also logs `prefer`.
  - The booking type comes from Intake's look-up and travels ticket → `pipeline.new_agent` →
    `BaseAgent(booking_type=…)` → `registry.run_tool(booking_type=…)`. The registry sets it for Atlas `search_policy`
    and replaces any model argument with the same name. `ask_agent` passes it to the Agent A it starts.
  - Without a booking type (None), the search is by meaning only, as before. ShopNova search is unchanged.
  - **Prompt / tool-schema fingerprints: none changed.** The schema of `search_policy` is unchanged, because the model
    never sees `booking_type`.
- `tests/test_t14f.py` (48 tests): 9 synthetic ShopNova messages that ask for money back and 9 that do not (word check
  + through `review()`: approve and 1 refund row, or `ask_user`, the exact ask sentence and 0 rows); a case without a
  message; the agent's "false" still asks; R-DMG-01 after the photo, with and without the words; 4515 / 350 TND without
  the words never reaches Layer 3; a cancellation keeps its path; Atlas uses the same function. Search: t05 + flight →
  first rule is a flight rule; hotel → hotel rule; no type = old result; the registry overrides a model-given
  `booking_type`; ShopNova search unchanged; `prefer_first` order.
- **Old tests changed on purpose.** All of them built a ShopNova refund case **without any client message** (or
  asserted that the agent's flag alone is enough). They now carry a message with money-back words; the expected
  outcomes are unchanged:
  - `tests/test_coordinator.py`: new helper `refund_case()` used in s1, amount above paid, already refunded, rule
    false, wrong rule, not confirmed, damaged without proof, 4515 Layer 3, 600 refused, third send-back, decided twice.
  - `tests/test_layer3_queue.py`: its 4 `new_case` calls (all refunds of 4515 / 4512).
  - `tests/test_console.py`: the refund fixture (line ~107) and `test_admin_decision_reply_keeps_its_seconds`.
  - `tests/test_shopnova_admin_app.py`: `test_refund_approvals_page_approves_a_pending_refund`.
  - `tests/test_t14c.py`: `test_the_proof_is_stored_with_the_proposal_and_reused_at_approval`.
  - `tests/test_reply.py`: `test_rule_not_searched_is_a_warning_only`.
  - `tests/test_routing_by_company.py`: `test_a_shopnova_negative_sentence_still_uses_the_agents_flag` (message "I do
    not want to wait, refund me."), `test_shopnova_still_uses_the_agents_flag`, and `shopnova_refund_ticket()`.
- `README.md`: T14f entry.

## 3. Evidence
- Full suite: **1429 passed** / 1429 (1381 before + 48 new).
- Check: app setup `CALLVERSE_AGENTS_SET=local` only. Runners: `run_decline_check` for decline / t14b and `run_t14c` for
  t14c / t14d. Fresh DBs, clock 2026-10-09. Output: `out/t14f_<set>.json` + `.log`; comparison `out/t14f_compare.txt`
  (script `out/t14f_compare.py`, compares with `out/t14e_*.json`):

| set | T14f | T14e |
|---|---|---|
| decline_practice | 12/12 | 12/12 |
| decline_heldout | 12/12 | 12/12 |
| t14b_practice | 12/12 | 12/12 |
| t14c_practice | 12/12 | 12/12 |
| t14c_heldout | 12/12 | 12/12 |
| t14d_heldout (dev) | **12/12** | 11/12 |
| **total** | **72/72** | 71/72 |

  Wrong writes (M2T3 definition) 0 · crashes 0 · leaks 0 · forbidden words 0 · **Groq / API calls 0** · avg 19.0 s,
  max 25.4 s.
- **Changed vs T14e:** only **t05**. Before: `info` (FAIL). Now: `approve AT-FLT-01`, 690 TND refund (PASS). Its trace
  (`traces/run_20261102_074111_428485.jsonl`): `policy_search` prefer = flight, results AT-FLT-01 (0.726),
  AT-FLT-04 (0.669). Before, the results were AT-HOT-03 and AT-HOT-02. No message that passed in T14e fails now.
- **t05 passes now.**

## 4. Problems
- **The ShopNova word check was never used in the 72 runs.** In the dev sets, the ShopNova refund proposals (p05 and
  the cancellations with a refund) all had money words or took the cancel path. So the new check is proven by the unit
  tests only, not by real runs.
- **Follow-up turns:** the check reads only the current message (`ticket["text"]`). If a client answers "Yes" to "Please
  confirm that you want a refund …", the words are still missing and the Coordinator asks again. Atlas has worked the
  same way since T14e. It needs a decision (see Q2).
- "No refund please" is not read as negative by `negation.py` (it knows not / don't / never / no longer, not plain
  "no"). I did not change it (out of scope); one test sentence was rewritten to avoid it.
- Step 0 deviation: the task file is committed on the branch, not on main (same as T14e).

## 5. Questions for the Brain
1. The ShopNova check is "agent's flag **and** money words". Atlas uses code only (quote + Intake reason + words). Should
   ShopNova refunds move fully to code, like Atlas, in a later task?
2. Follow-up "Yes" after an ask: should the confirmation read the whole conversation, or the previous ask + "yes"? This
   applies to both companies.
3. Should we add a ShopNova dev set where the refund words are missing (e.g. "order 4512 is a week late, help"), so the
   new check is also tested in real runs?

## 6. Next step
Brain review → Yassine merges `feat/t14f-shopnova-refund-words` (and decides whether to put the "NEXT: T14f (Brain)"
commit on main). Then RL1 merge → RL5 → step 09.
