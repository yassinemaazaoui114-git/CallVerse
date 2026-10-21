"""Send the pending delivery notifications once and print them.

Usage (from the repo root):
    python -m scripts.run_notifier

It does not move the clock (see scripts/advance_clock.py) and does not reset the data.
Running it twice in a row sends nothing the second time (each subscription is sent once).
"""

import sys

from callverse import trace
from callverse.notifier.notifier import run_notifier
from callverse.slm.writer import warm_up


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    trace_path = trace.start_run()
    warm = warm_up()
    if not warm["ok"]:
        print(f"Warning: {warm['warning']} ({warm['error']})")
    messages = run_notifier()
    print(f"Messages sent: {len(messages)}")
    for m in messages:
        print(f"  order {m['order_id']} ({m['event']}, subscription {m['subscription_id']}) [{m['reply_source']}]: {m['text']}")
    print(f"Trace file : {trace_path}")


if __name__ == "__main__":
    main()
