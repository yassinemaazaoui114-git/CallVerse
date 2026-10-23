"""Agent E: which workload properties can REAL e-commerce data support? (Olist public dataset, orders + reviews)

    python -m real_data.olist_workload --raw <folder with olist_orders_dataset.csv, olist_order_reviews_dataset.csv>
        --out results/real_olist

Olist = Brazilian e-commerce public dataset (Kaggle "olistbr/brazilian-ecommerce", CC BY-NC-SA 4.0), ~99k orders
2016-2018. It has ORDER timestamps, not support-contact logs. So:
  SUPPORTED (used):   demand shape by hour / weekday, day-to-day volatility, delivery lateness, cancellations,
                      and how REAL review scores fall with lateness (checks the SIM-CSAT formula's shape).
  NOT SUPPORTED:      contact arrival rates, queue waiting times, abandonment, handle times (no contact logs).
Outputs are aggregates only (no ids, no text): workload.json, e_calibration_olist.json, workload.png.
"""

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

FMT = "%Y-%m-%d %H:%M:%S"


def ts(v):
    try:
        return datetime.strptime(v, FMT) if v else None
    except ValueError:
        return None


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def best_window(hourly, width=8):
    """Start hour of the busiest `width`-hour window (the simulated day is 8 hours)."""
    sums = [sum(hourly[(h + k) % 24] for k in range(width)) for h in range(24)]
    return int(np.argmax(sums))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", default="results/real_olist")
    a = ap.parse_args(argv)
    raw, out = Path(a.raw), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    orders = read(raw / "olist_orders_dataset.csv")
    reviews = read(raw / "olist_order_reviews_dataset.csv")

    purchase = [ts(o["order_purchase_timestamp"]) for o in orders]
    purchase = [p for p in purchase if p]
    hourly = np.bincount([p.hour for p in purchase], minlength=24).astype(float)
    weekday = np.bincount([p.weekday() for p in purchase], minlength=7).astype(float)
    daily = Counter(p.date() for p in purchase)
    # steady period only (the first and last months of the dataset are ramp-up / cut-off)
    days = sorted(daily)
    steady = [daily[d] for d in days if datetime(2017, 6, 1).date() <= d <= datetime(2018, 7, 31).date()]
    steady = np.array(steady, float)
    peak_day = max(daily, key=daily.get)

    status = Counter(o["order_status"] for o in orders)
    late, delay_days, delivered_days = {}, [], []
    for o in orders:
        d, e, p = ts(o["order_delivered_customer_date"]), ts(o["order_estimated_delivery_date"]), ts(
            o["order_purchase_timestamp"])
        if d and e:
            dd = (d - e).total_seconds() / 86400
            late[o["order_id"]] = dd
            delay_days.append(dd)
            if p:
                delivered_days.append((d - p).total_seconds() / 86400)
    delay = np.array(delay_days)

    # real satisfaction vs lateness (one score per order; orders with several reviews averaged)
    by_order = defaultdict(list)
    for r in reviews:
        by_order[r["order_id"]].append(int(r["review_score"]))
    buckets = [(-1e9, -7, "early >7d"), (-7, 0, "early 0-7d"), (0, 3, "late 0-3d"), (3, 7, "late 3-7d"),
               (7, 14, "late 7-14d"), (14, 1e9, "late >14d")]
    score_by_delay = {}
    for lo, hi, name in buckets:
        s = [np.mean(by_order[o]) for o, dd in late.items() if lo < dd <= hi and o in by_order]
        score_by_delay[name] = {"n_orders": len(s), "mean_score": round(float(np.mean(s)), 3) if s else None,
                                "share_1_2_stars": round(float(np.mean(np.array(s) <= 2)), 3) if s else None}
    undelivered = [np.mean(by_order[o["order_id"]]) for o in orders
                   if o["order_status"] in ("canceled", "unavailable") and o["order_id"] in by_order]
    with_comment = [int(r["review_score"]) for r in reviews if r["review_comment_message"].strip()]
    all_scores = [int(r["review_score"]) for r in reviews]

    start = best_window(hourly)
    window = [hourly[(start + k) % 24] for k in range(8)]
    res = {
        "source": "Olist public dataset (Kaggle olistbr/brazilian-ecommerce, CC BY-NC-SA 4.0); ORDER data, not "
                  "support-contact logs",
        "n_orders": len(orders), "n_reviews": len(reviews),
        "period": [str(min(purchase).date()), str(max(purchase).date())],
        "hourly_share": [round(x / hourly.sum(), 4) for x in hourly],
        "weekday_share_mon_to_sun": [round(x / weekday.sum(), 4) for x in weekday],
        "busiest_8h_window_start_hour": start,
        "busiest_8h_window_share_of_day": round(sum(window) / hourly.sum(), 4),
        "peak_to_mean_within_8h_window": round(max(window) / np.mean(window), 3),
        "daily_orders_steady_period": {"mean": round(float(steady.mean()), 1), "cv": round(float(steady.std() /
                                       steady.mean()), 3), "p95_over_mean": round(float(np.percentile(steady, 95) /
                                       steady.mean()), 3), "max_over_mean": round(float(steady.max() / steady.mean()), 3)},
        "peak_day": {"date": str(peak_day), "orders": daily[peak_day]},
        "order_status_share": {k: round(v / len(orders), 4) for k, v in status.most_common()},
        "delivery": {"n_delivered_with_estimate": len(delay), "late_share": round(float((delay > 0).mean()), 4),
                     "late_over_3d_share": round(float((delay > 3).mean()), 4),
                     "days_purchase_to_delivery_p50": round(float(np.median(delivered_days)), 1),
                     "days_late_p90_given_late": round(float(np.percentile(delay[delay > 0], 90)), 1)},
        "review_score_vs_lateness": score_by_delay,
        "review_score_canceled_or_unavailable": round(float(np.mean(undelivered)), 3) if undelivered else None,
        "review_score_distribution_all": {k: round(v / len(all_scores), 4) for k, v in sorted(Counter(all_scores).items())},
        "review_score_distribution_with_comment": {k: round(v / len(with_comment), 4)
                                                   for k, v in sorted(Counter(with_comment).items())},
        "not_supported_by_this_data": ["support-contact arrival rates", "queue waiting times", "abandonment",
                                       "handle/service times", "intent mix of support contacts"],
    }
    (out / "workload.json").write_text(json.dumps(res, indent=2))
    cal = {"source": "olist_workload.py: hourly demand shape of the busiest 8h window (order timestamps). Queue mix, "
                     "service times, patience: NOT from data (simulator assumptions kept).",
           "hourly_profile_8h": [round(x / np.mean(window), 4) for x in window],
           "window_start_hour": start}
    (out / "e_calibration_olist.json").write_text(json.dumps(cal, indent=2))
    plot(res, cal, out)
    print(json.dumps({k: res[k] for k in ("busiest_8h_window_start_hour", "peak_to_mean_within_8h_window",
                                          "daily_orders_steady_period", "delivery", "review_score_vs_lateness")},
                     indent=1))


def plot(res, cal, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from env.callcenter_env import profile
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4))
    x = np.linspace(0, 1, 97)
    sim = np.array([profile(v) for v in x])
    a1.plot(x * 8, sim / sim.mean(), label="simulator (assumed)")
    hp = np.array(cal["hourly_profile_8h"])
    a1.plot(np.arange(8) + 0.5, hp / hp.mean(), "o-", label=f"Olist orders {cal['window_start_hour']}:00 +8h")
    a1.set_xlabel("hour of the simulated day")
    a1.set_ylabel("relative demand (mean 1)")
    a1.set_title("Demand shape: assumed vs real (orders)")
    a1.legend()
    names = list(res["review_score_vs_lateness"])
    vals = [res["review_score_vs_lateness"][n]["mean_score"] for n in names]
    a2.bar(names, vals)
    a2.set_ylim(1, 5)
    a2.set_title("Real review score vs delivery lateness (Olist)")
    a2.tick_params(axis="x", rotation=30, labelsize=8)
    fig.tight_layout()
    fig.savefig(out / "workload.png", dpi=110)


if __name__ == "__main__":
    main()
