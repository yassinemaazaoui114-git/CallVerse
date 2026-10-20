"""Prints a summary of the ShopNova database: what is in it, and what is AI-generated or scripted.

This is what we show for "explain your data / label AI-generated data".
It only READS the database (the one in use; run `python -m callverse.data.seed` first for a fresh one).
The numbers come from summary() in callverse/data/reports.py, the same function the local server's
GET /summary uses, so both always agree.

Usage (from the repo root):
    python -m scripts.data_summary        (or: python scripts/data_summary.py)
"""

import sys
from pathlib import Path

# Allow "python scripts/data_summary.py" as well as "python -m scripts.data_summary".
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from callverse.data.reports import summary  # noqa: E402


def main() -> None:
    s = summary()
    profile = s["company"]
    print(f"Company : {profile['name']} ({profile['domain']}, {profile['currency']}) "
          f"- profile ai_generated = {profile['ai_generated']}")
    print(f"Carriers: {', '.join(profile['carriers'])} | promise {profile['delivery_promise_days']['min']}-"
          f"{profile['delivery_promise_days']['max']} days | cities: {len(profile['cities_served'])}")

    print("\nRows per table (total | ai_generated | scripted)")
    for t, c in s["tables"].items():
        print(f"  {t:<14}{c['total']:>5} |{c['ai_generated']:>5} |{c['scripted']:>5}")

    print("\nOrders per status")
    for status, n in s["orders_per_status"].items():
        print(f"  {status:<18}{n:>4}")

    sc, gen = s["scripted_orders"], s["generated_orders"]
    print(f"\nScripted orders : {sc['count']} (ids {sc['first_id']}-{sc['last_id']})")
    print(f"Generated orders: {gen['count']} (ids {gen['first_id']}-{gen['last_id']})")
    late_open, late_delivered = s["late_not_delivered"], s["late_delivered"]
    print(f"Late orders     : {late_open + late_delivered} ({late_open} not delivered yet, "
          f"{late_delivered} delivered late); {s['late_over_5_not_delivered']} more than 5 days late and not delivered")
    print(f"Cash on delivery: {s['cash_on_delivery_unpaid']} orders not paid yet (paid = 0)")
    print(f"Total paid      : {s['total_paid_tnd']:.2f} TND")
    print(f"Refunds         : {s['refunds']['count']} rows, {s['refunds']['total_tnd']:.2f} TND")


if __name__ == "__main__":
    main()
