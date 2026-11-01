# T14e report — An Atlas refund needs the client's own money-back words

Branch `feat/t14e-refund-words` (pushed). **Not merged.**

## 1. In plain words
Atlas used to pay a refund when the message was *about* a refund by meaning, even if the client never asked for money
(t02: "cancelled flight … no confirmation to the hotel. Help" got 690 TND). Now the Coordinator pays a refund only
when the client's own words ask for money back ("refund", "money back", "my money", "pay me back", "reimburse my
ticket", "chargeback") in a sentence that is not negative. Without those words it asks first ("Please confirm that you
want a refund of 690.00 TND for booking 7008.") and writes nothing. t05 ("still no refund") failed because of the model
(Agent B answered with text and made no proposal), not because of a rule, so no rule was changed for it.

## 2. Done
- Step 0: `tasks/NEXT.md` + `tasks/T14e_refund_needs_money_words.md` committed as "NEXT: T14e (Brain)" (5932b40),
  **but on the branch, not on main**: the push to `main` was blocked by the Claude Code permission check
  ("Modify Shared Resources"). Branch made from main 14c5f97 (= ff05d4a + NEXT DONE commit).
- `callverse/intake/request_words.py`: `MONEY_BACK_RE` + `asks_for_money_back(text)` (whole words: refund / refunds /
  refunded / refunding, not "refundable"; money back; my / our money; pay / paid / give / send (me|us|it) back;
  chargeback; something / anything back; `REIMBURSE_TICKET_RE` = reimburse + ticket / booking / flight).
- `callverse/coordinator/atlas_coordinator.py`: `confirmation()` — for action `refund` (ticket or hotel) also needs
  `money_back_asked(message)`: one sentence with money-back words that `negated_request` does not flag. Else
  reason "the client's words do not ask for money back" → `ask_user`, nothing written. `cancel_hotel` (T21) and
  `compensation` unchanged.
- `tests/test_t14e.py` (31 tests): 11 sentences that ask, 9 that do not; t02 → ask_user, 0 refund rows; 3 + 3 synthetic
  messages through `review()`; a negative money sentence; compensation and hotel cancellation keep their path; t05's
  sentence is money back and not negated.
- `tests/test_routing_by_company.py` changed on purpose: the fixture message `"Please: as the client wrote it."` (a
  placeholder without money words) is now `"… I want my money back."` (15 tests had failed on it).
- `CLAUDE.md`: the model lines replaced with the text of step 3 (nothing else).
- `README.md`: T14e entry.

## 3. Evidence
- Full suite: **1381 passed** / 1381 (1350 before + 31 new).
- Check (app setup: `CALLVERSE_AGENTS_SET=local` only, runners `run_decline_check` / `run_t14c`, fresh DBs, clock
  2026-10-09) → `out/t14e_<set>.json` + `.log`, comparison `out/t14e_compare.txt` (script `out/t14e_compare.py`):

| set | T14e | before (T14d D / T14d held-out) |
|---|---|---|
| decline_practice | 12/12 | 12/12 |
| decline_heldout | 12/12 | 12/12 |
| t14b_practice | 12/12 | 12/12 |
| t14c_practice | 12/12 | 12/12 |
| t14c_heldout | 12/12 | 12/12 |
| t14d_heldout (dev now) | **11/12** | 10/12 |
| **total** | **71/72** | 70/72 |

  Wrong writes (M2T3 definition) 0 · crashes 0 · leaks 0 · forbidden words 0 · **Groq / API calls 0** · avg 18.9 s, max 26.1 s.
- Changed vs before: only **t02**: `approve AT-FLT-01` (690 TND written) → `ask_user` ("Please confirm that you want a
  refund of 690.00 TND for booking 7008."), now PASS. No message that passed before fails now.
- **t05 cause** (trace `traces/run_20261101_233139_675095.jsonl`, same again in `run_20261102_002137_422952.jsonl`):
  Intake was right (main reason `refund_request`, 0.789, sentence "Cancelled ticket 2 months back and still no refund.",
  no negation). Agent B (`callverse-m2-v3`) called `search_policy` with the whole message, got only AT-HOT-03 / AT-HOT-02
  (hotel rules) for a flight booking, then gave a text answer ("not refundable … weather, AT-FLT-06", invented) with
  no proposal → Coordinator `info`. Not a rule bug (`negated_request` says False, `asks_for_money_back` says True,
  both now tested), so nothing fixed.

## 4. Problems
- Step 0 deviation: the task files are committed on the branch, not pushed to `main` (blocked, see above).
- "something / anything back" was added to the money words because the written practice message a08
  ("a different room … I want something back.", expects a 72 TND refund) would have turned into ask_user. It is a
  general phrase, but it was added because of that message. None of the 72 messages contain it (checked).
- t05 still fails: the model does not propose. Its `search_policy` query (the whole message) finds hotel rules for a
  flight booking.
- ShopNova (not changed, as asked): its refunds have **no code check of the client's words at all**. The ShopNova
  Coordinator trusts the agent's `user_confirmed` flag for a refund (`coordinator.py` ~line 448); only a cancellation
  is decided by code (`cancel_confirmed`). So a ShopNova refund rests on the model, not on Intake's meaning — a
  different, weaker path than Atlas.
- The ask sentence is the existing "Please confirm that you want a refund of X TND for booking N." (not the task's
  "Do you want a refund …?" wording), so the SLM checks and old tests stay as they are.

## 5. Questions for the Brain
1. Keep "something / anything back" as money words (a08), or change a08's expect to `ask_user`?
2. ShopNova refunds: give them the same code check (money-back words + quote) in a later task?
3. t05: worth a task on Agent B's policy search (e.g. add the booking type to the query, or let the Coordinator
   propose when Intake says refund_request and a flight rule holds)? Or leave it to the model?

## 6. Next step
Brain review → Yassine merges `feat/t14e-refund-words` (and decides whether to put the "NEXT: T14e (Brain)" commit on
main himself). Then RL1 merge → RL5 → step 09.
