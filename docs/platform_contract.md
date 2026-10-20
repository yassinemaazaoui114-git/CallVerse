# Platform contract — ShopNova (for the platform builder)

What the CallVerse agents expect from the ShopNova mock platform. Keep these names and shapes
so the agents work without code changes. All amounts in **TND**. Demo date: **2026-10-09**.

## 1. What already runs (prototype repo)
Shared LLM layer (Groq `gpt-oss-120b`, backup `gpt-oss-20b`), placeholder SQLite database
(`callverse/data/seed.py`), 3 read tools, per-agent allow-lists, Agent A, traces, tests.
Not built yet: policies + search, Agent B, Coordinator, notifications, Intake, SLM, Simulator.

## 2. Tables (same structure as the placeholder)
- `users(id, name, email, phone)`
- `products(id, name, price, stock)`
- `orders(id, user_id, items[JSON], total, paid, status, order_date, promised_date, delivered_date, carrier, tracking_number)`
- `refunds(id, order_id, amount, status)`
- coming with notifications: `subscriptions(id, order_id, event, status waiting|sent, created_at)`,
  `events(id, order_id, event, at)`

## 3. How agents call tools
Plain Python functions + OpenAI-style JSON definitions (function calling). No LangChain.
Each call passes through a registry that checks the agent's allow-list.

```python
get_order(order_id: int) -> dict        # the order, or {"error": "..."}
```
```json
{"type": "function", "function": {"name": "get_order",
  "description": "Get a ShopNova order: items, total, amount paid, status, dates, carrier, tracking number.",
  "parameters": {"type": "object", "properties": {"order_id": {"type": "integer"}}, "required": ["order_id"]}}}
```
Read tools today: `get_user(email|phone|user_id)`, `get_order(order_id)`, `get_tracking(order_id)` (adds `days_late`).

## 4. How the Coordinator approves (to be built)
`review(proposal)` → `approve | send_back | ask_user | ask_proof | layer3 | escalate`.
On **approve**, only the Coordinator writes: a `refunds` row with status `"approved"`, or a `subscriptions`
row with status `"waiting"`. The platform should offer these write functions:
`create_refund(order_id, amount, rule_id, proposal_id)`, `create_subscription(order_id, event)`,
and emit `events` when an order status changes (shipped, out_for_delivery, delivered).

## 5. Policies — needed from the platform
Format per rule: `id`, `title`, `text` (what agents read), `condition` (what the Coordinator checks in code).
Rules the prototype needs (draft): R-DEL-01 delivery promise · R-DEL-02 late 1–5 days: apologise + offer
notification · R-REF-03 late > 5 days and not delivered: full refund on request · R-REF-05 refund ≤ amount paid ·
R-RET-01 returns within 14 days · R-DMG-01 damaged item: photo proof · R-ESC-01 refunds > 300 TND need
finance (Layer 3) · R-NOT-01 notifications for shipped, out_for_delivery, delivered.

## 6. Scripted cases (placeholder data)
4512 Sara, 59.90 TND paid, promised 2026-10-03, stuck at depot, 6 days late (main demo) · 4506 already
refunded (189 TND) · 4507 delivered 2 days late · 4510, 4513 shipped on time · 4511 processing ·
4514 cash on delivery (0 paid) · 4505, 4508, 4509 delivered.

## 7. Other settings
Layer 3 stub: refunds > 300 TND go to finance; stub approves ≤ 500 TND, refuses above.
Agent IDs: `A`, `B` (`C`, `D` later). Vector store: small numpy index (cosine) on `bge-small-en-v1.5`,
swappable for Chroma/FAISS.
Demo: S1 refund approved · S2 wrong amount sent back then corrected · S3 delivery notification after
advancing the clock · (if time) Atlas hotel cancelled with agent C.
