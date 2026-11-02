"""Phase 1 (D6): build clean, anonymised real-score sets + splits.

CONV  = USS (sunnweiwei/user-satisfaction-simulation) MultiWOZ + SGD, English, travel dialogues,
        dialogue-level 1-5 rating given by ANNOTATORS (paper: 40 invited annotators, 3 per dialogue; the file has 3-7
        ratings per dialogue; we use the mean, rounded half up).
CSAT  = eCommerce Customer Service Satisfaction (Kaggle ddosad), CSAT 1-5 given by the CUSTOMER.
Extra (statistics only): Olist reviews (customer, Portuguese), TripAdvisor hotel reviews (customer).
"""
import re
import statistics

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from common import PROC, RAW, SEED, anonymise, save_json, write_jsonl

OUT = PROC / "real_scores"
OUT.mkdir(parents=True, exist_ok=True)

TRAVEL_MWOZ = ("Hotel-", "Train-", "Taxi-")
TRAVEL_KW = re.compile(r"\b(flights?|hotels?|bus(es)?|trains?|rental car|car rental|rent a car|airport|airline|"
                       r"one ?way|round ?trip|check.?in|room)\b", re.I)


def round_half_up(x):
    return int(np.floor(x + 0.5))


def parse_uss(name):
    sessions = (RAW / "uss" / f"{name}.txt").read_text(encoding="utf-8").strip().split("\n\n")
    out = []
    for i, s in enumerate(sessions):
        turns, actions, overall = [], [], None
        for line in s.split("\n"):
            p = line.split("\t")
            if len(p) < 2:
                continue
            role, text = p[0], p[1]
            act = p[2] if len(p) > 2 else ""
            if role == "USER" and text == "OVERALL":
                overall = [int(x) for x in p[3].split(",")]
                continue
            turn = {"role": "user" if role == "USER" else "agent", "text": anonymise(text)}
            if role == "USER" and len(p) > 3 and p[3]:
                turn["turn_sat"] = [int(x) for x in p[3].split(",")]
            turns.append(turn)
            actions.append(act)
        if overall is None:
            continue
        full = " ".join(t["text"] for t in turns)
        if name == "MWOZ":
            travel = any(a.startswith(TRAVEL_MWOZ) for a in actions)
        else:
            travel = bool(TRAVEL_KW.search(full))
        if not travel:
            continue
        mean = statistics.mean(overall)
        out.append({
            "id": f"uss_{name.lower()}_{i:04d}", "source": f"USS-{name}", "turns": turns,
            "n_user_turns": sum(t["role"] == "user" for t in turns),
            "ratings": overall, "rating_mean": mean, "score": round_half_up(mean),
            "scored_by": "annotators (USS, Sun et al. SIGIR 2021: 40 invited annotators)",
            "goal": next(t["text"] for t in turns if t["role"] == "user"),
        })
    return out


# ShopNova label mapping for Flipkart (Shopzilla) category / sub-category. Documented in D6_satisfaction.md.
SUB_MAP = {
    "Delayed": "late_delivery", "Priority delivery": "late_delivery",
    "Order status enquiry": "order_status", "Unable to track": "order_status",
    "Order Verification": "order_status", "General Enquiry|Order Related": "order_status",
    "Refund Enquiry": "refund_request", "Refund Related Issues": "refund_request",
    "COD Refund Details": "refund_request",
    "Reverse Pickup Enquiry": "return_item", "Return request": "return_item",
    "Exchange / Replacement": "return_item", "Return cancellation": "return_item",
    "Wrong": "return_item",
    "Damaged": "damaged_item", "Product related Issues": "damaged_item", "Missing": "damaged_item",
}


def map_reason(cat, sub):
    if f"{sub}|{cat}" in SUB_MAP:
        return SUB_MAP[f"{sub}|{cat}"]
    return SUB_MAP.get(sub, "other")


DELAY_BUCKETS = [(-0.1, 5, "0-5 min"), (5, 30, "5-30 min"), (30, 120, "30 min-2 h"),
                 (120, 480, "2-8 h"), (480, 1e9, "8 h+")]


def delay_bucket(m):
    if m is None or np.isnan(m) or m < 0:
        return "unknown"
    for lo, hi, lab in DELAY_BUCKETS:
        if lo < m <= hi:
            return lab
    return "unknown"


def build_csat():
    d = pd.read_csv(RAW / "ecommerce-customer-service-satisfaction" / "Customer_support_data.csv")
    rep = pd.to_datetime(d["Issue_reported at"], format="%d/%m/%Y %H:%M", errors="coerce")
    res = pd.to_datetime(d["issue_responded"], format="%d/%m/%Y %H:%M", errors="coerce")
    mins = (res - rep).dt.total_seconds() / 60
    names = set()
    for c in ("Agent_name", "Supervisor", "Manager"):
        for n in d[c].dropna().unique():
            names.update(n.split())
    rows = []
    for i, r in d.iterrows():
        rem = r["Customer Remarks"]
        rem = anonymise(rem.strip(), names) if isinstance(rem, str) and rem.strip() else None
        m = mins.iloc[i]
        rows.append({
            "id": f"csat_{i:05d}", "source": "Flipkart-CSAT (Kaggle ddosad)",
            "channel": r["channel_name"], "category": r["category"], "sub_category": r["Sub-category"],
            "reason": map_reason(r["category"], r["Sub-category"]),
            "response_minutes": None if pd.isna(m) or m < 0 else float(m),
            "delay_bucket": delay_bucket(m), "remark": rem,
            "tenure_bucket": r["Tenure Bucket"], "shift": r["Agent Shift"],
            "score": int(r["CSAT Score"]), "scored_by": "customer (post-contact CSAT survey)",
        })
    return pd.DataFrame(rows)


def split(df, name, key="score"):
    tr, rest = train_test_split(df, test_size=0.30, random_state=SEED, stratify=df[key])
    dv, te = train_test_split(rest, test_size=0.50, random_state=SEED, stratify=rest[key])
    for part, x in (("train", tr), ("dev", dv), ("test", te)):
        write_jsonl(x.to_dict("records"), OUT / f"{name}_{part}.jsonl")
    return {"train": len(tr), "dev": len(dv), "test": len(te)}


def main():
    info = {}
    conv = parse_uss("MWOZ") + parse_uss("SGD")
    cdf = pd.DataFrame(conv)
    # scores 1 and 5 are too rare to stratify alone; merge them into neighbours for the stratify key only
    cdf["strat"] = cdf["score"].clip(2, 4)
    info["conv"] = {"n": len(cdf), "by_source": cdf.source.value_counts().to_dict(),
                    "score_dist": cdf.score.value_counts().sort_index().to_dict(),
                    "splits": split(cdf, "conv", key="strat")}

    csat = build_csat()
    write_jsonl(csat.to_dict("records"), OUT / "csat_all.jsonl")
    txt = csat[csat.remark.notna()].copy()
    info["csat_all"] = {"n": len(csat), "score_dist": csat.score.value_counts().sort_index().to_dict(),
                        "reason_dist": csat.reason.value_counts().to_dict(),
                        "negative_or_missing_response_time": int(csat.response_minutes.isna().sum())}
    info["csat_text"] = {"n": len(txt), "score_dist": txt.score.value_counts().sort_index().to_dict(),
                         "splits": split(txt, "csat_text")}
    info["csat_all"]["splits"] = split(csat, "csat_allrows")

    # Extra real-score sets, statistics only (not used for tuning).
    o = pd.read_csv(RAW / "brazilian-ecommerce" / "olist_order_reviews_dataset.csv")
    od = pd.read_csv(RAW / "brazilian-ecommerce" / "olist_orders_dataset.csv")
    o = o.merge(od, on="order_id", how="left")
    late = (pd.to_datetime(o.order_delivered_customer_date) - pd.to_datetime(o.order_estimated_delivery_date)).dt.days
    o["days_late"] = late
    o[["review_id", "review_score", "days_late", "order_status"]].to_csv(OUT / "olist_scores_delay.csv", index=False)
    info["olist"] = {"n": len(o), "with_comment": int(o.review_comment_message.notna().sum()),
                     "score_dist": o.review_score.value_counts().sort_index().to_dict()}
    t = pd.read_csv(RAW / "trip-advisor-hotel-reviews" / "tripadvisor_hotel_reviews.csv")
    info["tripadvisor"] = {"n": len(t), "score_dist": t.Rating.value_counts().sort_index().to_dict()}
    a = pd.read_csv(RAW / "airline-reviews" / "Airline_review.csv")
    info["airline_reviews"] = {"n": len(a), "overall_rating_dist": a.Overall_Rating.astype(str).value_counts().to_dict()}
    save_json(info, OUT / "build_info.json")
    print(info)


if __name__ == "__main__":
    main()
