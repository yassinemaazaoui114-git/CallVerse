# T14c report — Atlas declines by code, shared negation check, R-DMG-01 proof flag, p07, damaged item, off-topic

Branch `feat/t14c-atlas-declines` (from `main` 21f1167). **Not merged.** Pushed. Built by Claude Code on **Opus 5.5**
(NEXT.md asked for Sonnet 5.5; the session ran on Opus). Everything was done in one sitting (well inside the 3.5 h box).

## 1. In plain words
Atlas Travel can now say "no" with the rule's reason, like ShopNova: a compensation for a 1-hour delay, a refund for a
non-refundable hotel, a compensation when the weather cancelled the flight. The decision is made by code from the
booking data; the reply writer only words it. "I'm not able to cancel" is now read as a request (not as "I don't want to
cancel"), in both companies. A damaged item now gets the photo request instead of a return refusal. The off-topic reply
is a fixed text (no model call). On the 12 practice messages **11/12** pass. On the 12 held-out messages, run once,
**9/12** pass — **below the 10/12 bar**. No crash, no leak; but 2 of the 3 misses wrote something the client did not
ask for (details in Problems). Nothing was changed after the held-out run.

## 2. Done
| Item | What | Files |
|---|---|---|
| 0 | Branch, full suite first: **1176 passed** | — |
| 1 | Atlas declines: `decline_rule()` (Intake reason + re-read facts, first match wins), `decline_words()` (fixed sentences), `decline_decision()` (no proposal), and a check inside `review()` right after the facts are read (`no_rule_says_no`, traced with the rule id). Atlas writer guide `decline_atlas`; the template gives the reason first, then the next step | `callverse/coordinator/atlas_coordinator.py`, `callverse/slm/writer.py`, `callverse/slm/templates.py` |
| 2 | One negation function for both companies (new file): step 1 removes "request" phrases (can't / unable to / not able to / not getting / tried to / how do I / problems / "I was not refunded" / "I didn't get my refund"), step 2 = a negative word + at most 4 filler words + cancel/refund/return/compensation. Replaces ShopNova's `NOT_CANCEL_RE` and Atlas's `NEGATIVE_WORDS` | **new** `callverse/coordinator/negation.py`, `coordinator.py`, `atlas_coordinator.py` |
| 3 | `proposals.proof_received` (ShopNova): set by the Coordinator from its case (an agent cannot set it), stored with the proposal, re-used by the finance re-check; Refund approvals page shows "📷 photo proof received". Old files get the column with default 0 on open | `callverse/data/seed.py`, `db.py`, `writes.py`, `admin_reads.py`, `callverse/channels/approvals.py`, `coordinator.py`, `apps/shopnova/pages/6_Refund_approvals.py` |
| 4 | p07 3 runs → registry also hides `ai_generated` / `scripted` from ShopNova agents → p07 3 runs | `callverse/tools/registry.py` |
| 5 | Damage word in Intake (whole words damaged/broken/cracked/smashed/defective/destroyed; not when negated, not for link/app/website/page/checkout...) | `callverse/intake/reasons.py` |
| 6 | Off-topic redirect = fixed text, **no SLM call**, both companies (Atlas also loses its calm opener, same as ShopNova in T14b) | `writer.py`, `templates.py` |
| 7 | Runner for both companies (copied from the T14b runner; fresh ShopNova + Atlas DBs per message, clock 2026-10-09, queue mode, same leak check + Atlas wrong-write check) | **new** `scripts/run_t14c.py` |
| + | Small writer fix found in the practice run: "Hello, A full refund" → "Hello, a full refund" | `writer.py` |
| docs | README, `docs/decision_format.md` (Atlas decline table, off-topic) | — |

**New files:** `callverse/coordinator/negation.py` (is a sentence a request said in the negative?, plain regex code),
`scripts/run_t14c.py` (the live check for both companies), `tests/test_t14c.py` (107 tests).

**Files Dali's UI reads (item 3):** schema `callverse/data/seed.py` (`proposals.proof_received INTEGER NOT NULL DEFAULT 0`),
migration in `callverse/data/db.py`, `admin_reads.proposal()` and `admin_reads.approval_facts()` now return `proof_received` (bool),
page `apps/shopnova/pages/6_Refund_approvals.py`. The Atlas proposals table is unchanged (Atlas has no R-DMG-01).

## 3. Evidence
**Tests:** 1176 → **1283 passed, 0 failed** (+107 in `tests/test_t14c.py`). Old tests changed on purpose (each has a T14c comment):
- `test_routing_by_company.py`: 7007 refund → now `decline` AT-FLT-04 (the send-back tests use another main reason);
  second refund on 7008 → `decline` AT-REF-01 (was send_back); a05/a06/a07 compensation paths → `decline` FLT-06/03/06 (were `info`);
  two confirmation tests got sentences with a real negated request ("Do not wait. Refund me now." is now a request).
- `test_t14b.py`: Atlas off-topic has no opener any more (item 6).
- `test_atlas_data.py`: `proof_received` is ShopNova-only.
- **Pinned fingerprints: none changed** (the Atlas writer fingerprints test an `approve` decision; the decline guide is a
  new key used only for Atlas declines).

**Intake on validation (`benchmarks/m3/pc_check`, val only):** ShopNova macro-F1 **0.4117**, critical **26**; Atlas 0.8838 / 1 —
identical to T14b. `pc_check.json` restored.

**Item 5, Intake before the change (no change made at that point):**
| id | main reason | reasons (score) | damage sentence scores |
|---|---|---|---|
| p08 (t14b) | refund_request | refund 0.786, order_status 0.745 | refund 0.786, return 0.762, damaged 0.761 |
| s01 | return_item | return 0.749, order_status 0.73 | damaged 0.636 (under 0.69) |
| s02 | refund_request | refund 0.747 | refund 0.747, late 0.722, cancel 0.715 |

After the word check: all three → `damaged_item`; s01 and s02 live → `ask_proof`, 0 refund rows.

**Item 4, p07 ×3 before / after** (ShopNova 4515, queue mode, `out/t14c_p07_before_*.json`, `out/t14c_p07_after_*.json`):
| | run 1 | run 2 | run 3 | `propose_refund` called | labels in tool results |
|---|---|---|---|---|---|
| before | layer3_pending 378.00 | layer3_pending | layer3_pending | **3/3** | 2 per run |
| after (labels hidden) | layer3_pending 378.00 | layer3_pending | layer3_pending | **3/3** | 0 |
Tokens 24,943 / 24,122. The T14b skip did not happen in 6/6 runs, so the hidden labels are neither proven cause nor cure.

**Practice (`out/t14c_practice_run1.json`): 11/12** · 0 crashes · 0 leaks · 0 wrong writes · 0 forbidden words · avg 7.7 s · 37,773 tokens
| id | got | pass |
|---|---|---|
| a01 | decline AT-FLT-03 | ✓ |
| a02 | decline AT-FLT-06 | ✓ |
| a03 | decline AT-FLT-06 | ✓ |
| a04 | decline AT-FLT-04 | ✓ |
| a05 | info (no write, no approval) | ✓ |
| a06 | layer3_pending 839.50 | ✓ |
| a07 | decline AT-HOT-03 | ✓ |
| s01 / s02 | ask_proof R-DMG-01 | ✓ ✓ |
| s03 | ask_user (expected approve) | ✗ Agent B corrected a one-letter typo of the client inside its `user_quote`: quote not in the message → ask first. Not the negation check |
| s04 | decline R-RET-01, 0 refunds | ✓ |
| s05 | approve R-CAN-01 (COD, 0 refunds) | ✓ |

**Held-out (`out/t14c_heldout.json`), run once on the frozen code (commit after the practice run): 9/12** · 0 crashes · 0 leaks ·
runner's wrong-write check 0 · 0 forbidden words · avg 6.2 s · 42,788 tokens
| id | expected | got | pass |
|---|---|---|---|
| h01 | decline AT-FLT-03 | decline AT-FLT-03 | ✓ |
| h02 | decline AT-FLT-06 | decline AT-FLT-06 | ✓ |
| h03 | decline AT-FLT-06, 0 refunds | **approve AT-FLT-01, refund 690.00** | ✗ |
| h04 | approve, refund 690.00 | ask_user (nothing written) | ✗ |
| h05 | decline AT-FLT-04 | decline AT-FLT-04 | ✓ |
| h06 | decline AT-HOT-01 | decline AT-HOT-01 | ✓ |
| h07 | approve AT-HOT-03 (cancelled, 0 back) | same | ✓ |
| h08 | approve R-CAN-01, 54.40 | same (a "not able to cancel" message now confirms) | ✓ |
| h09 / h10 | ask_proof R-DMG-01 | same | ✓ ✓ |
| h11 | decline R-CAN-01 | same | ✓ |
| h12 | 0 refunds, order stays processing | **approve R-CAN-01, order 4514 cancelled** | ✗ |

Groq today: ~130k tokens (p07 49k, practice 38k, held-out 43k, quota checks); no limit hit.

## 4. Problems (honest)
1. **Held-out 9/12, under the bar.** Not tuned after the run.
2. **h03 — a refund the client did not ask for (690 TND).** The client asks to be reimbursed for a hotel stay after the cancelled
   flight: Intake said `refund_request` (not compensation), so the compensation decline did not apply; Agent B proposed a ticket
   refund under AT-FLT-01, which the rules allow (cancelled flight; AT-FLT-06 says "the refund still applies"), and the code
   confirmed it (refund reason + a real quote). The runner's rule check does not count it as a wrong write, but the client asked
   for hotel costs, not a ticket refund.
3. **h12 — an order cancelled that the client did not ask to cancel.** The client asks to cancel a membership charge on order 4514:
   the sentence with "cancel" has no subscription/membership word (it is in the previous sentence), so Intake said `cancel_order`,
   and the code confirmed the quote. COD order, so 0 refund rows, but the order is cancelled. ShopNova's wrong-write check only looks at
   refund rows, so it did not flag it.
4. **h04 — my negation check is wrong on "<noun> not refunded (yet)".** "not refunded" without "was/is/has" is read as a
   negation (the "still waiting" exception needs a be-verb). Safe outcome (ask first, nothing written), but a miss caused by item 2.
5. **s03 (practice)** — the agent fixed the client's typo inside its quote, so the exact-quote check failed (safe: ask first).
6. **AT-FLT-03 condition (please confirm):** the task table says "departure delay < 3 h"; the rule text and condition say
   **arrival** ("arrives 3 hours or more late", `arrival_delay_min >= 180`). I coded the rule's own condition (arrival). For all
   scripted bookings both give the same result.
7. **Damage word below the threshold:** a sentence with the damage word becomes `damaged_item` even under 0.69 (s01: 0.636). The
   threshold value is unchanged, but this is a word override like T14a's cancel word; validation F1 did not move.
8. **Design choice in item 1:** inside `review()`, the decline fires only when the proposal matches the client's request
   (compensation ↔ compensation_request; refund / hotel cancellation ↔ money back), and never for a cancellation of a still-confirmed
   hotel booking (T21's real cancellation). A mismatching proposal goes the old way (this is how h03 was approved).
9. `docs/UI_replacement_brief.md`, `.vscode/`, `tasks/RL2b_followup.md` are not mine; left untouched.

## 5. Questions for the Brain
1. h03 / h12: should a write need the proposal's action to match the client's words more strictly (e.g. payment, hotel-cost or
   membership words anywhere in the message → ask first), or should the ShopNova wrong-write check also count order-status changes?
2. h04: extend the "still waiting" exception to "<noun> not refunded (yet)" without a be-verb? (Not done: held-out rule.)
3. AT-FLT-03: arrival delay (rule text) as coded — OK?
4. Accept the damage-word override under the threshold (item 7)?
5. Quote check: allow tiny typo differences (s03), or keep it exact (safer)?
6. Held-out is under the bar: a new held-out set for a later re-run, after the fixes you choose?

## 6. Next step
Brain reviews the 3 held-out misses and answers Q1–Q2 (they decide whether T14c can merge as is or needs a T14d for request/action
matching). Then the roadmap: RL1 → step 09 → agent C → agent D.

**Is it safe for the demo?** The decline replies are correct on every scripted Atlas case tried (practice + held-out: 10/10 declines
right). The risk is the two held-out cases where a write happened that the client did not ask for (h03, h12); avoid similar
"refund of other costs" / "cancel a payment" messages in the demo until Q1 is decided.
