"""Run Intake on one message and print the ticket.

Usage (from the repo root):
    python -m scripts.run_intake "Hi, my order 4512 is a week late, I want my money back!"
"""

import sys
import time

from callverse import trace
from callverse.data.seed import seed
from callverse.intake import intake


def main() -> None:
    message = " ".join(sys.argv[1:]) or "Hi, my order 4512 is a week late, I want my money back!"

    seed()                          # same placeholder data on every run
    trace_path = trace.start_run()

    start = time.perf_counter()
    intake.load_models()
    load_seconds = time.perf_counter() - start

    t = intake.process(message)

    print(f"Message    : {t['text']}")
    print(f"Ticket     : {t['ticket_id']}")
    print(f"Order / email / phone : {t['order_id']} / {t['email']} / {t['phone']}")
    print("Reasons    :")
    for r in t["reasons"]:
        score = f"{r['score']:.3f}" if r["score"] is not None else "LLM"
        print(f"   - {r['reason']:15s} score {score}   <- {r['sentence']!r}")
    print(f"Main reason: {t['main_reason']}   (needs_llm: {t['needs_llm']})")
    print(f"Emotion    : {t['emotion']['label']} ({t['emotion']['score']})   "
          f"Sentiment: {t['sentiment']['label']} ({t['sentiment']['score']})")
    print(f"Facts      : {t['facts']}")
    print(f"Priority   : {t['priority_label'].upper()} {t['priority_score']}  = 0.6 x severity {t['severity']}"
          f" + 0.25 x time {t['time_pressure']} + 0.15 x emotion {t['emotion_intensity']}")
    print(f"Style      : {t['style']}")
    print(f"Time       : {t['seconds']} s (models loaded in {load_seconds:.1f} s)")
    print(f"Trace file : {trace_path}")


if __name__ == "__main__":
    main()
