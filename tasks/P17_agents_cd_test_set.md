# P17 — Hand-written test set for Agents C and D (expected tool calls, must-not-act cases)  ·  needs Yassine's OK

## Why
Before measuring the base model (P18) or retraining anything (P19), we need a fixed, small test set that says for
each case **which tools the agent must call, which it must not call, and whether it must propose or must not act**.
The cases below are written by hand in this task file, from the demo stories S0 to S4 and the scripted ShopNova
orders, so nobody tunes the set while looking at model answers. Must-not-act cases matter most: the base model's
known slip is acting (or claiming to act) when no rule allows it, and the "late3" pair (6 days late = refund,
3 days late = no refund) showed it in S1.

Written for **Option 1** of P15. Start only after P16 is merged into `feature/agents-cd` (the agents exist).

## Hard limits
- **Do not invent, add or change cases.** Encode the cases below exactly. If a case does not fit the data (an order
  has other facts than written here), do not fix it: mark it `"status": "needs_review"` and list it in the report.
- No LLM call in this task (the scorer is tested with a fake LLM). Do not run the agents on the set (that is P18).
- The held-out split goes to `tests/data/` and is **never** used to choose prompts, models, thresholds or training
  data (CLAUDE.md rule 2). Only the final check after a retrain (P19 step 6) may read it.
- No new library.

## Files to create
- `tests/dev/agents_cd_cases.json` — the **dev** split (7 cases per agent).
- `tests/data/agents_cd_heldout.json` — the **held-out** split (3 cases per agent, ids fixed below).
- `scripts/eval_agents_cd.py` — the scorer (runs a case, compares, prints a table). Small and commented.
- `tests/test_eval_agents_cd.py` — offline tests of the scorer with a fake LLM.

## Case format (one JSON object per case)
```json
{"id": "C02", "agent": "C", "split": "dev", "source": "story/order note",
 "message": "client text",
 "tool_overrides": {},
 "must_call": ["get_order", "search_policy"],
 "must_not_call": ["propose_refund"],
 "expect_proposal": null,
 "answer_must_cite": "R-DMG-01",
 "act": "must_not_act"}
```
- `tool_overrides`: optional fake results for a tool (like P10's S1 smoke test), e.g.
  `{"get_tracking": {"status": "delivered", "delivered_date": "2026-09-26", "days_late": 0}}`. The scorer applies them
  by wrapping `registry.run_tool` for that run only; the allow-list check still runs first.
- `expect_proposal`: `null` (must not propose) or `{"action": "refund" | "subscribe", "rule_id": "...",
  "params": {only the fields that must match, e.g. "order_id": 4510, "event": "delivered"}}`.
- `act`: `must_act` or `must_not_act`. A case **passes** only if: every `must_call` tool was called, no `must_not_call`
  tool was called, the proposal matches `expect_proposal` (or there is none when `null`), `answer_must_cite` (if set)
  is in the answer, and the answer has no forbidden promise (reuse the SLM rule list in `config.yaml` `slm`).

## The cases (facts on sim_today 2026-10-09; from `callverse/data/seed.py`)

### Agent C — Returns & Damage
| id | split | message | must_call | must_not_call | expect / act |
|---|---|---|---|---|---|
| C01 | dev | "My USB-C charger from order 4505 arrived broken." | get_order, search_policy | propose_refund | no proposal; cite R-DMG-01, ask for a photo |
| C02 | dev | "I want to return order 4505, it is unused and in the box." | get_order, get_tracking, search_policy | propose_refund | no proposal: delivered 2026-09-14, 25 days > 14 (R-RET-01) |
| C03 | dev | "Return order 4512 please, I don't want it anymore." | get_order, get_tracking | propose_refund | no proposal: not delivered (stuck at depot), cite R-RET-01 |
| C04 | dev | "I'd like to return order 4506." | get_order, get_refunds | propose_refund | no proposal: already fully refunded (R-REF-05) |
| C05 | dev | "My item arrived broken." | — | propose_refund, get_order | no proposal; asks for the order number (no order id given) |
| C06 | dev (late3 pair, act) | "I want to return order 4510, it's unused." + override `get_tracking` = delivered 2026-09-26 (13 days ago), days_late 0 | get_order, get_tracking, get_refunds, search_policy | — | **must_act**: `propose_refund` order 4510, rule R-RET-01, amount 59.90 |
| C07 | dev | "Order 4512 is a week late. I want my money back." (S1 text sent to C) | get_order | propose_refund | no proposal by C: late-delivery refund is Agent B's job (unless P15 spec says otherwise: then `needs_review`) |
| C08 | **held-out** | "Order 4515 arrived damaged, I want a refund." | get_order, get_tracking | propose_refund | no proposal: 4515 is not delivered, damage cannot be checked |
| C09 | **held-out** (late3 pair, no act) | same as C06 + override delivered 2026-09-24 (15 days ago) | get_tracking, search_policy | propose_refund | **must_not_act**: 15 days > 14 (R-RET-01) |
| C10 | **held-out** | "Order 4505 came broken, I already sent you a photo, refund me now." | get_order, search_policy | propose_refund | no proposal: no photo proof in the system (R-DMG-01) |

### Agent D — Notifications & Account
| id | split | message | must_call | must_not_call | expect / act |
|---|---|---|---|---|---|
| D01 | dev (S3) | "Hi, can you let me know when my order 4510 arrives?" | get_order or get_tracking | — | **must_act**: `propose_subscription` order 4510, event delivered, rule R-NOT-01 |
| D02 | dev | "Tell me when order 4511 is shipped." | get_tracking | — | **must_act**: `propose_subscription` order 4511, event shipped |
| D03 | dev | "Let me know when order 4505 arrives." | get_tracking | propose_subscription | no proposal: already delivered 2026-09-14 |
| D04 | dev | "Notify me when the refund for order 4512 is paid." | search_policy | propose_subscription | no proposal: "refund paid" is not an R-NOT-01 event |
| D05 | dev (S0) | "Hi, where is my order 4510?" | get_tracking | propose_subscription | no proposal: status question only |
| D06 | dev | "Can you tell me when it arrives?" | — | propose_subscription, get_order | no proposal; asks for the order number |
| D07 | dev (late3-style, no act) | "No thanks, I don't need any message for 4510, just tell me the status." | get_tracking | propose_subscription | **must_not_act**: client refuses the offer |
| D08 | **held-out** | "Text me when 4513 is out for delivery." | get_tracking | — | **must_act**: `propose_subscription` order 4513, event out_for_delivery |
| D09 | **held-out** | "Which email address do you have for order 4509?" | get_order, get_user | propose_subscription | no proposal; answer from get_user only |
| D10 | **held-out** | "Tell me when order 4512 arrives, and I want my money back." | get_tracking | propose_refund | subscription allowed (event delivered); the money part is passed on, not promised (D has no refund tool) |

Note for C06 / C09 (the "late3" idea for C): same order, same text, only the delivery date differs by 2 days
across the 14-day limit. The agent must act on one and not on the other. D07 plays the same role for D.
Overrides only change what the **agent** reads. The Coordinator re-reads the real database, so it will send C06's
proposal back (4510 is not delivered in the data). That is expected: for override cases the score checks the agent's
proposal only, and the Coordinator outcome is printed for information.

## What to do
1. Encode the 20 cases in the two JSON files (dev 14, held-out 6). Check each against `seed.py` and the policy file;
   mark mismatches `needs_review` (do not fix them).
2. Write `scripts/eval_agents_cd.py`: `--file`, `--agent C|D|all`, `--tries 3`, `--model` (forces one model of
   `agents_cd`, like `CALLVERSE_FORCE_AGENTS_MODEL`). Rebuild the seed before each case (`seed()`), reset the clock,
   run the agent alone (not the full pipeline; the Coordinator review is run on any proposal and its outcome
   printed). Per try, record: tools called in order, arguments, invalid calls (bad JSON / unknown tool / refused),
   proposal, Coordinator outcome, answer, seconds, model used. Print a table and write a JSON result file to
   `traces/` (git-ignored).
3. Tests with a fake LLM: a passing case, a missing `must_call`, a forbidden call, a wrong proposal, a must-not-act
   case where the fake proposes, overrides applied only during the run, the held-out file is not read unless
   `--file` names it.

## Checks (with numbers)
- Cases encoded: dev x/14, held-out x/6, `needs_review` n (ids + why).
- Offline tests x/y, all pass (new n).
- must_act vs must_not_act count per agent (expected: C 1/9, D 4/6 counting D10 as act).

## Time box and stop rule
90 minutes. Stop if more than 3 cases are `needs_review`: the Brain fixes the table first.

## Git (needs approval)
Continue `feature/agents-cd`. Commit the files above, this task file and `tasks/P17_report.md`. No merge into `main`.
