# T26 report — demo-ready platform

**Top line:** all three branches are merged on `feat/t26-demo-ready`: Dali's web UI (`callverse-UI`), agents C and D
(P20, `m2-finetuned`) and RL1 reply styles (`feature/rl1-styles`, default unchanged). One-click start and reset
work. Live flows F1–F7 ran with the real local models: F1–F5 and F7 pass; F6 ends in a safe escalation (no later
flight in the real data). Low-confidence routing to C is switched **OFF**. Nothing is merged into main.

Merge line for Yassine (after the Brain's review): `git checkout main; git merge --no-ff feat/t26-demo-ready`

## 1. In plain words
The new website, the two new agents (C for urgent help, D for stock and hotel rooms) and the reply styles now live
together on one branch, and all tests pass. Double-clicking `Demo.bat` starts the whole demo in about 7 seconds;
`reset_demo.ps1` puts the data back so the demo can be repeated. We ran the demo flows for real: refunds,
approvals by the admins, an order status, Agent C's replacement after the client's "Yes", and Agent D's
promotion and hotel deal proposals. One flow (rebooking a cancelled flight) cannot finish because the real flight
data has no later flight; the safety rules caught the agent's wrong proposal and passed the case to a colleague.

## 2. Done
- Step 1: merged `origin/callverse-UI`; 2 test-helper lines changed in `webui/` (see Problems).
- Step 2: merged `origin/m2-finetuned` (7 conflicts, both sides kept); CLAUDE.md scope line updated.
- Step 3: Agent C = `callverse-m2-v3` -> Groq 120b -> 20b -> Gemini; `pipeline.layer2_agent_c` ON;
  `queues.low_confidence_margin` = null (OFF).
- Step 4: regression check; bench wrapper fix in `scripts/eval_agents.py` (`**kwargs`, so T14f's `booking_type`
  passes through) + test `test_override_wrapper_passes_extra_keywords`.
- Step 5: merged `origin/feature/rl1-styles` (README conflict only); `reply_style` null = unchanged default.
- Step 6: `Demo.bat`, `scripts/start_demo.ps1`, `scripts/reset_demo.ps1`, Desktop shortcut entry.
- Step 7: live flows F1–F7 (table below).
- Step 8: `docs/DEMO_RUNBOOK.md` rewritten for T26 (old `/demo` runbook kept as an appendix); README (start + history).

## 3. Evidence

### Tests
| Suite | Result |
|---|---|
| Full suite on the branch (`python -m pytest -q`) | **1767 passed** (6 min 29 s) |
| `webui/api/tests` (step 1) | 82/82 |
| `npm --prefix webui/frontend test` / `run build` (step 1) | 51/51 / OK |
| After step 2 / after step 5 (earlier sessions) | 1554/1554 / 1765/1765 |

### Step 4a — the 72-message set (local `callverse-m2-v3`, same runners as T14f)
| Set | Result | Note |
|---|---|---|
| decline_practice | 12/12 | |
| decline_heldout | 11/12 | h10 failed with low-confidence routing ON; **not re-run** (held-out: open once, rule 9) |
| t14b_practice | 12/12 | |
| t14c_practice | 11/12 -> s02 re-run with routing OFF: PASS | `out/t26_t14c_s02_rerun.json` |
| t14c_heldout | 12/12 | routing OFF |
| t14d_heldout | 12/12 | routing OFF |
| **Total** | **70/72 as run (71/72 with the s02 re-run)** | bar >= 70/72 met; 0 wrong writes, 0 leaks, 0 Groq tokens |

Both failures came from P20's low-confidence routing to C; that switch is now OFF.

### Step 4b — P20's 26 cases (`out/t26_eval_agents_v3b.json`)
The first run (`out/t26_eval_agents_v3.json`) was invalid: every A/B/C case crashed on `booking_type` (bench wrapper).
| Agent | Pass | P20 had |
|---|---|---|
| A | 8/8 | |
| B | 5/7 (B02, B06 fail) | |
| C | 5/7 (C04, C06 `bad_args`) | |
| D | 4/4 | |
| **Total** | **22/26** (bar >= 22) | 24/26 |
Wrong proposals: **2** (bar 0, **not met**):
- B02: bench artifact. Its fake "3 days late" is put on `get_tracking`, but merged Agent B gets tracking through
  `ask_agent`, so the fake never applies; on the real data (refund allowed) the approval is correct.
- B06: model error. B proposed a refund of 89.00 for order 4514 (cash on delivery, nothing paid), 3 times; the
  Coordinator sent it back and escalated: nothing written.

### Step 7 — live flows (API on 127.0.0.1:8610, queue mode, local models, temp demo-only accounts file)
| Flow | Account | Message | Ticket | Outcome | Seconds | Model |
|---|---|---|---|---|---|---|
| F1 | sara | `Hi, my order 4512 is very late. I want my money back please.` | T-0001 | approve, refund 59.90, Solved | 38.5 | v3 + qwen2.5:1.5b |
| F2 | youssef | `My order 4515 never arrived. I want a refund.` | T-0002 | Waiting for finance (378.00) -> `admin` approves -> Solved; 1 refund row (id 93) | 22.8 | v3 |
| F3 | nizar | `My flight 7004 was very delayed. I want compensation.` | T-0003 | waits (839.50) -> `atlas_admin` approves -> Solved | 17.6 | v3 |
| F4 | amira | `Hi, where is my order 4511?` | T-0004 | info: "your order 4511 is being prepared" | 9.0 | v3 |
| F5 | sara (ShopNova reseeded) | `Order 4512 is late and I need it tomorrow, it's a birthday gift!` -> `Yes` | T-0005 | C: ask_user (replacement Wireless Earbuds) -> approve, new order 12001; 1 replacement row | 25.5 + 21.6 | v3 |
| F6 | hedi | `My flight 7005 was cancelled. Please put me on the next flight.` | T-0006 | Escalated: C proposed "flight 0", Coordinator refused twice ("alternatives: none"), then escalated | 40.1 | v3 |
| F7 | owner | `run_stock_scan` (the Streamlit "Check now" button) | — | ShopNova: 42 short, 504 overstock, 3 promotions pending; Atlas: 0 overbooked, 2 low, 2 hotel deals pending | 0.3 / 0.0 | rules (template wording) |
Trace of F1–F6: `traces/run_20261102_104254_786703.jsonl`. 0 wrong writes. Total: 7 customer messages + 2 approvals.
F7 was run by calling the same function as the Streamlit button, not by clicking in the browser.
`Demo.bat` (via `scripts/start_demo.ps1`) was then run once for real after a reset: exit 0, ready in 7 s, API health OK.

### Other checks
- No `models/`, `data/raw/` or `.env` in `git diff main..HEAD`.
- Groq tokens used in this session: 0.

## 4. Problems
- **`webui/` was touched**: step 1 changed 2 lines in `webui/api/dev_fixture.py` and `webui/api/tests/conftest.py`
  (the test helpers must pass the client message to the Coordinator, needed by T14f's money-back words). The task
  says no `webui/` change; this is test/fixture code only. The Brain should accept or move it to T27.
- **4b bar not met**: 2 wrong proposals (B02 bench artifact, B06 real). The Coordinator stopped both.
- **F6 cannot rebook**: the real 2015 schedule has no later ATL -> LAX flight for 7005. C still invents a flight id
  instead of saying "no flight"; the Coordinator catches it. Not fixed (model behaviour, not a small code fix;
  adding a fake flight would break "real data first").
- h10 (held-out) was not re-run with routing OFF (rule 9).
- The PC has little free RAM (about 2.8 GB free with the model loaded); runs were done one at a time.

## 5. Questions for the Brain
1. Accept the 2 test-helper lines in `webui/` from step 1?
2. Accept 4b with 2 wrong proposals (both stopped by the Coordinator), or fix the bench (apply overrides inside
   `ask_agent` results) in a later task?
3. F6: keep it as a "safety" demo, or should C answer "no later flight" by code when `find_alternative_flights` is
   empty (a small check in C's tool step)?
4. Low-confidence routing to C stays OFF: OK?

## 6. Next step
- Yassine merges `feat/t26-demo-ready` into main.
- **T27** (web UI with the `ui-ux-pro-max` plugin): Promotions page (ShopNova owner), Hotel deals page (Atlas owner),
  "Check now" scan buttons, the urgent flag on approvals, the new C outcomes (replacement, hold, colleague, rebooking,
  wheelchair) and D's stock warnings in the Console ticket view.
- Then step 09 (memory, several requests in one message, bare "yes", T14f follow-ups) and RL5.

### P20's new rules (for Yassine's review)
- **R-RPL-01** Replacement for an urgent need — When a client urgently needs an item of an order that is late or arrived damaged (photo received), ShopNova may send a replacement of that item from its stock, as a new order at no cost. The replacement is offered only if the product is in stock, the order was not refunded or cancelled, and the client says yes to it. One replacement per order.
- **R-HLD-01** Hold an item for a client — ShopNova may keep (hold) units of a product in stock for a client for at most 3 days, for example while an urgent problem with their order is solved. A hold is made only if enough stock is left and the client says yes to it. Held units are not sold to others during the hold.
- **R-AST-01** Special help from a colleague — A hard or disputed case (the client disagrees with a decision, the case was sent back several times, or no rule fits) can be passed to a human colleague of the special help team, with the reason. The request is made only if the client says yes to it.
- **R-STK-01** Low stock warning — A product is short when 5 units or fewer are left, or when the stock covers less than 14 days of sales at the rate of the last 30 days. The availability team then warns the status team, so clients are not promised items that may run out.
- **R-PRM-01** Promotion for overstock — A product is overstocked when 50 units or more are in stock and the stock covers more than 180 days of sales at the rate of the last 30 days. The availability team may then propose a promotion of at most 20 percent. The shop owner must approve every promotion before it starts; a promotion never changes the price by itself.
- **AT-CAP-01** Hotel overbooking risk — A hotel is at risk of overbooking when a coming night has more rooms booked than the most rooms it ever had occupied on one night. The availability team then warns the status team, so clients of that night are not promised a room they may not get.
- **AT-DEAL-01** Deal for empty rooms — When a hotel has coming nights at 30 percent occupancy or less, the availability team may propose a deal of at most 20 percent on those nights. The owner must approve every deal before it starts; a deal never changes a price by itself.

### Conflict decisions (step 2, 7 files; step 5, README only)
- `coordinator.py`: kept main's T14 checks (negation, cancel, money-back words, proof flag, decline by code) AND P20's
  `special.py` / `atlas_special.py` checks in `review()`; `PROPOSAL_TOOLS` = union of both.
- `pipeline.py`: main's order / reason / message in the case for every company + P20's `client_said_yes`.
- `config.yaml`: both handover texts (`cancel_order` + `urgent_help`).
- `policies_shopnova.json` + `tests/test_policies.py`: 9 main rules + 5 P20 rules = 14, ids unique.
- `test_routing_by_company.py`, `test_server.py`: both sides' cases kept.
- Fingerprints renewed: Agent A prompt (P20's one `[HANDOVER: C]` line); tool schemas: main's hash after removing
  P20's 6 new tools.
- `ask_c` tools accept `booking_type` (main's registry passes it to every agent-running tool).
