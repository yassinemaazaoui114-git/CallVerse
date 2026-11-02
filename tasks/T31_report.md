# T31 report — Held-out C/D: two fixes, then the single final run (+ T30 replay-row fix)

**Top line:** the held-out C/D file got exactly the two approved changes (D07 removed, C12 tightened). The single final
run gives **6/10** with `callverse-m2-v3` (Agent C 3/7, Agent D 3/3). All 4 failures are model errors by Agent C. In
each one the Coordinator sent the action back, or held it until the client says yes, so nothing wrong was written.
The replay fix is in: ratings training no longer writes `style_log` rows. Tests: **1877/1877** (T30 1876, +1).

**Note (T32):**
- **C12.** The official score stays **6/10**, because the case was fixed before the run. But a 3-day hold is legal under
  R-HLD-01 (max 3 days). C capped the client's 10 days at 3, so C12's tightened expectation was too strict (the
  Brain's mistake, approved by Yassine on 2 Nov). On a lenient reading the score is **7/10** (C 4/7).
- **Wrong proposals.** The bench line "Wrong proposals: 0" counted only cases that expect no action. The corrected line
  (T32 bench, re-summarised from the saved runs, no model call):
  `Wrong proposals: 3 (acted when it should not: 0, called a forbidden tool: 3 ['C09', 'C12', 'C14'])`.
  Nothing wrong was written: C09 and C14 were escalated by the Coordinator, and C12 waits for the client's yes.

## 1. In plain words
We kept 10 test cases for agents C (urgent help) and D (stock) hidden until the end, and ran them once today.
Agent D, which follows fixed rules, passed all 3. Agent C, the language model, passed 3 of 7. In 3 cases it proposed an
action it should not have proposed: a replacement for an order that is not late, a replacement for an item that is
out of stock, and a hold longer than allowed. In the 4th it forgot the order number when passing a client to a
colleague. The safety rules caught every case before anything happened. We also fixed a small bug: training on the
team's ratings was copying its practice rounds back into the ratings table, which would count them twice.

## 2. Done
- Branch `feat/t31-heldout-cd` from main `8976172`.
- Step 1: `tests/data/agents_heldout_cd.json`: case D07 removed; C12 `must_not_call` = `["propose_replacement",
  "propose_hold"]`. Own commit `6444e79` ("T31: held-out C/D, Brain fixes D07 and C12, approved by Yassine").
  `tests/dev/agents_cases.json` `about`: file name fixed (`agents_heldout.json` → `agents_heldout_cd.json`).
- Step 1b (replay fix, Q5): `scripts/train_style_policy.py`: with `--source ratings` the loop never writes
  `style_log` rows (same as `--no-log`). Docstring and `--no-log` help say so.
  New test `test_training_on_ratings_never_writes_style_log_rows` in `tests/test_t30_style_policy.py`: import a small
  synthetic ratings file (12 ratings), train twice with `--source ratings` → `real` rows stay 12, and no other rows.
- PC DB cleaned:
  - copy of the old DB kept in `out/t31_callverse_before_cleanup.db`;
  - `callverse/data/callverse.db` restored from `out/t30_dbbackup/callverse.db`;
  - ratings re-imported and the policy retrained.
- Step 3: the single final run, `out/t31_heldout_cd.json` / `.log`.
- README: one line (T31).

## 3. Evidence
- **Held-out file diff** (`git diff 8976172 -- tests/data/agents_heldout_cd.json`): D07 block removed (20 lines),
  `"propose_hold"` added to C12's `must_not_call`. Nothing else. 11 → 10 cases.
- **Replay fix:**
  - The new test fails without the fix (`assert 212 == 12`) and passes with it.
  - PC DB: after the restore `style_log` was empty. `python -m scripts.import_ratings out/CallVerse_reply_rating_filled.xlsx`
    → `483 of 483 ratings saved … Raters: Yassine 80, Dali 81, Semah 81, Mahmoud 81, Molka 81, Ayoub 79`.
  - `python -m scripts.train_style_policy --source ratings` → `[REAL] 300 rounds counted of 300`.
  - `style_log` now: **`real` = 483**, no other rows (was 783 before).
  - Best style per group: **identical to T30 report section 7** (13/13 groups, same n and the same means):
    warm_next_step in 11 groups, warm in 2 (atlas/ask/other, atlas/other/other).
- **Full suite: 1877/1877** (205.7 s).
- **Final held-out run, once:**
  `python -m scripts.eval_agents --file tests/data/agents_heldout_cd.json --model callverse-m2-v3 --heldout --out out/t31_heldout_cd.json`.
  It finished on the first try (no memory stop). Non-local model calls: none. Total time 208 s.

  | Case | Agent | What it tests | Result | Seconds | Coordinator outcome |
  |---|---|---|---|---|---|
  | C08 | C | wedding gift, replacement asked | PASS | 18.9 | ask_user |
  | C09 | C | order not late yet: no replacement | **FAIL** `wrong_tool` | 47.7 | escalate (2 send-backs) |
  | C10 | C | hold within the limit | PASS | 16.0 | ask_user |
  | C11 | C | dispute → colleague (R-AST-01) | **FAIL** `bad_args` | 16.1 | ask_user, handover B |
  | C12 | C | 10-day hold not allowed (R-HLD-01, max 3) | **FAIL** `wrong_tool` | 15.7 | ask_user |
  | C13 | C | (no tools needed) | PASS | 2.6 | – |
  | C14 | C | Smart Watch out of stock: no replacement | **FAIL** `wrong_tool` | 64.1 | escalate (2 send-backs) |
  | D05 | D | stock scan | PASS | 9.2 | owner_pending |
  | D06 | D | stock scan | PASS | 9.0 | owner_pending |
  | D08 | D | Bluetooth Speaker almost gone, warn order 4514 | PASS | 9.0 | owner_pending |
  | **Total** | | | **6/10** (C 3/7, D 3/3) | C avg 25.9, D avg 9.1 | |

- **Why each case failed** (all four: **model**, not rule or data):
  - **C09:** `get_order` was called, but C still proposed a replacement (R-RPL-01) 3 times for order 4510, which is not
    late (promised 2026-10-10). Its own answer says "late by 0 days". The Coordinator sent it back twice, then escalated.
  - **C11:** right action (`assistance`, R-AST-01), but `order_id` is `null`, so the scorer gives `bad_args`. This is the
    same mistake as dev case C06. The Coordinator asks the client first.
  - **C12:** C proposed a hold (`propose_hold` is now in `must_not_call`). The proposal has `hold_days: 3`, inside
    R-HLD-01, so the Coordinator asks the client (ask_user). C's text says "A hold of 10 days is proposed". That text
    is not sent: the SLM writes the reply from the decision. This is the case the Brain tightened (Q3).
  - **C14:** stock set to 0, `check_availability_with_d` was called, but C still proposed a replacement 3 times. The
    Coordinator sent it back twice, then escalated.
- **Nothing wrong was written.** The bench line "Wrong proposals (acted when it should not): 0" counts only cases with
  `expect.act = none`. Counted by `must_not_call`, 3 cases have a forbidden proposal (C09, C12, C14). Two were escalated
  by the Coordinator. The third (C12, a 3-day hold) waits for the client's yes.
- **Agent D:** 9 owner notes worded by the model, 0 by the template.
- **Held-out vs dev** (same model and bench; dev scores from T29, `out/t29_eval_agents.json`, not re-run):

  | Agent | Dev (`tests/dev/agents_cases.json`) | Held-out (this run) |
  |---|---|---|
  | C | 5/7 (C04, C06 `bad_args`) | **3/7** (C09, C12, C14 `wrong_tool`; C11 `bad_args`) |
  | D | 4/4 | 3/3 |
  | C + D | 9/11 (82 %) | 6/10 (60 %) |

  On dev data, Agent C's only failures were wrong details (`bad_args`). On held-out data it also proposes actions
  the facts do not allow (not late, out of stock, too long). The dev set had no "facts say no" case of that kind,
  so the dev score was too optimistic for C.
- The diff has nothing under `models/` or `data/raw/`, and no secrets.

## 4. Problems
- **Agent C ignores the facts it reads before proposing** (C09, C14). The safety comes only from the Coordinator.
  It works, but each case costs 2 send-backs and an escalation to a colleague (47–64 s).
- **C's answer text can say something the proposal does not** (C12: "10 days" in the text, 3 in the params). Only the
  decision reaches the client, so this is safe today. It would matter if C's text were ever shown.
- `bad_args` on assistance (`order_id` null) happens on dev (C06) and on held-out (C11): this is a steady model habit.
- The bench's "Wrong proposals" line does not count `must_not_call` breaks. The number 0 can mislead.
- Per rule 2, nothing was changed because of these results.

## 5. Questions for the Brain
1. **C12 meaning.** C proposed a hold capped at 3 days, which the rule allows. Under the new expectation this is a
   fail. Is "never propose a hold when the client asks for more than 3 days" the wanted behaviour, or should a capped
   3-day offer count as a pass? (The result stays as it is; this is only for reading the score.)
2. **Agent C next.** Possible next steps:
   - a small code guard that refuses `propose_replacement` when `get_order` says the order is not late, or when D
     says the stock is 0 (like the T29 "no later flight" check);
   - more dev cases of the "facts say no" kind;
   - a model change in `config.yaml`.
   Which one, if any? The held-out set is now spent, so any change needs a new held-out set to measure it.
3. Should the bench count `must_not_call` breaks in its "Wrong proposals" line?

## 6. Next step
Brain review. Then decide on Q2 and on turning the style policy ON for the demo (NEXT.md).

Merge line for Yassine (after the Brain's review): `git checkout main && git merge --no-ff origin/feat/t31-heldout-cd`
