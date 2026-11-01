# T14d — A write must match what the user asked (request/action match)

Approved by Yassine 2026-11-01 13:33 (B1 + C1–C3). Model: **Sonnet 5.5** — switch with `/model` before you start (T14c ran on Opus by mistake).
New conversation, branch from `main` **after T14c is merged** (`git checkout main && git pull`, branch `feat/t14d-request-match`). Time box **2.5 h**, WIP stop allowed.
Offline coding and tests can start now; live runs need fresh Groq quota (T14c used ~130k of today's 200k) → **do the live runs on Monday**.

## Why
T14c held-out 9/12. Two real wrong writes (both behaved the same before T14c, the new set exposed them):
- **h12** — "cancel this payment (Prime membership $11)" → Intake said `cancel_order` → order 4514 got cancelled. The user asked to stop a charge, not the order.
- **h03** — asked for hotel-stay costs after a cancelled flight → a 690 TND ticket refund (AT-FLT-01) was approved.
- **h04** — "amount not refunded till date" was read as a negation → asked first, nothing written (safe, but a miss).

## Hard limits
- Security as always: never read `.env`, no secrets, no force push/rebase/reset/branch deletion, **no merge into main** (Yassine merges). Agents propose, the Coordinator executes. No change to thresholds, rule texts, or Intake models (pinned). No fingerprint change unless an item says so; list any in the report.
- `tests/data/t14d_heldout_messages.json`: **do not open, print or grep until item 6.** Run it ONCE at the end, never fix after it (rule 9). `tests/data/t14c_heldout_messages.json` is now **dev material** (already seen): use it as practice, just run it from where it is.
- Fixes must be **general rules** (word lists + tests on synthetic sentences and the t14c sets), not patches for one tweet.

## What to do (approved B1)
0. Branch, full suite first (expect 1283 pass).
1. **ShopNova: money words ≠ order cancellation (h12).** If the message says payment / charge / charged / billing / statement / membership / subscription / prime (as a service) and the "cancel" is about it, Intake must **not** give `cancel_order` as the main reason (→ ask first / info, no write). Whole-word match; "cancel my order" with the order named still wins. Also: "pressed cancel by accident / how do I fix this" is not a request to cancel. Same style as the T14b cancel word / T14c damage word (code check next to `reasons.py`).
2. **Atlas: a ticket refund needs a money-back request (h03).** If the user asks about hotel costs / hotel voucher / reimbursement of expenses / meals / taxi / "compensate for my hotel…" the reason is **compensation_request** (or info), not `refund_request`; an agent's refund proposal for such a message is **not confirmed** by the Coordinator (ask first or the existing compensation decline/finance path). A plain "refund my cancelled ticket" must still work (AT-FLT-01).
3. **Runner wrong-write check (ShopNova):** `scripts/run_t14c.py` (or a new `scripts/run_t14d.py` copied from it) must also flag an **order status change** that the expect does not allow (use `expect.order_status` and fail if the order was cancelled/refunded unexpectedly).
4. **Negation exception (h04):** "<thing> not refunded/returned/credited" followed by yet / till / still / since / for N days / ago = a **complaint, not a negation** (so it is a refund request). Keep "should be rerouted NOT refunded" and "do not want to refund/return" as negations. Change `callverse/coordinator/negation.py` only; add ≥ 8 synthetic tests (both directions).
5. **Practice run (live, Monday):** run `tests/data/t14c_heldout_messages.json` (12) with the new code. Expectation: h03, h12 pass now (the fixes were built on them, so this is **dev**, not proof); h04 passes; nothing that passed before fails. Also tell the Brain the Groq tokens used.
6. **Held-out (once, at the end):** `tests/data/t14d_heldout_messages.json` (12 new real tweets: 6 Atlas, 6 ShopNova). Pass bar: **≥ 10/12**, 0 crashes, 0 leaks, 0 wrong writes (any refund row or order-status change not allowed by `expect` = wrong write), 0 forbidden words. Report each id: expected / got / pass.

## Checks the Brain will look at
- Rules in code (word lists) with tests for both directions; the "cancel my order" positive paths still pass (t12, h08, s03, s05).
- Full suite green; no pinned-fingerprint change (or listed).
- Held-out table; any miss explained honestly; nothing tuned after the run.

## Git
Small commits on the branch, push, **no merge**. At the end set `tasks/NEXT.md` to WAITING FOR REVIEW and write `tasks/T14d_report.md`.
Report format: In plain words · Numbers · Problems · Questions for the Brain · Next step.
