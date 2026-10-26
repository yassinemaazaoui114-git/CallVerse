"""Phase 4: write simulator/real_numbers.json, rubric.json and calibration.json from the result files.
Usage: python p4_build_kit.py   (writes real_numbers.json and rubric.json; calibration files come from p6_followup.py)"""
import sys

from common import RESULTS, ROOT, load_json, save_json
from llm import short

SIM = ROOT / "simulator"
TW = "Customer Support on Twitter (Kaggle thoughtvector), CC BY-NC-SA 4.0, https://www.kaggle.com/datasets/thoughtvector/customer-support-on-twitter"
FK = "eCommerce Customer Service Satisfaction (Kaggle ddosad), licence to verify, https://www.kaggle.com/datasets/ddosad/ecommerce-customer-service-satisfaction"
MC = ("County Medi-Cal Call Center Data, CA Dept. of Health Care Services via CHHS Open Data, https://data.chhs.ca.gov/dataset/county-medi-cal-call-center-data "
      "(CHHS Terms of Use: free use and distribution with attribution; the data.ca.gov listing says Creative Commons Attribution)")
USS = "USS (github sunnweiwei/user-satisfaction-simulation), licence to verify"


def main(models):
    p2 = load_json(RESULTS / "p2_real_numbers_and_profile.json")
    p1 = load_json(RESULTS / "p1_real_stats.json")
    acc = load_json(RESULTS / "p2_mapping_handcheck.json")["v2_rules_fresh_seed2024"]["accuracy"]
    rn = {
        "reason_mix": {
            "shopnova": {"values": p2["flipkart_reason_mix_mapped"], "source": FK,
                         "note": "company categories mapped to ShopNova labels (see D6_satisfaction.md)",
                         "alternative_twitter_keyword_rules": p2["reason_mix_twitter_keyword_rules"]["shopnova"]},
            "atlas": {"values": p2["reason_mix_twitter_keyword_rules"]["atlas"], "source": TW,
                      "note": f"keyword rules, hand-checked accuracy {acc:.0%} on 50 messages"},
        },
        "arrivals_share_by_hour": {"values": p2["arrivals_share_by_hour_utc"], "source": TW, "note": "UTC, Oct-Dec 2017"},
        "arrivals_share_by_weekday": {"values": p2["arrivals_share_by_weekday_utc"], "source": TW},
        "first_response_minutes": {"twitter": p2["first_response_minutes"], "flipkart": p2["flipkart_first_response_minutes"],
                                   "source": [TW, FK]},
        "give_up_rate": {"value": p2["medi_cal_abandonment_raw_value"]["median"], "unit": "fraction of queued calls (0-1)",
                         "source": MC,
                         "definition": "source data dictionary (average-call-abandonment-rate-data-dictionary.csv): calls abandoned by the "
                                       "caller after entering the queue for a live agent / calls that entered the queue; after-hours calls, "
                                       "hang-ups before the queue and queued call-backs are not counted; 'between 0 and 1, ... 0.5 "
                                       "representing 50%'. So 0.28 = 28% (median county-month, Jan-Jun 2026; IQR 0.20-0.37).",
                         "note": "public-benefits call centers with long waits (median 28 min per county-month), not retail/travel chat",
                         "proxy_twitter_unanswered_share": p2["unanswered_share_proxy"]},
        "real_score_distribution": {
            "customer_csat_ecommerce": {"values": p1["distributions"]["Flipkart CSAT (customer)"], "source": FK,
                                        "scored_by": "customer"},
            "annotator_travel_dialogues": {"values": p1["distributions"]["USS travel dialogues (annotators)"], "source": USS,
                                           "scored_by": "annotators (40 invited, per the USS paper)"},
            "csat_mean_by_response_delay": {k: v["mean"] for k, v in p1["csat_by_delay"].items()},
            "csat_mean_by_reason": {k: v["mean"] for k, v in p1["csat_by_reason"].items()},
        },
    }
    save_json(rn, SIM / "real_numbers.json")
    rub = load_json(RESULTS / "p3_rubrics_from_train.json")["csat"]
    rub["source"] = FK + " (train split only)"
    save_json(rub, SIM / "rubric.json")
    # calibration.json and calibration_fallback.json are written by p6_followup.py fit (delay-aware + fallback)
    print("kit files written for", models)


if __name__ == "__main__":
    main(sys.argv[1:])
