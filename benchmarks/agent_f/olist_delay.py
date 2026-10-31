"""Real anchor: Olist review score vs delivery delay (ShopNova sample). Prints the DELAY_TABLE for Agent F.

Run: python -m benchmarks.agent_f.olist_delay
"""
import datetime as dt
import json
from collections import defaultdict

from benchmarks.agent_f.common import ROOT

BUCKETS = [0, 2, 5, 10, 10_000]   # upper bounds in days late (<=0 = on time)


def rows():
    d = json.loads((ROOT / "callverse/data/real/shopnova_olist_sample.json").read_text(encoding="utf-8"))
    orders = {o["id"]: o for o in d["orders"]}
    for r in d["reviews"]:
        o = orders.get(r["order_id"])
        if o and o.get("delivered_date") and o.get("promised_date") and not r.get("ai_generated"):
            late = (dt.date.fromisoformat(o["delivered_date"]) - dt.date.fromisoformat(o["promised_date"])).days
            yield late, r["score"]


def table():
    b = defaultdict(list)
    for late, s in rows():
        b[next(u for u in BUCKETS if late <= u)].append(s)
    return [(u, round(sum(b[u]) / len(b[u]), 2), len(b[u])) for u in BUCKETS if b[u]]


if __name__ == "__main__":
    for u, mean, n in table():
        print(f"days_late <= {u}: mean {mean}  n={n}")
