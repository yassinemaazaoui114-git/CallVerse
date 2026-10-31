# P20 report — Agents C and D rebuilt to the official spec

## 1. In plain words
Agent C now does "urgent and special help": when a client needs an item fast (for example a gift for tomorrow and
the order is late), it can offer a free replacement from stock, keep an item for the client for up to 3 days, or pass
a hard case to a human colleague. It only proposes; the rule-based Coordinator checks the facts itself, and nothing
changes until the client has answered "yes" to C's question. Agent D now watches stock: it compares what is left
with what sold in the last 30 days, warns Agent A when an item of an order is running out, and proposes promotions
for products that sell too slowly, which the shop owner must approve. On the fine-tuned local model
(`callverse-m2-v3`) the four agents pass 24 of 26 practice cases, with no Groq call.

## 1b. Second round: gaps with the project spec (`PIDS_project_spec.md`, checked 2026-10-31)
| Spec | Before | Now |
|---|---|---|
| Link (1) C asks A "get the facts" (+ deadline: can meet yes / no) | C read tracking itself | tool `get_facts_from_a`: Agent A reads with its tools; "can meet the deadline" is computed by code from A's facts (`agents/ask_c.py`) |
| Link (2) C asks B "urgent refund" (top of the human's list) | missing | C ends with `[HANDOVER: B]`; B runs, the ticket is marked urgent; urgent approvals come first (`approvals.urgent`, page shows URGENT) |
| Link (4) C asks D "is it available?" | C read stock itself | tool `check_availability_with_d` (by order: the product ids come from the order) |
| Link (5) D tells A "stock-out warning" | done | unchanged (line in A's Intake note) |
| C = Layer 2 (escalated, sent back twice, disputed) | built, OFF | ON by default (`pipeline.layer2_agent_c: true`) |
| C at Atlas: rebook, assistance with explicit consent | Atlas routed both to "a colleague" | routes `rebooking` / `special_assistance` -> C; `propose_rebooking` (AT-FLT-01: cancelled flight -> later flight on the same route) and `propose_assistance` (AT-AST-01: wheelchair, >= 48 h); `coordinator/atlas_special.py`; new table `rebookings` |
| C never pays; nothing changes without the yes | done | unchanged (C has no money tool; yes = answer to C's own question) |
| D at Atlas: overbooked hotels | missing | **built (third round)**: capacity per hotel DERIVED from the real bookings = the most rooms occupied on one past night (Lisbon 25, Algarve 26; `tools/capacity_tools.py`); a coming night above it = overbooking risk (new rule AT-CAP-01) -> a warning line in Agent A's Intake note for hotel bookings of that night |
| D at Atlas: deals for empty capacity | missing | **built for hotel rooms**: coming nights at 30 % or less (new rule AT-DEAL-01, max 20 %) -> a deal proposal, `owner_pending`, table `hotel_deals`; the owner decides on the Atlas Approvals page ("Hotel deals"), one transaction, no price change. Today: 2 deals proposed (1 low night per hotel), 0 overbooked nights |
| D at Atlas: empty **seats** | missing | **not built**: flights have no seat count and the schedule has 1 coming flight; a seat number would have to be invented |
| Low-confidence tickets to C | missing | **built (third round)**: confidence = Intake's own score of the main reason minus the company's reason_threshold (no new model); a case with a margin under `queues.low_confidence_margin` (0.02, a first value, not tuned on any test set) goes to C, layer L2 (`queues/router.py`) |
| Urgent cases never go to fallback | n/a | fallback mode is out of the prototype (CLAUDE.md) |
| "Agents A-D are not trained, only E" | - | **the switch to `callverse-m2-v3` (a fine-tuned model) needs Yassine's OK and a written reason** (question 1) |

Found on the way: with the links, v3 asked D about invented product ids (123, 1001) and C fell to 3/7; fixed by asking D
per ORDER and letting the replacement / hold use the order's own item. C is back to 5/7.

## 2. Done
- Old local branch `feature/agents-cd` (wrong C = returns, D = delivery messages) deleted, on the user's go (no backup).
  New branch `claude/project-thread-xbs9wx` from the latest `main`. Not pushed.
- Task file `tasks/P20_agents_cd_rebuild.md`.
- 5 new rules in `callverse/kb/policies_shopnova.json`: R-RPL-01 replacement, R-HLD-01 hold, R-AST-01 special help,
  R-STK-01 low stock, R-PRM-01 promotion (owner approves). The thresholds live only in their conditions.
- 4 new tables (`seed.py`, created if missing on an older database): `replacements`, `holds`, `assistance_requests`,
  `promotions`. Writes in `writes.py` (Coordinator only, same safety nets as refunds: approved proposal, same params,
  used once, stock never below 0, one replacement per order); `admin_decide_promotion` in one transaction.
- `callverse/tools/stock_tools.py`: `get_stock` (read tool) and the stock report (units sold in 30 days, days of cover,
  shortage / overstock from the rule conditions).
- `callverse/agents/agent_c.py`: LLM agent. Allow-list: `get_order, get_tracking, get_stock, search_policy,
  propose_replacement, propose_hold, propose_assistance` (not `get_refunds`: rule T06, only B reads refunds).
- `callverse/agents/agent_d.py`: rules. Model only for the owner's note; the note's numbers are checked, else a template.
- `callverse/coordinator/special.py`: checks for replace / hold / assistance / promotion; `coordinator.review` sends
  these actions there. **A yes counts only when the client's message answers C's own question** (the channel marks it);
  the model's `user_confirmed` alone is not enough (see Problems).
- Pipeline: Agent A's `[HANDOVER: C]`; web chat sends the client's answer back to C (`continue_agent`); D's shortage
  line in the Intake note (`stock_warning`); Layer 2 (C takes cases A/B escalate), switch `pipeline.layer2_agent_c`,
  OFF; one retry when C writes its offer as text without calling the tool, switch `pipeline.c_offer_retry`, ON.
- Approvals page (`apps/shopnova/pages/6_Refund_approvals.py`): new "Promotions (Agent D)" part with "Check stock now",
  Approve / Refuse (reason required to refuse). The price never changes by itself.
- `config.yaml`: `models.agent_c` (Groq, like B), `agent_c_local`, `agent_d` (local), the two switches, handover text.
- Test bench `scripts/eval_agents.py` carried over (same arguments, so `D4\v3\compare_models.py` works unchanged),
  now with D cases (rules) and an optional expected Coordinator outcome. Cases `tests/dev/agents_cases.json` (26).

## 3. Evidence
- `pytest`: **1091 passed** after the third round (`tests/test_agent_d_atlas.py`: capacity, overbooking warning,
  deals and the owner's decision, low-confidence routing); **1085** after the second round (Atlas C tests in `tests/test_agent_c_atlas.py`; the Atlas route
  tests and practice message a11 now expect Agent C, which asks the client first, instead of "a colleague");
  first round: 1075 passed (27 new in `tests/test_agents_cd.py`, `tests/test_eval_agents.py`; 3 old guard
  tests updated on purpose: Agent A's prompt fingerprint (one new line), the tool-schema fingerprint now covers the
  tools that existed before, rule count 8 -> 13).
- Practice cases, all local, no Groq call (`traces/eval_v3_all.json`, `eval_base_all.json`, `eval_*_C2.json`):

| Agent | callverse-m2-v3 | base Qwen (cv-qwen3-4b-instruct) |
|---|---|---|
| A (8) | 8/8, avg 10.7 s (rerun after the links, `eval_v3_A3.json`) | 5/8 |
| B (7) | 7/7, avg 29.9 s | 5/7 |
| C (7) | 5/7, avg 27.9 s (after the links, the yes rule + retry; `eval_v3_C4.json`) | 2/7 (before the links) |
| D (4, rules) | 4/4 | 4/4 |
| **Total** | **24/26** | **16/26** |

- Wrong proposals (an action where none was due): 0 on both models. Every C proposal without a real yes ended
  `ask_user`; nothing was written.
- D's owner notes: 12/12 kept the model's wording (numbers checked).

## 4. Problems
- **v3 said "confirmed" without a yes** (C01, "I need it tomorrow"): before the fix the replacement was approved at
  once. Fixed in code (the yes must answer C's question), so the model cannot decide it any more.
- v3 C04: omits `hold_days` (default 3 used, the client asked 2). C06: `order_id` empty in the assistance request.
  Both safe (Coordinator checks, client asked first) but wrong details.
- Base Qwen: right proposals now, but its own text promises "as soon as possible" (that text never reaches the client:
  the SLM writes the reply from the decision; still scored).
- A04 and A11 changed meaning vs the old 28 cases (A now proposes the notification itself, as on main; A11 is the
  new handover to C), so A/B/C/D totals are not comparable with the old 25/28.
- C, A11 and D cases are **my drafts** (Claude): the team must review them. There are **no held-out C/D cases** yet
  (the old ones tested the wrong jobs and were removed); they must be written by the team.
- The Approvals page uses the `approve_refunds` permission for promotions.
- Not pushed; CLAUDE.md still says C and D are out of scope (Yassine's file, not changed).

## 5. Questions for the Brain
1. Switch C (and B) to `callverse-m2-v3` locally? On practice cases v3 is 24/26 with 0 wrong proposals; the
   held-out run is still needed, and C/D held-out cases do not exist yet.
2. Turn on Layer 2 (`pipeline.layer2_agent_c`)? It is built and tested, OFF by default.
3. Promotions: keep the `approve_refunds` permission, or a new `approve_promotions`?
4. Atlas C (rebooking, special assistance: today routed to `escalate`) as the next task?
5. Pickup points / nearby stock (spec example) need data the platform does not have; add it?
6. Hotel capacity is a lower bound from our 2,000-booking sample (25 / 26 rooms): OK, or give real room counts?
   Seats per flight and coming flights (for rebooking and seat deals) still have no data.
7. Low-confidence margin 0.02: keep, or measure it on the Intake dev set first?
8. Yassine planned to build C and D himself: is P20 the version to review, and who owns it from here?

## 6. Next step
Team writes held-out C/D cases and reviews the drafts; run the held-out set once on v3; then decide question 1.
