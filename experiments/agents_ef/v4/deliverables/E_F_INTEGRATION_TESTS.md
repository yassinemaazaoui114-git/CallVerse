# E/F integration tests (Worker D)

All tests are **offline** and isolated:
- no API calls;
- temporary databases only;
- no file in `callverse/` changed;
- no production queue touched.

Run from `experiments/agents_ef/`: `python -m pytest v4/d/tests -q`. Result: **28 passed**.

## What the prototype really looks like (audit)

| Item | Prototype (`callverse/`, `config.yaml`) | Agent E research model | Consequence |
|---|---|---|---|
| Queues | **one** priority queue (`queues/queue.py`: high > medium > low, then arrival) | 4 categories, each with its own staffed sessions | E's 4-pool staffing is a **research abstraction**. There is no prototype contract for sessions per category |
| Routing | `queues.routes`: order_status / late_delivery / other → Agent A; refund_request / return_item / damaged_item → Agent B | order_status / late_delivery → A_status; refund_request / return_item → B_refund; **damaged_item → C_urgent**; other → D_availability | "Urgent" = damaged item. In the prototype it goes to Agent B. Mapping in `v4/d/bridge.py`; `check_mapping()` is tested against `config.yaml` |
| Ticket fields E needs | Intake ticket: `main_reason`, `priority_label`, `priority_score`, `ticket_id` | same fields; no message text | Agent E sees aggregates only |
| Closed conversation | trace JSONL; `pipeline_done` marks the end | Agent F reads it as is | No prototype change needed |

**Intake errors flow into Agent E's queue counts.** The fixture is real Intake output with `use_llm=False` (`v4/d/fixtures/intake_tickets.json`, written test messages):
- "Do you sell phone cases for the new model?" → `return_item` (counted as B_refund);
- "Bonjour, où en est ma commande 4514 ?" → `other`;
- "I want to return order 4511" → `refund_request`.

Agent E's input is only as good as Intake's classification. With the LLM fallback enabled, the result is NOT VERIFIED (no API key).

## Tests

| File | What it shows |
|---|---|
| `test_bridge.py` (16) | Every prototype reason maps to an Agent E queue. The **independent validator** (written from ConfigV3's rules, not from E's code) gives the same allowed set as `EnvV3.action_mask` for all 17 actions on every state of a random-play day in **all 13 families**. The urgent minimum (queue C ≥ 2), capacity and budget refusals come with reasons. The ticket book orders tickets like the prototype queue, and its snapshot contains no message text |
| `test_fe_contract.py` (5) | The F → E reward channel opens only if Agent F's eligibility flag **and** a validation card that passes the V3 gate agree. Either one alone is refused. Bad scores are refused. Units are those of EnvV3's `(5 − s) / 4` shortfall |
| `test_integration_e.py` (5) | **Ticket → queue statistics → RL proposal → independent check → simulated update**, using the real Intake fixture and a trained V3 Dueling DDQN. The adapter does not mutate its input, the proposal is independently valid, and queue C stays ≥ 2. A missing checkpoint falls back to MPC and states the reason. **Closed loop**: a full simulated day on tracking_spike, severe_overload and combined_shock, where every one of 96 proposals passes the independent check; 0 invalid proposals, 0 HIGH tickets on fallback, budget kept |
| `test_integration_f.py` (2) | **Closed conversation → Agent F → quality flags → rule/knowledge warnings → owner report → F → E contract**, on 30 held-out corpus traces. Every evidence ref points at the right trace line. Non-English conversations get no score. Nothing is eligible for E's reward, and the contract refuses all 30. Agent F changes neither the policy file nor the traces (hash check) |

## Demo

`python -m v4.d.demo_end_to_end [--run <run_id>]`. Last run used the V3 Dueling DDQN s0:
- **Part 1:** 3 decision steps, all three proposals "move 1 session D_availability → C_urgent" as damaged-item tickets queue up; independent check OK; 0.9–13.8 ms per decision.
- **Part 2:** 6 demo traces. Two French conversations have their score withheld. One escalated case gets `claim_false` ×2, `sent_back` and `escalated`. Owner report: `v4/d/results/demo_owner_report.md`.
- **Part 3:** 0 reward cells; 6/6 refused, with the gate's reasons.

## Not verified

- Behaviour inside the running prototype server: no wiring into `callverse/` is allowed without an approved task.
- Intake with its LLM fallback.
- Real (non-scripted) closed conversations: no `pipeline_done` trace exists outside the scripted corpus.
