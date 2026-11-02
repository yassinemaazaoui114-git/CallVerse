# T29 — Small follow-ups: money-back words, "no later flight" check (F6), eval bench fix

## Why
Yassine asked (2 Nov, 13:32) to use the remaining time and usage on what is left. Everything required except RL5 is merged (main 9feca1b, T28). RL5 waits for the team's real ratings.
These are the small items the T26–T28 reviews left open. Each is small and testable. No new architecture.

## Hard limits
- Branch `feat/t29-polish` from main (9feca1b or later). Claude Code never merges into main (CLAUDE.md rule 11). No secrets; never read or print `.env`. No force push.
- Main's safety must survive: money-back words, negation check, decline by code, proof flag, hidden fields, Coordinator rules, Layer 3 queue, T28's pending-question and one-decision rules. Never weaken a check to make a test pass.
- Do not tune on held-out files (`tests/data/*heldout*`); run them only for the final regression, once. New examples are Claude-written drafts (name the file/test "draft").
- Fix rule: a failure is fixed in code (a check, a default, a structure), never by a prompt trick for one model.
- Do not run `scripts/reset_demo.ps1` or the Reset shortcut. Back up the DBs before runs that re-seed them (as in T28: `out/t28_dbbackup/`), and put them back after.

## What to do
0. Create the branch. Commit this file + NEXT.md. Write `tasks/T29_progress.md` and update it after every step (WIP protocol).
1. **Money-back words.** In `request_words.py` (`asks_for_money_back`): the phrases "money returned (to me)", "returned to me" (only with money / payment / amount nearby), "reimbursed / reimbursement" (for the user's money), "paid back", "get my money", "money refunded" must count as asking for money back. Keep the negation check working ("I do not want to be reimbursed"). It must NOT count: "return the item", "returned my order" (no money word), "I have not been refunded yet" stays what T14f/T28 decided. Add at least 20 new tests: 12 positives, 8 negatives/near misses, incl. the T28 live message "Order 4512 is late and I need it tomorrow for a birthday. If it can't arrive in time, I'd rather have the money returned to me." (now a money-back request) and a bare "yes" after it (one refund written, double "yes" = one write). Both ShopNova and Atlas paths.
2. **F6: Agent C must not invent a flight.** In Atlas Agent C's tool step (`callverse/tools/atlas_c_tools.py` and/or `callverse/agents/agent_c.py`): when `find_alternative_flights` returns no flight, C must not propose a rebooking by itself; by code it hands the case to a human colleague (the existing special-help handover) with the reason "no later flight on this route" and the user gets one fixed, clear sentence. Test: booking 7005 on the real data → no `propose_rebooking`, a colleague handover, 0 rebooking rows; a booking that HAS a later flight still gets C's offer (positive control).
3. **Eval bench fix.** `scripts/eval_agents.py`: apply the fake data overrides inside the `ask_agent` results too (B02's "3 days late" never reached merged Agent B), so the bench measures the same thing the pipeline does. Re-run P20's 26 cases with `callverse-m2-v3` once (local). Report the table. Bar: >= 22/26 and the number of wrong proposals (B06: refund 89.00 on cash-on-delivery order 4514, nothing paid, is the known one). Add a code-side check at the tool/proposal step: a refund proposal for an order with nothing paid (cash on delivery, not delivered, no payment) is refused by code with a clear reason, not only by the Coordinator. Test with order 4514.
4. **Rule wording (optional, only if steps 1–3 are done and time remains):** in P20's 7 rule texts (R-RPL-01, R-HLD-01, R-AST-01, R-STK-01, R-PRM-01, AT-CAP-01, AT-DEAL-01) change "client(s)" to "user(s)". Update the policy tests/fingerprints that pin the text; list each changed hash in the report. If this breaks more than text pins, revert this step and say so.
5. **Regression:** full suite green; the 72-message set once as in T28 (`run_decline_check` + `run_t14c`; bar >= 70/72, 0 wrong writes, 0 leaks; T28 had 72/72). If a message flips, say which and why.
6. **Docs:** `docs/DEMO_RUNBOOK.md` (F6 now ends in a clear "no later flight, a colleague will contact you" answer; money-back words list), README line. Report `out/T29_report.md` and a copy at `tasks/T29_report.md` (commit it): top line, test counts, regression table, the 26-case table, what is left, questions for the Brain.

## Checks (all reported)
Full suite green (>= 1811 + new). Regression bar met. 0 wrong writes. Step 1: 12 positives pass, 8 negatives stay negative. Step 2: 7005 → colleague handover, no rebooking, positive control OK. Step 3: 26-case table + 4514 refund refused by code. Nothing under `models/`, `data/raw/`, or secrets in the diff.

## Time box and WIP protocol
2 hours. Commit a WIP after each step and keep `tasks/T29_progress.md` current; if the session stops, the next one reads it. Priority: 1, 2, 3, 5, 6, then 4. Push the branch. Close other apps before the model runs (7.7 GB RAM).

## Git
Branch `feat/t29-polish` from main; push; the report lists the merge line for Yassine (the Brain reviews first). Update the README at the end (CLAUDE.md rule 8).
