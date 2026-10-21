"""Move the simulation clock forward (story S3) or reset it, and print what happened.

Usage (from the repo root):
    python scripts/advance_clock.py --hours 30     move 30 simulated hours forward, play due timeline events
    python scripts/advance_clock.py --reset        back to 2026-10-09 09:00, timeline undone

The timeline (callverse/data/scenario_timeline.json) moves order 4510: +24 h out_for_delivery, +30 h delivered.
Notifications are not sent here: pending ones are listed so you can see what the notifier will send.
"""

import argparse
import sys
from pathlib import Path

# Allow "python scripts/advance_clock.py" as well as "python -m scripts.advance_clock".
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from callverse import trace  # noqa: E402
from callverse.data import clock  # noqa: E402
from callverse.data.reports import get_pending_notifications  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Move or reset the ShopNova simulation clock.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--hours", type=float, help="simulated hours to move forward (> 0)")
    group.add_argument("--reset", action="store_true", help="back to the start, timeline undone")
    args = parser.parse_args()

    trace_path = trace.start_run()
    if args.reset:
        r = clock.reset()
        print(f"Clock reset to {r['now']}; orders restored: {r['orders_restored']}")
    else:
        r = clock.advance(args.hours)
        if "error" in r:
            sys.exit(f"Refused: {r['error']}")
        print(f"Clock: {r['from']}  ->  {r['to']}")
        if not r["applied"]:
            print("Timeline events applied: none")
        for e in r["applied"]:
            if e["applied"]:
                print(f"  {e['at']}  order {e['order_id']}: {e['old_status']} -> {e['status']}  (events row #{e['event_row']})")
            else:
                print(f"  {e['at']}  order {e['order_id']} -> {e['status']}: REFUSED ({e['reason']})")
    pending = get_pending_notifications()
    print(f"Pending notifications (not sent yet): {len(pending)}")
    for n in pending:
        print(f"  subscription #{n['subscription_id']}: order {n['order_id']} {n['event']} on {n['event_at']}"
              f" for {n['user']['name']}")
    print(f"Trace file: {trace_path}")


if __name__ == "__main__":
    main()
