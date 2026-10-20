# T04 report — Pipeline: Intake → Queues router → Agent A (handover to B recorded)

## 1. In plain words
A client message now goes through the whole first part of the center: Intake turns it into a ticket,
a small rule table decides which agent should answer, and Agent A answers "where is my order?" questions.
Money, return and damage cases are sent to Agent B; B is not built yet, so for now the client gets a
fixed "passed to our refund team" answer and the handover is written in the trace. Several tickets can
wait in a queue, and the most urgent ones (high priority) are always served first.

## 2. Done
- `config.yaml`: `intake.main_reason_order` (approved precedence) and `queues` (layer L1 + 6 routes).
- `callverse/tools/registry.py`: `ALLOW_LISTS["INTAKE"] = ["get_order", "get_tracking"]`.
- `callverse/intake/intake.py`: facts read through `run_tool("INTAKE", ...)` (same gate and trace as the agents);
  `pick_main_reason()` = first reason of the precedence list present in the ticket. Severity unchanged.
- `callverse/intake/priority.py`: `time_pressure = 0` when the order is delivered.
- New `callverse/queues/router.py`: `route(ticket) -> {agent, layer, reason, priority_label}`, traced `route`.
- New `callverse/queues/queue.py`: `QueueManager.add/next` (heap on (priority rank, arrival)), traced `queue_add`, `queue_next`.
- New `callverse/pipeline.py`: `handle(message)` / `handle_ticket(ticket)` → `{ticket, route, answer, handover}`.
  Agent A gets the message + a short Intake note (order id, main reason). Handover traced `handover`, end traced `pipeline_done`.
- New `scripts/run_pipeline.py` (`"<message>"` or `--batch` with 5 demo messages written for the demo).
- New `tests/test_pipeline.py` (13 tests, no API calls).
- `README.md` and `docs/architecture.md` status lines.
- `tasks/NEXT.md` and `tasks/NEXT_PLATFORM.md` updated as the Brain asked (see Problems for NEXT_PLATFORM).

New files in simple words:
- `router.py` — a lookup table: "reason → agent". No AI, so it always gives the same answer.
- `queue.py` — a waiting line sorted by urgency, then by who came first.
- `pipeline.py` — glues Intake, router and Agent A together for one message.
- `run_pipeline.py` — the demo you run from the terminal.

## 3. Evidence
- Tests: **101/101 passed** (`python -m pytest -q`, 88 before + 13 new).
- Check 1 — `"Hi, where is my order 4512?"` → route **A (L1)**, main_reason order_status, MEDIUM 0.541.
  Answer: "Your order #4512 is currently **stuck at the depot** with Rapid-Poste. The promised delivery date
  was 2026-10-03, and it is **6 days late**." Handover none. Trace `traces/run_20261020_214406_924953.jsonl`.
- Check 2 — `"Order 4512 is a week late. I want my money back."` → reasons [refund_request, late_delivery],
  main_reason **refund_request**, HIGH 0.831, route **B**, handover **B** recorded. Trace `traces/run_20261020_214214_766804.jsonl`.
- Check 3 — `--batch` (trace `traces/run_20261020_214506_541058.jsonl`):

  | Arrival | Message (short) | Priority |
  |---|---|---|
  | 1 | status of 4510 | low 0.124 |
  | 2 | 4512 week late, money back | high 0.831 |
  | 3 | 4507 arrived damaged | medium 0.498 |
  | 4 | 4512 not arrived, nobody tells me | high 0.831 |
  | 5 | parcel, no order number | low 0.241 |

  Processing order: **#1 HIGH** (arrival 2, → B) · **#2 HIGH** (arrival 4, → A, "6 days late") ·
  **#3 MEDIUM** (arrival 3, damaged → B) · **#4 LOW** (arrival 1, → A, 4510 shipped, not late) ·
  **#5 LOW** (arrival 5, → A, asks for order number/email/phone). Every high before every low; ties by arrival.
  Trace steps in that run: route 5, queue_add 5, queue_next 5, handover 2, pipeline_done 5, tool_call 11.
- Regression — `scripts/eval_intake` run once: **19/20** reason sets (≥ 18 required), multi-reason 3/3,
  priority pair p01 OK, needs_llm 3. Nothing tuned.

## 4. Problems
- `tasks/NEXT_PLATFORM.md` in the "fresh clone" had **uncommitted local changes** (an older version pointing
  Dali's lane at T04). I replaced it with the Brain's values, keeping the P05 task file and approval from branch
  `platform`. NEXT.md was set READY then immediately IN PROGRESS → WAITING FOR REVIEW (only the final state is committed).
- First run of `run_pipeline` crashed on Windows: the LLM answer had a narrow no-break space the console
  code page (cp1252) cannot print. Fixed in the script with `sys.stdout.reconfigure(encoding="utf-8")`.
  `run_demo.py` has the same risk (not changed — not in this task).
- The damaged-item case gets the fixed text "passed to our refund team" (wording from the task); for a
  damaged lamp a "returns/claims team" wording may sound more natural once Agent B exists.
- The batch was run twice by mistake (one extra set of Groq calls); results identical in order.
- Eval 19/20 vs 18/20 in T03: the reason *sets* do not depend on this task's changes; the difference likely
  comes from the LLM fallback (3 messages) varying between runs.

## 5. Questions for the Brain
1. Should the handover answer depend on the reason (refund vs return vs damaged), or stay one fixed sentence until Agent B?
2. Agent A answers use Markdown bold (`**...**`). Keep it for now (the SLM will rewrite later), or ask for plain text?

## 6. Next step
Review T04 on `feature/pipeline`; then Agent B (proposals only) + Coordinator, plugged in where `pipeline.py`
now records the handover.

## Git
`git checkout main` → `git pull --ff-only` (already up to date, c2984b1) → `git checkout -b feature/pipeline` →
commit → `git push -u origin feature/pipeline`. Nothing merged into `main`.
