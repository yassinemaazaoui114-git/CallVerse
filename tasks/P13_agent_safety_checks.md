# P13 — Code checks for agent slips (any model) + S1 "cancelled" wording  ·  core files, needs Yassine's OK

## Why
Three known slips, seen with gpt-oss, qwen3.5:4b (T13) and base Qwen3-4B (S1). They are fixed in **code** (checks and
structure), never with prompt tricks for one model (T13 fix rule). Useful whatever model runs the agents, so this task
does not depend on P10 to P12. Background: `docs/m2_finetune_review.md` §4.

1. **Text-only proposal.** The agent writes "I propose a full refund under R-REF-03 ... sent for checking" but never
   calls `propose_refund` (or `propose_subscription`). Safe (nothing is written) but the client gets an `info` reply
   and the refund path never runs.
2. **Policy not searched.** Agent B sometimes proposes without calling `search_policy`. The Coordinator only logs
   `rule_not_searched` (coordinator.py ~line 258); it does not send back.
3. **S1 wording.** For R-REF-03 the client is told "Your order N is now cancelled." (`user_words`, ~line 78) while
   `_finish` sets the order status to `refunded` (~line 328).

## Hard limits
- Touches `callverse/pipeline.py`, `callverse/coordinator/coordinator.py` and their tests only. No prompt change.
- Every new check is traced. No new library. Never run `tests/data/*`.
- Wording change for slip 3 = **decision for the Brain/Yassine** (see step 3): write both options in the report if not
  decided before you start.

## What to do
1. **Slip 1, pipeline check.** After an agent turn with no proposal: if the answer text claims a proposal (simple,
   commented regex on words such as "propose", "proposal", "sent for checking" together with "refund" or a rule id
   `R-[A-Z]+-\d+`), send the agent back once, like a Coordinator send-back, with the note
   "[Coordinator: you described a proposal but did not call the proposal tool. Call it, or answer without proposing.]".
   It counts toward `coordinator.max_send_backs`. Trace `claimed_proposal_without_tool`.
2. **Slip 2, Coordinator check.** If the proposal's `rule_id` is not in `case["searched_rules"]`: **send back** with the
   reason "cite a rule you found with search_policy" instead of only logging. Keep the existing trace event.
3. **Slip 3, wording.** Make what the client hears match the database. Option A (recommended): next_step
   "Your order N is now refunded." Option B: keep "cancelled" and set the status to `cancelled` (needs a platform
   check: `writes.py` allows both). Do the option written in "Approved by"; update tests that check this sentence and
   the S1 expected reply ("Your refund of 59.90 TND is approved." must stay).
4. **Tests (offline, fake LLM):** text-only claim → 1 send-back → proposal accepted; text-only claim twice → escalate
   path unchanged; plain info answer (no claim) → no send-back; proposal with a rule not searched → send_back;
   S1 next_step text.
5. **Live check:** practice set on the current default chain (Groq) or, to save quota, with the T13 local switch.
   Say which.

## Checks (with numbers)
- Offline tests x/y, all pass.
- Practice x/24, crashes, leaks, wrong writes; count of `claimed_proposal_without_tool` and `rule_not_searched`
  send-backs; proposals made x/5 on d05, d17, d18, d20, d24 before vs after.
- S1 reply text before / after.

## Time box and stop rule
90 minutes. Stop if a check causes a wrong write or more than 2 extra send-backs on one practice message.

## Git (needs approval)
Branch `feature/agent-checks` from the latest `main`. Commit and push. No merge into `main`.
Write `tasks/P13_report.md`. Because these are core files, track it in `tasks/NEXT.md` (Yassine's lane) if Yassine prefers.
