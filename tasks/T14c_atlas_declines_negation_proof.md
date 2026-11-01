# T14c — Atlas declines by code, smarter negative check, R-DMG-01 proof flag, p07 + damaged-item fixes

Approved by Yassine 2026-11-01 11:34 (all ⭐ on items 1–8). Model: **Sonnet 5.5**, new conversation. Time box **3.5 h over two days**
(stop at a clean WIP commit between). Offline coding can start now; live runs (items 4 and 8) need a fresh Groq quota (~200k tokens/day).

## Why
T14b left open: Atlas has no "decline by code" (ShopNova has it), "I'm *not* able to cancel" is read as a negation (h08 miss),
a damaged item gets a R-RET-01 decline instead of a photo request (p08), >300 TND damaged proof is lost between proposal and
approval, and Agent B skipped `propose_refund` on p07 in 2/2 full runs. The reply writer is fixed (T14b); this is the decision side.

## Hard limits
- Security as always: never read `.env`, no secrets in files, no force push/rebase/reset/branch deletion, **no merge into main**
  (Yassine merges). Agents only propose; the Coordinator executes. No change to thresholds, rule texts or Intake models (pinned).
- Held-out file `tests/data/t14c_heldout_messages.json`: **do not open, print or grep it until step 8**. Run it ONCE at the end,
  never fix anything after it (rule 9). Real tweets stay in the two JSON files only; report holds ids + counts, no tweet texts in commits beyond those files.
- Do **not** switch on `pipeline.proposal_claim_retry`. Keep the `ask_agent` "source: get_tracking" label as it is.
- Pinned prompt fingerprints may change only where an item below says so; renew them on purpose and list them in the report.

## What to do (the 8 approved items)
0. `git checkout main && git pull`, branch `feat/t14c-atlas-declines`. Run the full test suite first (expect 1176 pass).
1. **Atlas declines by code**, same design as ShopNova (Coordinator decides, rule_id + facts + must_say; agents cannot invent a decline).
   Cases (check in this order, first match wins; add to `atlas_coordinator.py`):
   - departure delay < 3 h, or on time → `AT-FLT-03` decline (compensation)
   - extraordinary cause (weather / air system / security) → `AT-FLT-06` decline
   - cancelled with ≥ 14 days notice → `AT-FLT-02` decline
   - delay < 5 h, not cancelled, and the user asks for a refund → `AT-FLT-04` decline
   - hotel non-refundable → `AT-HOT-03`; refundable deposit and cancelled < 2 days before arrival → `AT-HOT-02`; no-show → `AT-HOT-05`
   - already fully refunded → `AT-REF-01`; hotel with no deposit → `AT-HOT-01` (nothing to refund)
   Rule texts are read from `policies_atlas.json` — check each rule's real condition there before coding; if a case above does not match
   the rule text, **stop and tell the Brain**. Atlas writer prompt gets a decline guide like ShopNova's (renew fingerprints on purpose).
   Compensation and refunds above the finance limit (AT-ESC-01) stay as they are (layer3_pending).
2. **Smarter negative check** (shared by both companies, one function, offline tests on the practice tweets only):
   - request to cancel (NOT a negation): "not getting the cancel option", "can't/cannot/unable to/not able to cancel", "how do I cancel", "tried to cancel", "problems cancelling"
   - true negation → ask first, no write: "do not / don't / never / no longer / not want … cancel|refund|return", "should be rerouted NOT refunded"
   - add unit tests with ≥ 8 synthetic sentences + the practice tweets s03, s04, s05, a05 (from the JSON).
3. **R-DMG-01 proof flag (> 300 TND)**: store `proof_received` with the proposal and reuse it at approval; admin console shows "photo proof received".
   Small schema change → write it as a migration-safe default (False); tell the Brain which files changed (Dali's UI reads this).
4. **p07 ×3 before/after** (uses `tests/dev/t14b_practice_messages.json` p07, ShopNova order 4515):
   run p07 3 times on current code → hide `ai_generated` / `scripted` fields from agents' tool results (registry.py, same pattern as T14b) → run p07 3 times again.
   Report 3 vs 3: did Agent B call `propose_refund`? (~45k Groq tokens — stop if quota error, report, continue offline items.)
5. **Damaged item asks for a photo (R-DMG-01), not R-RET-01 decline.** First print what Intake scored for p08 (t14b practice) and s01/s02 here
   (reason + scores, no change). If the reason is not `damaged_item`, add a code check on whole words damaged|broken|cracked|smashed|defective|destroyed
   (like the cancel word in T14b); it must not fire on negations ("not damaged"). Expected: outcome `ask_proof`, 0 refund rows.
6. **Off-topic**: fixed text, no SLM call, for both companies (ShopNova already has an own template — extend to Atlas, same wording style; no order/booking facts).
7. Test files (already written by the Brain, do not edit): `tests/dev/t14c_practice_messages.json` (12) and `tests/data/t14c_heldout_messages.json` (12).
   Format: `id, company, user_id, order_id|booking_id, text, expect` (+ `brain_written: true` on 3 hotel messages: a07, h06, h07; no real hotel tweet exists in our candidates).
   `expect` keys: `outcome` (decline | approve | ask_proof | layer3_pending), `rule_id`, `refund_rows`, `compensation_rows`, `order_status`, `booking_status_after`, `approvals_pending`, `approval_amount`, `refund_amount`.
   Missing key = not checked. Write the runner `scripts/run_t14c.py` by copying the T14b runner pattern (fresh seeded DB per message, clock 2026-10-09, same leak check).
8. **Pass bar** (like T14a/T14b): practice — 0 crashes, 0 leaks (card/cash/city/payment/source), 0 wrong writes, 0 forbidden words ("days late"/"0 days"/"late by" where the decision is not lateness),
   decisions match `expect` on ≥ 11/12. **Held-out: run once, at the end, on fresh quota, ≥ 10/12** with the same 0-crash/0-leak/0-wrong-write rules.
   Report any miss honestly; do not tune after the held-out run.

## Checks the Brain will look at
- Decline decisions come from code (rule_id in the trace), not from the writer; the writer only phrases `must_say`.
- Full suite green; new tests for items 1, 2, 3, 5, 6; no pinned-fingerprint change outside Atlas writer prompt / the hidden-fields change.
- p07 3 vs 3 table; held-out table (id, expected, got, pass).

## Git
Commit in small steps on the branch, push, **no merge**. Update `tasks/NEXT.md` status to WAITING FOR REVIEW at the end (it is READY now).
Write `tasks/T14c_report.md`. Report format: In plain words · Numbers · Problems · Questions for the Brain · Next step.
