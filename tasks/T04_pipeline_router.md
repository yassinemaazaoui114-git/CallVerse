# T04 — Pipeline: Intake → Queues router → Agent A (handover to B recorded)

## Why
First end-to-end flow of the center: a client message becomes a labelled ticket (Intake), the Queues
send it to the right agent with rules (not an LLM: predictable, explainable), and Agent A answers status
questions. Refund / return / damaged cases are routed to Agent B (built later); for now the handover is recorded.

## Hard limits
- Start from the latest **`main`** (it contains Intake and the platform after T04a). Do **not** merge anything into `main`.
- Do not build Agent B, the Coordinator, the SLM or the notifier. Do not change Agent A's prompt rules.
- The Intake held-out test set is **spent**: you may re-run `scripts/eval_intake.py` once as a regression check,
  but never change anything to improve its score. Do not edit the examples or test files.
- No new libraries. No secrets in files.

## What to do
1. **Main reason by precedence** (approved): `config.yaml` → `intake.main_reason_order:
   [damaged_item, refund_request, return_item, late_delivery, order_status, other]`. `main_reason` = the first reason
   of this list that is present in the ticket (severity stays "most severe reason").
2. **Intake allow-list** (approved): in `tools/registry.py` add `ALLOW_LISTS["INTAKE"] = ["get_order", "get_tracking"]`;
   Intake reads facts through `run_tool("INTAKE", ...)` instead of calling the functions directly.
3. **Time pressure** (approved): `time_pressure = 0` when the order is delivered.
4. **Router** — `callverse/queues/router.py`: `route(ticket) -> {agent, layer, reason, priority_label}`.
   Rules in `config.yaml` → `queues.routes`: order_status → A, late_delivery → A, refund_request → B,
   return_item → B, damaged_item → B, other → A. Layer = L1 for A and B. Every routing decision traced (`route`).
5. **Queue** — `callverse/queues/queue.py`: `QueueManager` with `add(ticket)` and `next()`: high before medium before
   low, then first-come first-served. Traced (`queue_add`, `queue_next`).
6. **Pipeline** — `callverse/pipeline.py`: `handle(message) -> {ticket, route, answer, handover}`:
   Intake → router → if A: run Agent A with the message plus a short note of the ticket (order id, main reason);
   if A returns `handover: "B"`, or the route is B: record the handover (`answer` = "Your request is passed to our
   refund team.", `handover: "B"`) — Agent B comes in a later task.
7. **Scripts** — `scripts/run_pipeline.py "<message>"` prints ticket summary, route, answer, handover, trace path.
   `scripts/run_pipeline.py --batch` puts 5 demo messages in the queue (mixed priorities, written by you, not from any
   test file) and shows the processing order.
8. **Tests** (no API calls; stub the Intake models where needed): router rules for all 6 reasons; queue order
   (high > medium > low, then arrival); main-reason precedence ("late + refund" → refund_request → B);
   `run_tool("INTAKE", "get_user", ...)` is refused; time_pressure = 0 for a delivered order; pipeline flow with a fake LLM.
9. Update `README.md` / `docs/architecture.md` status lines.

## Checks (with numbers)
- `"Hi, where is my order 4512?"` → route **A**, answer says stuck at the depot and **6 days late**.
- `"Order 4512 is a week late. I want my money back."` → main_reason **refund_request**, route **B**, handover recorded.
- `--batch`: the processing order puts every high ticket before every low one (paste the order with priorities).
- Regression: `eval_intake` still **≥ 18/20** reason sets (run once, report; do not tune).
- All tests pass (report x/y).

## Time box and stop rule
2 hours. The Intake models download once (~1 GB) — expected. Stop and report if a check fails twice.

## Git (approved by Yassine, 2026-10-20)
`git checkout main` → `git pull --ff-only` → create branch **`feature/pipeline`** → commit → push `feature/pipeline`.
**Do not merge into `main`.** Write `tasks/T04_report.md` (6-section format) and set `tasks/NEXT.md` to WAITING FOR REVIEW.
