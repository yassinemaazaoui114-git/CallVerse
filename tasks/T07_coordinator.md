# T07 — Join platform + Agent B into main, the Coordinator (S1, S2, Layer 3), rate-limit fix

## Why
Agents only **propose**. The Coordinator is the rule-based safety gate: it re-reads the data, checks the cited rule,
the user's confirmation and the finance limit, then approves (and only then the platform writes), sends back, or
escalates. This task makes scenarios S1 and S2 run end to end and makes the demo survive Groq's rate limit.

## Hard limits
- Coordinator = **rules only, no LLM**. It uses the platform functions; it never trusts the agent's `facts_used`.
- Action names: **`refund`** and **`subscribe`** (not `subscribe_update`).
- Do not change platform files (`callverse/data/*`, `callverse/kb/policies*`, `callverse/server/*`) except to call them.
- `main` changes only through the merges in step 0. Then work on branch **`feature/coordinator`**.
- No secrets in files. Never tune on held-out test files.

## What to do
0. **Merges (approved):** the working tree has an uncommitted `CLAUDE.md` (new git rules by the Brain): commit it on
   `main` first (`"CLAUDE.md: git rules and lanes (approved)"`). Then `git pull --ff-only`, then
   `git merge --no-ff origin/platform` (P05–P07, reviewed: 102/102) and `git merge --no-ff origin/feature/agent-b`
   (T06, reviewed). Resolve by **combining both sides**: `CLAUDE.md` (keep the new git rules and the three lanes),
   `requirements.txt`, `README.md`, `config.yaml`, `docs/*`, test files about allow-lists (keep both sides' intent:
   `get_refunds` only on B, `get_company_profile` only on A). `pip install -r requirements.txt`, run all tests;
   if green, `git push origin main`. If a conflict touches code logic beyond this list, stop and report.
   Then `git checkout -b feature/coordinator`.
1. **Coordinator** — `callverse/coordinator/coordinator.py`: `review(proposal, case) -> decision`.
   - `record_proposal` (platform) → id.
   - **Facts match data:** order exists; for `refund` read `paid`, `refunded_total` (`get_refunds`), `days_late`,
     `delivered` (`get_tracking`) yourself.
   - **Policy allows:** the cited `rule_id` exists and `check_condition(rule.condition, facts)` is true;
     R-REF-05 (`amount <= paid - refunded_total`) always checked for refunds.
   - **User confirmed:** `user_confirmed` true, else outcome `ask_user`.
   - **Layer 3:** if R-ESC-01's condition (`amount > 300`) is true → `layer3_decide`; refused → outcome `layer3_refused`.
   - Outcomes: `approve` → `record_decision(approve)` → `create_refund(...)` (+ `set_order_status(order, "refunded")`
     for R-REF-03) or `create_subscription(order, event, proposal_id)`; `send_back(reason)` (max 2 per case, the 3rd
     becomes `escalate`); `ask_user`; `ask_proof` (R-DMG-01 without proof); `escalate`.
   - Every check traced (`coordinator_check` with rule, facts, result) and the decision (`coordinator_decision`).
   - Returns a decision dict: `outcome, action, order_id, rule_id, facts` (only verified facts), `next_step`, `reason`,
     `proposal_id` (the SLM will use this format later).
2. **Pipeline:** when an agent submits a proposal → `review` → on `send_back`, give the reason to the same agent once
   more so it can correct (max 2 send-backs) → final decision in the result. Agent A's subscription proposals use action
   `subscribe`.
3. **Scenarios** — `scripts/run_scenario.py S1|S2|S4 [--inject-error]`:
   S1 "Order 4512 is a week late. I want my money back." → approve; S2 = S1 with `--inject-error` (B's first proposal
   70.00) → send_back → corrected → approve; S4 "Order 4515 is very late, I want a full refund." → Layer 3 approved → approve.
   Each prints a readable step list + trace path.
4. **Fewer tokens per turn:** measure Agent B tokens per turn (from the trace) **before** changes. Then: `search_policy`
   returns the top 2 with text cut to ~300 characters; `ask_agent` returns compact facts (not A's whole transcript);
   shorter prompts; only allowed tool schemas sent. Measure **after**. Target: average B turn **< 8,000 tokens**.
5. **Rate limit:** in `llm.py`, on 429 read `retry-after`; if ≤ 20 s, wait and retry the same model once; otherwise move
   to the next model. Add **Gemini Flash** as the 3rd model of `models.agents` (use the Flash model id this key accepts;
   check with one call). Add a way to force a model for testing (e.g. env `CALLVERSE_FORCE_AGENTS_MODEL`).
6. **Tests (no API):** Coordinator: S1 approve; amount > paid → send_back; already refunded → send_back; rule condition
   false → send_back; not confirmed → ask_user; 4515 378 → Layer 3 approved → approve; 600 → layer3_refused; third
   send-back → escalate; subscribe with an event outside R-NOT-01 → send_back; a proposal decided twice → refused.
   llm: 429 with retry-after 2 s → waits and retries; retry-after 60 s → next model.

## Checks (with numbers)
- S1: refund row **59.90**, rule **R-REF-03**, status approved; order 4512 → `refunded`; proposal decision `approve`.
- S2: **1 send_back** (reason mentions R-REF-05) then **approve** (2 proposals recorded).
- S4: Layer 3 **approved**, refund **378.00**.
- Agent B tokens per turn: before → after (target < 8,000).
- Run S1 **3 times in a row, no pause** → **3/3** succeed (report which model answered each time).
- Forced Gemini run of S1 → outcome **approve** (tool calling works on Gemini).
- All tests pass (report x/y, before and after the merges).

## Time box and stop rule
3 hours. Stop and report if a merge conflict touches logic, or a check fails twice.

## Git (approved by Yassine, 2026-10-20)
Commit `CLAUDE.md` on `main`; merge `origin/platform` then `origin/feature/agent-b` into `main` (`--no-ff`); push `main`
if all tests pass. Then branch `feature/coordinator`, commit, push. No other merge. Write `tasks/T07_report.md`, set
`tasks/NEXT.md` to WAITING FOR REVIEW.
