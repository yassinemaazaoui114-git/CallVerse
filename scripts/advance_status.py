"""Demo S3 helper: plays the carrier by changing an order's status.

Usage (from the repo root):
    python -m scripts.advance_status --order 4512 --status out_for_delivery

It calls set_order_status() on the real ShopNova database. If the new status is a notification
event (shipped, out_for_delivery, delivered), an `events` row is created; the notifier (a later
task) turns it into a message for clients who subscribed.
This is a demo control, not an agent action: agents can never change an order.
"""

import argparse

from callverse import trace
from callverse.data.writes import set_order_status


def main() -> None:
    parser = argparse.ArgumentParser(description="Change a ShopNova order status (demo S3).")
    parser.add_argument("--order", type=int, required=True, help="order number, e.g. 4512")
    parser.add_argument("--status", required=True, help="new status code, e.g. out_for_delivery")
    args = parser.parse_args()

    trace_path = trace.start_run()
    result = set_order_status(args.order, args.status)

    if "error" in result:
        print(f"Refused   : {result['error']}")
    else:
        print(f"Order {result['order_id']}: {result['old_status']} -> {result['new_status']}")
        print(f"Event     : {result['event'] or 'none (not a notification event)'}")
    print(f"Trace file: {trace_path}")


if __name__ == "__main__":
    main()
