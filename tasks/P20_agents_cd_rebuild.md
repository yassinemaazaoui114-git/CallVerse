# P20 — Agents C and D, rebuilt to the official spec (ShopNova)

| Field | Value |
|---|---|
| Lane | Agents A-D (local Qwen goal) |
| Branch | `claude/project-thread-xbs9wx`, from the latest `main` (not pushed until the user says go) |
| Approved by | (waiting for Yassine) — built on its own branch meanwhile (CLAUDE.md rule 1: own branch is free) |
| Time box | 1 day of build + 1 eval run per model |
| Replaces | the local branch `feature/agents-cd` (C = returns, D = delivery messages: wrong jobs) and its P15-P19 |

## Why
The official spec (user screenshot, 2026-10-31) gives C and D other jobs than the ones built on `feature/agents-cd`:

- **C = Urgent & Special Help.** The only agent that *changes the situation*: replace an item, hold (reserve) an
  item, request human assistance (rebooking is the Atlas version, later). It combines what A (delivery facts),
  B (money facts) and D (stock facts) read. **Nothing changes until the client says yes.** It is also **Layer 2**
  for hard or disputed cases. ShopNova example: a gift is needed tomorrow -> offer a replacement from stock.
- **D = Availability & Supply.** Compares stock with demand, **warns A** of shortages, **proposes promotions** for
  overstock. **The owner approves every promotion.**

## Design (the locked rules stay)
- Agents never act. C's three action tools and D's promotion only build a PROPOSAL. Only the Coordinator
  (rules, no LLM) writes, after re-reading the facts itself.
- C = LLM agent with tools (same loop as A and B, `base_agent.py`). Allow-list in `tools/registry.py`:
  `get_order, get_tracking, get_stock, search_policy, propose_replacement, propose_hold,
  propose_assistance`.
- D = **rules**, not an LLM: `units_sold_30d` and `days_of_cover` from `products.stock` and the orders of the last
  30 days. Shortage / overstock = the conditions of rules R-STK-01 / R-PRM-01 (one place, the policy file).
  The model is used only to word the note for the owner (template if the model fails).
- New rules in `callverse/kb/policies_shopnova.json`: R-RPL-01 (replacement), R-HLD-01 (hold),
  R-AST-01 (human assistance), R-STK-01 (low stock), R-PRM-01 (promotion, owner approves).
- How C is reached: Agent A ends with `[HANDOVER: C]` for an urgent need / replacement / hold / special help;
  Layer 2: when A or B ends in "escalate", C gets the case once (switch `pipeline.layer2_agent_c`, OFF by default).
- How D warns A: when the ticket's order holds a product in shortage, the Intake note given to A (and C) gets one
  line "[Agent D: ...]" (traced as `stock_warning`). A's allow-list does not change.
- Promotions: Coordinator outcome `owner_pending` -> a `promotions` row (pending) -> the existing
  Refund approvals page gets a "Promotions" section; Approve / Refuse writes in ONE transaction
  (proposal decision + promotion + `admin_actions` row). A promotion never changes the price by itself.
- New ShopNova tables (created if missing, so an old database still works): `replacements`, `holds`,
  `assistance_requests`, `promotions`.

## Done when
1. `pytest` passes (old tests + new offline tests with a fake LLM: allow-list, each Coordinator outcome, writes,
   D's rules, promotion approve / refuse, handover to C, Layer 2 switch).
2. The test bench `scripts/eval_agents.py` (carried over from the old branch so `D4\v3\compare_models.py` keeps
   working) runs A, B, C, D; new C and D practice cases in `tests/dev/agents_cases.json`.
3. Baseline: base Qwen (`cv-qwen3-4b-instruct`), then `callverse-m2-v3`, same cases; results in the report.
4. `tasks/P20_report.md` written.

## Out of scope
Atlas C (rebooking, special assistance: Atlas routes them to `escalate` today), pickup points and nearby stock
(no such data yet), retraining the model on C/D, any push or merge.
