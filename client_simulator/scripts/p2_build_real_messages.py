"""Phase 2 (D5): real customer messages (Customer Support on Twitter), realism profile, real numbers."""
import re
import zipfile

import numpy as np
import pandas as pd

from common import FIG, PROC, RAW, REAL, RESULTS, SEED, anonymise, plot_style, save_json, write_jsonl
from realism import is_english, map_reason, profile

OUT = PROC / "real_messages"
OUT.mkdir(parents=True, exist_ok=True)
SHOP = ["AmazonHelp", "UPSHelp", "AskTarget", "ArgosHelpers", "AskeBay"]
TRAVEL = ["Delta", "AmericanAir", "British_Airways", "SouthwestAir", "AirAsiaSupport", "JetBlue", "AlaskaAir",
          "VirginAtlantic", "VirginTrains", "GWRHelp", "AirbnbHelp"]
COMPANY = {**{b: "shopnova" for b in SHOP}, **{b: "atlas" for b in TRAVEL}}
_SIGN = re.compile(r"(\s[-^*~]\s?[A-Z][A-Za-z]{0,12}\.?\s*$|\s\^[A-Z]{1,4}\s*$|\s[-~][A-Z]{1,4}\s*$)")


def clean(text):
    """Anonymise and drop leading @mentions (Twitter addressing, not part of the message)."""
    t = re.sub(r"^(\s*@\w+)+", "", str(text))
    t = _SIGN.sub(" <AGENT>", t)  # agent sign-offs such as "^JK" or "-Anna"
    return anonymise(t).strip()


def load_twcs():
    pkl = RAW / "customer-support-on-twitter" / "twcs.pkl"
    if pkl.exists():
        return pd.read_pickle(pkl)
    z = zipfile.ZipFile(RAW / "customer-support-on-twitter" / "customer-support-on-twitter.zip")
    d = pd.read_csv(z.open("twcs/twcs.csv"))
    d.to_pickle(pkl)
    return d


def main():
    d = load_twcs()
    d["ts"] = pd.to_datetime(d.created_at, format="%a %b %d %H:%M:%S %z %Y", utc=True)
    by_id = d.set_index("tweet_id")
    # brand reply -> the tweet it answers
    brand = d[~d.inbound & d.author_id.isin(COMPANY)]
    first_reply = (brand.dropna(subset=["in_response_to_tweet_id"])
                   .sort_values("ts").groupby("in_response_to_tweet_id").first())
    # first customer messages: inbound, not a reply, addressed to one of our brands (by @mention)
    firsts = d[d.inbound & d.in_response_to_tweet_id.isna()].copy()
    mention = firsts.text.str.extract(r"@(" + "|".join(COMPANY) + r")\b", flags=re.I)[0]
    lower = {b.lower(): b for b in COMPANY}
    firsts["brand"] = mention.str.lower().map(lower)
    firsts = firsts[firsts.brand.notna()].copy()
    firsts["company"] = firsts.brand.map(COMPANY)
    fr = first_reply.reindex(firsts.tweet_id)
    firsts["brand_replied"] = fr.author_id.notna().values
    firsts["reply_minutes"] = ((fr.ts.values - firsts.ts.values) / np.timedelta64(1, "m"))
    firsts["clean"] = firsts.text.map(clean)
    firsts = firsts[firsts.clean.str.len() > 3]
    n_before_lang = len(firsts)
    firsts = firsts[firsts.clean.map(is_english)].copy()
    n_after_lang = len(firsts)
    m = firsts.apply(lambda r: map_reason(r.clean, r.company), axis=1)
    firsts["reason"] = [x[0] for x in m]
    firsts["all_reasons"] = [x[1] for x in m]
    firsts["reply_text"] = fr.text.reindex(firsts.tweet_id).map(lambda x: clean(x) if isinstance(x, str) else None).values

    # later customer turns: inbound replies to a brand tweet of our brands
    later = d[d.inbound & d.in_response_to_tweet_id.notna()].copy()
    later["parent_author"] = by_id.author_id.reindex(later.in_response_to_tweet_id).values
    later = later[later.parent_author.isin(COMPANY)].copy()
    later["company"] = later.parent_author.map(COMPANY)
    later["clean"] = later.text.map(clean)
    later = later[later.clean.map(is_english)].copy()

    keep = ["tweet_id", "brand", "company", "reason", "all_reasons", "clean", "brand_replied", "reply_minutes", "reply_text"]
    out = firsts[keep].rename(columns={"tweet_id": "id", "clean": "text"})
    out["id"] = "tw_" + out.id.astype(str)
    out["source"] = "Customer Support on Twitter (Kaggle thoughtvector)"
    write_jsonl(out.to_dict("records"), OUT / "first_messages.jsonl")
    lt = later[["tweet_id", "company", "clean"]].rename(columns={"tweet_id": "id", "clean": "text"})
    lt["id"] = "tw_" + lt.id.astype(str)
    write_jsonl(lt.sample(min(len(lt), 20000), random_state=SEED).to_dict("records"), OUT / "later_turns_sample.jsonl")
    # real agent replies used as the "agent" turns in Phase 3 test 2
    rep = out[out.reply_text.notna()][["id", "company", "reason", "reply_text"]]
    write_jsonl(rep.sample(min(len(rep), 3000), random_state=SEED).to_dict("records"), OUT / "agent_replies_sample.jsonl")

    # ---------------- realism profile (sample for speed; fixed seed)
    res = {"counts": {"first_messages": len(out), "by_company": out.company.value_counts().to_dict(),
                      "by_brand": out.brand.value_counts().to_dict(), "later_turns": len(lt),
                      "dropped_as_not_english_or_too_short": n_before_lang - n_after_lang}}
    prof = {}
    for comp in ("shopnova", "atlas"):
        s = out[out.company == comp].sample(3000, random_state=SEED)
        prof[comp] = profile(s.text.tolist(), [comp] * len(s))
        ls = lt[lt.company == comp].sample(3000, random_state=SEED)
        prof[comp + "_later_turns"] = profile(ls.text.tolist(), [comp] * len(ls))
    both = out.groupby("company").sample(1500, random_state=SEED)
    prof["all_first"] = profile(both.text.tolist(), both.company.tolist())
    res["realism_profile"] = prof
    res["realism_profile_note"] = "3,000 random first messages per company (seed 42); tweets are capped at 140/280 characters"

    # ---------------- real numbers
    res["reason_mix_twitter_keyword_rules"] = {c: (g.reason.value_counts(normalize=True).round(4).to_dict())
                                               for c, g in out.groupby("company")}
    hours = out.assign(h=firsts.ts.dt.hour.reindex(out.index)).h.value_counts(normalize=True).sort_index()
    dows = firsts.ts.dt.day_name().reindex(out.index).value_counts(normalize=True)
    res["arrivals_share_by_hour_utc"] = {int(k): round(float(v), 4) for k, v in hours.items()}
    res["arrivals_share_by_weekday_utc"] = {k: round(float(v), 4) for k, v in dows.items()}
    res["twitter_time_span"] = [str(firsts.ts.min()), str(firsts.ts.max())]
    rm = out.reply_minutes.dropna()
    rm = rm[rm >= 0]
    res["first_response_minutes"] = {c: {"n": int(len(g)), "median": float(g.median()), "p25": float(g.quantile(.25)),
                                         "p75": float(g.quantile(.75)), "p90": float(g.quantile(.9))}
                                     for c, g in out.assign(rm=out.reply_minutes).dropna(subset=["rm"]).query("rm>=0").groupby("company").rm}
    res["unanswered_share_proxy"] = {c: round(float(1 - g.brand_replied.mean()), 4) for c, g in out.groupby("company")}

    # US airline tweets: negative-reason mix (labels by CrowdFlower annotators)
    w = pd.read_csv(RAW / "twitter-airline-sentiment" / "Tweets.csv")
    res["us_airline_negative_reason_mix"] = w.negativereason.value_counts(normalize=True).round(4).to_dict()
    res["us_airline_sentiment_mix"] = w.airline_sentiment.value_counts(normalize=True).round(4).to_dict()
    # Flipkart CSAT category mix (real contacts, labelled by the company)
    cs = pd.read_json(PROC / "real_scores" / "csat_all.jsonl", lines=True)
    res["flipkart_reason_mix_mapped"] = cs.reason.value_counts(normalize=True).round(4).to_dict()
    rep_t = pd.read_csv(RAW / "ecommerce-customer-service-satisfaction" / "Customer_support_data.csv",
                        usecols=["Issue_reported at"])
    rt = pd.to_datetime(rep_t["Issue_reported at"], format="%d/%m/%Y %H:%M", errors="coerce")
    res["flipkart_arrivals_share_by_hour_local"] = {int(k): round(float(v), 4) for k, v in rt.dt.hour.value_counts(normalize=True).sort_index().items()}
    res["flipkart_arrivals_share_by_weekday_local"] = {k: round(float(v), 4) for k, v in rt.dt.day_name().value_counts(normalize=True).items()}
    rmin = cs.response_minutes.dropna()
    res["flipkart_first_response_minutes"] = {"n": int(len(rmin)), "median": float(rmin.median()), "p25": float(rmin.quantile(.25)),
                                              "p75": float(rmin.quantile(.75)), "p90": float(rmin.quantile(.9))}
    # Medi-Cal county call centres (CA open data): abandonment and volume
    ab = pd.read_csv(RAW / "medical_callcenter" / "abandon.csv", skiprows=1)
    ab["rate"] = pd.to_numeric(ab["Average Abandonment Rate"], errors="coerce")
    vol = pd.read_csv(RAW / "medical_callcenter" / "volume.csv", skiprows=1)
    vol["calls"] = pd.to_numeric(vol["Total Number of Calls Received"].astype(str).str.replace(",", ""), errors="coerce")
    res["medi_cal_abandonment_raw_value"] = {
        "n_county_months": int(ab.rate.notna().sum()), "median": float(ab.rate.median()),
        "p25": float(ab.rate.quantile(.25)), "p75": float(ab.rate.quantile(.75)),
        "periods": sorted(ab["Reporting Period"].dropna().unique().tolist())[:12],
        "unit_note": "fraction 0-1 per the source data dictionary (0.5 = 50%); abandoned after entering the queue / entered the queue",
    }
    res["medi_cal_after_hours_share_of_calls"] = float(
        pd.to_numeric(vol["Number of Calls Received After Working Hours"].astype(str).str.replace(",", ""), errors="coerce").sum()
        / vol.calls.sum())
    save_json(res, RESULTS / "p2_real_numbers_and_profile.json")

    # ---------------- charts
    plt = plot_style()
    fig, axes = plt.subplots(1, 2, figsize=(12, 3.6))
    hs = [res["arrivals_share_by_hour_utc"].get(h, 0) for h in range(24)]
    axes[0].bar(range(24), hs, color=REAL, width=0.7)
    axes[0].set_title("Twitter support: first customer messages by hour (UTC)", loc="left")
    axes[0].set_xlabel("hour of day (UTC)"); axes[0].set_ylabel("share of messages")
    fh = [res["flipkart_arrivals_share_by_hour_local"].get(h, 0) for h in range(24)]
    axes[1].bar(range(24), fh, color=REAL, width=0.7)
    axes[1].set_title("Flipkart CSAT: issues reported by hour (local time)", loc="left")
    axes[1].set_xlabel("hour of day"); axes[1].set_ylabel("share of contacts")
    fig.tight_layout(); fig.savefig(FIG / "arrivals_by_hour.png")

    # hand-check sample of 50 (25 per company) for the reason mapping
    # v2 check uses a fresh seed (v1 sample, seed 7, was used to improve the rules)
    hc = out.groupby("company").sample(25, random_state=2024)[["id", "company", "brand", "reason", "all_reasons", "text"]]
    hc.to_csv(OUT / "mapping_handcheck_v2_sample.csv", index=False)
    # 20 sample messages for the report
    s20 = out.groupby("company").sample(10, random_state=11)[["company", "brand", "reason", "text"]]
    s20.to_csv(OUT / "sample20.csv", index=False)
    print({k: v for k, v in res.items() if k != "realism_profile"})
    print(prof)


if __name__ == "__main__":
    main()
