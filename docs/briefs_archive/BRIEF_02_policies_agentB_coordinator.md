# Brief #2 — Policy KB + RAG, Agent B, Coordinator, Queues rules, delivery notifications

**Before starting:** the Brief #1 fixes must be applied and all tests green.

**Goal:** three scenarios run end to end (without Intake and SLM yet):
- **S1 – refund approved:** "My order 4512 is late, I want my money back." → A gives the facts → B proposes a
  refund of 59.90 TND citing rule R-REF-03 → the Coordinator checks and approves → a refund row is created.
- **S2 – send back:** B's first proposal has a wrong amount (69.90) → the Coordinator sends it back with the
  reason → B corrects → approved. (Use a demo flag `--inject-error` that makes B's first proposal wrong.)
- **S3 – notification:** "Where is my order 4512?" … "Yes, tell me when it's out for delivery." → A proposes
  a subscription → approved → `advance_clock.py` moves #4512 to "out_for_delivery" → the notifier sends the
  user a message.

**Why (for the presentation):** agents only *propose*; a rule-based Coordinator re-checks facts, policy and
user confirmation before anything changes. Policies live outside the agents (Policy KB) and are found by
meaning (RAG). Promises like "we'll notify you" are only made when a real subscription exists.

## 1. Policies — `callverse/kb/policies_shopnova.json` (AI-generated, labelled)
Each rule has: `id`, `title`, `text` (what the agent reads), and `condition` (what the Coordinator checks in code).
```
R-DEL-01  Delivery promise: orders should arrive by promised_date.
R-DEL-02  Late 1–5 days: apologise, give the new status, offer a delivery notification. No compensation.
R-REF-03  Late more than 5 days and not delivered: full refund on request (order cancelled).   condition: days_late > 5 and not delivered
R-REF-05  A refund never exceeds the amount paid.                                              condition: amount <= paid
R-RET-01  Returns within 14 days of delivery, unused item; refund after the item is received.
R-DMG-01  Damaged item: photo proof required, then replacement or refund.                      condition: proof_received
R-ESC-01  Refunds above 300 TND need approval from ShopNova finance (Layer 3).                condition: amount > 300 → layer3
R-NOT-01  Delivery notifications are available for: shipped, out_for_delivery, delivered.     condition: event in list
```
If the teammate's policies arrive later, they replace this file (same format).

## 2. Policy KB + RAG — `callverse/kb/`
- `build_index.py`: embed each rule's `title + text` with **`BAAI/bge-small-en-v1.5`** (sentence-transformers, CPU);
  save vectors (`.npy`) + metadata (`.json`). Vector store = a small numpy index with cosine similarity
  (simple to read; can be swapped for Chroma/FAISS later — keep it behind one function).
- `search.py`: `search_policy(query, k=3)` → top-k rules with id, title, text, score. Traced.
- New libraries allowed: `sentence-transformers`, `numpy`.

## 3. Proposal format — `callverse/proposals.py`
```json
{"proposal_id": "...", "agent": "B", "action": "refund",
 "params": {"order_id": 4512, "amount": 59.90},
 "rule_id": "R-REF-03",
 "facts_used": {"days_late": 6, "paid": 59.90, "delivered": false},
 "user_confirmed": true, "user_quote": "I want my money back"}
```
Actions for now: `refund`, `subscribe_update` (params: order_id, event).

## 4. Tools and allow-lists
- New tools: `get_refunds(order_id)` (read), `search_policy(query)` (read),
  `propose_refund(order_id, amount, rule_id, facts_used, user_confirmed, user_quote)` (proposal only),
  `propose_subscription(order_id, event, user_confirmed)` (proposal only),
  `ask_agent(agent, question)` (runs the other agent with the question and returns its answer + facts).
- Allow-lists:
  - `AGENT_A = [get_user, get_order, get_tracking, search_policy, propose_subscription]`
  - `AGENT_B = [get_order, get_refunds, search_policy, propose_refund, ask_agent]` (B asks A for delivery facts;
    B does **not** get `get_tracking`).
- Proposal tools only save the proposal and return `"submitted to Coordinator"`; they change no data.

## 5. Agent B — `callverse/agents/agent_b.py`
Prompt: Payment & Refund. Always find the rule with `search_policy` and cite its id; get delivery facts from A;
never promise money before the Coordinator's decision; compute nothing by memory (use tool results).
Uses the same `base_agent` loop.

## 6. Coordinator — `callverse/coordinator/coordinator.py` (rules only, no LLM)
`review(proposal) -> decision` with outcomes `approve`, `send_back(reason)`, `ask_user(question)`,
`ask_proof(what)`, `layer3(reason)`, `escalate(reason)`.
Checks, re-reading the data itself (never trusting `facts_used`):
1. **Facts match data:** order exists; amount ≤ paid; not already refunded; days_late recomputed from the DB.
2. **Policy allows:** `rule_id` exists and its `condition` is true on the real data; amount > 300 → `layer3`.
3. **User confirmed:** `user_confirmed` is true, else `ask_user`.
- Max 2 send-backs per case, then `escalate`.
- On `approve`: execute — insert into `refunds` (status "approved") or into `subscriptions`. Only the Coordinator writes.
- `layer3` uses a stub: approve if amount ≤ 500, else refuse (rule in config).
- Every check and its result is traced.

## 7. Queues (rules) — `callverse/queues/router.py`
`route(reason)`: `status` → A, `refund` → B, unknown → A. A's `[HANDOVER: B]` → route to B with the
conversation so far. (Intake will supply `reason` in Brief #3; for now the scenario script passes it.)

## 8. Notifications
- New table `subscriptions(id, order_id, event, status waiting|sent, created_at)`.
- New table `events(id, order_id, event, at)`.
- `advance_clock.py --order 4512 --event out_for_delivery`: updates the order status and inserts an event.
- `callverse/notifier.py`: for each new event, find waiting subscriptions, send a message to the user
  (fixed template for now; the SLM will write it in Brief #4), mark `sent`. Traced.
- Agent A's prompt: offer a notification only via `propose_subscription`, and only for the events in R-NOT-01.

## 9. Orchestrator + demo — `run_scenario.py`
`run_scenario.py S1|S2|S3 [--inject-error]`: runs the flow user → router → lead agent → Coordinator →
execute → reply (agent's text for now), prints a readable step list and the trace path.

## 10. Tests (no API calls for Coordinator tests)
- Coordinator: approve S1; amount > paid → send_back; already refunded → send_back; rule condition false →
  send_back; not confirmed → ask_user; amount > 300 → layer3; third send-back → escalate; subscription with
  an event not in R-NOT-01 → send_back.
- RAG: 5 questions return the right rule in the top 3 (e.g. "parcel a week late, money back" → R-REF-03).
- Registry: B cannot call `get_tracking`.

## Done when
S1, S2 and S3 run end to end with readable traces; all tests pass; then explain each new file in simple words.
