# T14f — ShopNova refunds need the user's money-back words + Atlas rule search by booking type (t05)

## Why
T14e (merged by Yassine) showed: (1) **ShopNova refunds have no code check of the user's words** — the Coordinator trusts the agent's
`user_confirmed` flag (`coordinator.py` ~line 448); only cancellations are decided by code. (2) **t05** ("Cancelled ticket 2 months back and
still no refund", Atlas 7008) failed because Agent B's `search_policy` found only hotel rules (AT-HOT-03/02) for a flight booking, so it
made no proposal. Approved by Yassine 2 Nov 00:32 (all ⭐: Q1 keep "something / anything back"; Q2 ShopNova check; Q3 booking type in search).
Fixes must be general rules (word lists, filters) with tests; all dev sets are seen material. Local runs (Dali's model is the default). No merge.

## Hard limits
Never read `.env`; no secrets; never commit `models/` / `data/raw/`; no force push / rebase / reset; **no merge into main**.
No change to thresholds, rule texts, Intake models. Prompt / tool-schema fingerprints may change only where step 2 needs it — list them.

## What to do
0. `git checkout main`, `git pull`. **Check that main contains `feat/t14e-refund-words`** (`git branch --contains` or `git log`); if not, stop and tell
   Yassine to merge it first. Commit `tasks/NEXT.md` + this file on main only if they are uncommitted there ("NEXT: T14f (Brain)") — if the push to
   main is blocked, commit them on the new branch instead and say so. Branch `feat/t14f-shopnova-refund-words`. Full suite first (expect 1381).
1. **ShopNova refund = money-back words** (same as Atlas in T14e): in the ShopNova Coordinator, a refund (any rule: R-REF-03 late, R-DMG-01 after
   proof, R-RET-01 return …) is confirmed only if `request_words.asks_for_money_back(message)` finds a non-negated money-back sentence (reuse T14e's
   `money_back_asked` logic — one shared function for both companies, not a copy). Else `ask_user` ("Please confirm that you want a refund of X TND
   for order N."), nothing written. Cancellation (R-CAN-01, refund included in the cancel) keeps its own T14a/T14d path. Layer 3 (> threshold) unchanged:
   the check runs before the proposal is queued. Tests: ≥ 8 synthetic ShopNova sentences each way + the old ShopNova refund tests (update on purpose
   only where a message had no money words; list them).
2. **Atlas rule search by booking type:** when Agent B (or any agent) calls `search_policy` for an Atlas ticket that names a booking, results of the
   booking's type come first: flight → AT-FLT-*, AT-AST-*, AT-REF-*, AT-ESC-*; hotel → AT-HOT-*, AT-REF-*, AT-ESC-*. Do it in code (filter / re-rank
   inside the tool using the ticket's booking type), not by asking the model. ShopNova search unchanged. Tests: a flight booking + "still no refund" →
   first result is a flight rule; a hotel booking → hotel rule.
3. **Check** (local, app setup `CALLVERSE_AGENTS_SET=local`): the 72 dev messages (same files + runners as T14e). Report per set, totals, wrong
   writes (M2T3 definition), crashes, leaks, Groq calls, and **every message whose result changed** vs `out/t14e_*.json`. Bar: 0 wrong writes,
   0 crashes / leaks, no message that passed in T14e now fails. Say whether t05 passes now.
4. Full suite green. Commit, push `feat/t14f-shopnova-refund-words`. **No merge.** Write `tasks/T14f_report.md` (In plain words · Numbers · Problems ·
   Questions for the Brain · Next step), copy to `out/T14f_report.md`, set `tasks/NEXT.md` to WAITING FOR REVIEW. Commit, push.

## Time box
2 h (72 local runs ≈ 25 min). WIP stop allowed.
