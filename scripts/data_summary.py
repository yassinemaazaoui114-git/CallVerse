"""Prints a summary of the ShopNova database: what is in it, and what is AI-generated or scripted.

This is what we show for "explain your data / label AI-generated data".
It only READS the database (the one in use; run `python -m callverse.data.seed` first for a fresh one).

Usage (from the repo root):
    python -m scripts.data_summary        (or: python scripts/data_summary.py)
"""

import json
import sys
from contextlib import closing
from pathlib import Path

# Allow "python scripts/data_summary.py" as well as "python -m scripts.data_summary".
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from callverse.data.db import connect  # noqa: E402
from callverse.tools.shopnova_tools import get_tracking  # noqa: E402

PROFILE_PATH = Path(__file__).resolve().parent.parent / "callverse" / "data" / "company_profile.json"
TABLES = ("users", "products", "orders", "refunds", "subscriptions", "events")


def main() -> None:
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    print(f"Company : {profile['name']} ({profile['domain']}, {profile['currency']}) "
          f"- profile ai_generated = {profile['ai_generated']}")
    print(f"Carriers: {', '.join(profile['carriers'])} | promise {profile['delivery_promise_days']['min']}-"
          f"{profile['delivery_promise_days']['max']} days | cities: {len(profile['cities_served'])}")

    with closing(connect()) as con:
        print("\nRows per table (total | ai_generated | scripted)")
        for t in TABLES:
            total, ai, scripted = con.execute(
                f"SELECT COUNT(*), COALESCE(SUM(ai_generated), 0), COALESCE(SUM(scripted), 0) FROM {t}").fetchone()
            print(f"  {t:<14}{total:>5} |{ai:>5} |{scripted:>5}")

        print("\nOrders per status")
        for status, n in con.execute("SELECT status, COUNT(*) FROM orders GROUP BY status ORDER BY COUNT(*) DESC"):
            print(f"  {status:<18}{n:>4}")

        scripted = con.execute("SELECT COUNT(*), MIN(id), MAX(id) FROM orders WHERE scripted = 1").fetchone()
        generated = con.execute("SELECT COUNT(*), MIN(id), MAX(id) FROM orders WHERE scripted = 0").fetchone()
        print(f"\nScripted orders : {scripted[0]} (ids {scripted[1]}-{scripted[2]})")
        print(f"Generated orders: {generated[0]} (ids {generated[1]}-{generated[2]})")

        ids = [r[0] for r in con.execute("SELECT id FROM orders WHERE status != 'cancelled'")]
        cod = con.execute("SELECT COUNT(*) FROM orders WHERE paid = 0 AND status != 'cancelled'").fetchone()[0]
        paid = con.execute("SELECT SUM(paid) FROM orders").fetchone()[0]
        refunds = con.execute("SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM refunds").fetchone()

    tracking = [get_tracking(i) for i in ids]  # days_late is computed by the tool, as agents see it
    late_open = sum(1 for t in tracking if t["days_late"] > 0 and not t["delivered"])
    late_delivered = sum(1 for t in tracking if t["days_late"] > 0 and t["delivered"])
    print(f"Late orders     : {late_open + late_delivered} ({late_open} not delivered yet, "
          f"{late_delivered} delivered late); {sum(1 for t in tracking if t['days_late'] > 5 and not t['delivered'])}"
          f" more than 5 days late and not delivered")
    print(f"Cash on delivery: {cod} orders not paid yet (paid = 0)")
    print(f"Total paid      : {paid:.2f} TND")
    print(f"Refunds         : {refunds[0]} rows, {refunds[1]:.2f} TND")


if __name__ == "__main__":
    main()
