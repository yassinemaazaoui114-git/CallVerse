"""Run the pipeline: Intake -> Router -> Agent A or Agent B (B may submit a refund proposal).

Usage (from the repo root):
    python -m scripts.run_pipeline "Hi, where is my order 4512?"
    python -m scripts.run_pipeline --batch     # 5 demo messages through the priority queue
"""

import sys

from callverse import pipeline, trace
from callverse.data.seed import seed
from callverse.intake import intake
from callverse.queues.queue import QueueManager
from callverse.slm.writer import warm_up

# Written for this demo (not from any test file): mixed reasons and priorities.
BATCH = [
    "Hello, can you tell me the status of order 4510?",
    "Order 4512 is a week late. I want my money back.",
    "My order 4507 arrived damaged, the box was crushed and the lamp is broken.",
    "My order 4512 still has not arrived and nobody tells me anything!",
    "Where is my parcel? I have no order number with me.",
]


def show(out: dict) -> None:
    t, r = out["ticket"], out["route"]
    print(f"Ticket   : {t['ticket_id']}  order {t['order_id']}  reasons {[x['reason'] for x in t['reasons']]}")
    print(f"           main_reason {t['main_reason']}  priority {t['priority_label'].upper()} {t['priority_score']}")
    print(f"Route    : agent {r['agent']} ({r['layer']})")
    print(f"Handover : {out['handover'] or 'none'}" + (f"  ({out['handover_text']})" if out['handover_text'] else ""))
    print(f"Agent text (trace only, not sent): {out['agent_text']}")
    print(f"REPLY    : {out['final_reply']}   [{out['reply_source']}]")
    print(f"Proposal : {out['proposal'] or 'none'}")
    d = out["decision"]
    print(f"Decision : {d['outcome']} {d['proposal_id']} ({d['reason']})" if d else "Decision : none")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")   # LLM answers may hold characters the Windows console code page lacks
    seed()                         # same placeholder data on every run
    trace_path = trace.start_run()
    intake.load_models()
    warm = warm_up()                # T09: load the SLM now, not during the first reply
    if not warm["ok"]:
        print(f"Warning: {warm['warning']} ({warm['error']})")

    if sys.argv[1:] == ["--batch"]:
        queue = QueueManager()
        for text in BATCH:
            ticket = intake.process(text)
            queue.add(ticket)
            print(f"queued  {ticket['priority_label']:6s} {ticket['priority_score']:.3f}  {text}")
        print("\nProcessing order:")
        n = 0
        while (ticket := queue.next()) is not None:
            n += 1
            print(f"\n#{n} [{ticket['priority_label'].upper()}]")
            show(pipeline.handle_ticket(ticket))
    else:
        message = " ".join(sys.argv[1:]) or "Hi, where is my order 4512?"
        print(f"Client   : {message}")
        show(pipeline.handle(message))

    print(f"\nTrace file : {trace_path}")


if __name__ == "__main__":
    main()
