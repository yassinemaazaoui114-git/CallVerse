"""Follow-up: (a) delay-aware CSAT calibration, (b) fallback calibration from confirmed-licence data only (Olist,
TripAdvisor). Resumable (LLM cache). Usage:
python p6_followup.py run MODEL...    # LLM calls: extra CSAT calibration rows, Olist cards, fallback prompt on CSAT test
python p6_followup.py fit MODEL...    # fit + select on dev, test numbers -> results/p6_followup.json, kit files
"""
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import PROC, RAW, RESULTS, SEED, load_json, read_jsonl, save_json, score_metrics  # noqa: E402
from llm import cached_chat, parse_score, short, unload_all  # noqa: E402
from p3_tests import DEFAULT_N, SC_OPTS, collect, csat_card, fit_maps, apply_map, samples, score_call  # noqa: E402
from simulator.prompts import score_messages  # noqa: E402

SIM = Path(__file__).resolve().parents[1] / "simulator"
RS = PROC / "real_scores"
N_CAL_BIG = 300          # CSAT calibration rows from train for the delay-aware map (first 100 = Phase 3 sample)
N_OLIST = {"cal": 150, "dev": 80, "test": 150}
N_FB_ON_CSAT = 100     # fallback evaluated on the first 100 rows of the Phase 3 CSAT test sample (LLM-time budget)
DELAYS = ["0-5 min", "5-30 min", "30 min-2 h", "2-8 h", "8 h+"]
LATE = ["on time or early", "1-3 days late", "4-7 days late", "8+ days late", "never delivered"]
MIN_BUCKET = 20          # buckets with fewer calibration rows fall back to the global map


# ------------------------------------------------------------------ Olist (CC BY-NC-SA 4.0) situation cards
def late_bucket(d):
    if d is None or (isinstance(d, float) and np.isnan(d)):
        return "never delivered"
    return "on time or early" if d <= 0 else "1-3 days late" if d <= 3 else "4-7 days late" if d <= 7 else "8+ days late"


def olist_card(r):
    d = r["days_late"]
    if r["late_bucket"] == "never delivered":
        s = "Your order never arrived."
    elif d <= 0:
        s = "Your order arrived on time." if d >= -1 else f"Your order arrived {int(-d)} days before the promised date."
    else:
        s = f"Your order arrived {int(d)} day{'s' if d > 1 else ''} after the promised delivery date."
    return f"You are a customer of ShopNova, an online shop. {s} Now you are asked to rate your purchase experience."


def olist_splits():
    o = pd.read_csv(RS / "olist_scores_delay.csv").dropna(subset=["review_score"])
    o = o.drop_duplicates("review_id").rename(columns={"review_score": "score"})
    o["late_bucket"] = o.days_late.map(late_bucket)
    o["id"] = "olist_" + o.review_id.astype(str)
    tr, rest = train_test_split(o, test_size=0.30, random_state=SEED, stratify=o.score)
    dv, te = train_test_split(rest, test_size=0.50, random_state=SEED, stratify=rest.score)
    return tr, dv, te


SHOT_COMMENT = {1: "It never came on time, terrible.", 2: "Late and nobody told me anything.", 3: "It arrived, but later than I hoped.",
                4: "Fine, it arrived as expected.", 5: "Arrived early, very happy."}


def fallback_rubric(tr):
    p = tr.score.value_counts(normalize=True)
    m = tr.groupby("late_bucket").score.agg(["mean", lambda x: (x == 1).mean()])
    lines = [
        f"Out of 100 real online-shop customers, {round(100 * p[5])} give 5, {round(100 * p[4])} give 4, {round(100 * p[3])} give 3, "
        f"{round(100 * p[2])} give 2 and {round(100 * p[1])} give 1.",
        f"Delivery on time or early: average {m.loc['on time or early', 'mean']:.2f}. 1-3 days late: {m.loc['1-3 days late', 'mean']:.2f}. "
        f"4-7 days late: {m.loc['4-7 days late', 'mean']:.2f}. 8+ days late: {m.loc['8+ days late', 'mean']:.2f} "
        f"({100 * m.loc['8+ days late', '<lambda_0>']:.0f}% give 1). Never delivered: {m.loc['never delivered', 'mean']:.2f}.",
    ]
    rng = np.random.RandomState(SEED)
    shots = []
    for s, b in ((1, "8+ days late"), (5, "on time or early"), (2, "4-7 days late"), (4, "on time or early"), (3, "1-3 days late")):
        c = tr[(tr.score == s) & (tr.late_bucket == b)]
        r = c.iloc[rng.randint(len(c))]
        shots.append({"id": r["id"], "prompt": olist_card(r), "score": s, "comment": SHOT_COMMENT[s]})
    return {"lines": lines, "shots": shots,
            "source": "Olist Brazilian E-Commerce order reviews (Kaggle olistbr), CC BY-NC-SA 4.0, train split only; "
                      "only structured fields used (no Portuguese text); shot comments written by us, shot scores real"}


def fb_call(m, item_id, card, rub, cache="p6_fallback"):
    msgs = score_messages(card, None, "v2", rubric=rub, shots=rub["shots"])
    return cached_chat(cache, m, "fb1", item_id, msgs, num_ctx=6144, **SC_OPTS)


def run(models):
    rub_main = load_json(RESULTS / "p3_rubrics_from_train.json")
    n = dict(DEFAULT_N, csat_cal=N_CAL_BIG)
    S = samples(n)
    tr, dv, te = olist_splits()
    rub_fb = fallback_rubric(tr)
    save_json(rub_fb, RESULTS / "p6_rubric_fallback.json")
    shot_ids = {s["id"] for s in rub_fb["shots"]}
    O = {"cal": tr[~tr.id.isin(shot_ids)].sample(N_OLIST["cal"], random_state=SEED),
         "dev": dv.sample(N_OLIST["dev"], random_state=SEED), "test": te.sample(N_OLIST["test"], random_state=SEED)}
    csat_test = S[("csat", "test")].head(N_FB_ON_CSAT).to_dict("records")
    for m in models:
        jobs = [("main", r) for r in S[("csat", "cal")].to_dict("records")]
        jobs += [("olist", r) for part in ("cal", "dev", "test") for r in O[part].to_dict("records")]
        jobs += [("fb_on_csat", r) for r in csat_test]

        def go(j):
            kind, r = j
            if kind == "main":
                return score_call(m, "csat", "v2", r, rub_main)
            if kind == "olist":
                return fb_call(m, r["id"], olist_card(r), rub_fb)
            return fb_call(m, r["id"], csat_card(r), rub_fb)
        with ThreadPoolExecutor(4) as ex:
            list(ex.map(go, jobs))
        print("p6 run done", m, len(jobs))
    unload_all()


# ------------------------------------------------------------------ fitting
def bucket_maps(raw, bucket, real_by_bucket, global_map):
    """Per bucket quantile map: the raw score's mid-rank quantile within the bucket -> the real quantile within the
    bucket (real distribution from the whole TRAIN split). Small buckets use the global map."""
    out = {}
    raw, bucket = np.asarray(raw), np.asarray(bucket)
    for b, real in real_by_bucket.items():
        r = raw[bucket == b]
        if len(r) < MIN_BUCKET:
            out[b] = dict(global_map)
            continue
        q = np.sort(np.asarray(real))
        cdf = {k: (np.mean(r < k) + np.mean(r <= k)) / 2 for k in range(1, 6)}
        out[b] = {str(k): int(q[min(int(cdf[k] * len(q)), len(q) - 1)]) for k in range(1, 6)}
    return out


def expected_map(raw, real):
    """Raw level k -> mean real score over k's quantile interval [F(k-1), F(k)] of the raw distribution
    (continuous; avoids the tie problem of an integer quantile map on 5 discrete levels)."""
    raw = np.asarray(raw)
    q = np.sort(np.asarray(real, dtype=float))
    out, seen = {}, {}
    for k in range(1, 6):
        lo, hi = np.mean(raw < k), np.mean(raw <= k)
        if hi > lo:
            a, b = int(lo * len(q)), max(int(hi * len(q)), int(lo * len(q)) + 1)
            seen[k] = round(float(q[a:b].mean()), 3)
    for k in range(1, 6):
        out[str(k)] = seen.get(k, seen[min(seen, key=lambda s: abs(s - k))])
    return out


def bucket_expected_maps(raw, bucket, real_by_bucket, global_map):
    raw, bucket = np.asarray(raw), np.asarray(bucket)
    return {b: (expected_map(raw[bucket == b], real) if (bucket == b).sum() >= MIN_BUCKET else dict(global_map))
            for b, real in real_by_bucket.items()}


def to_int(x):
    return [int(np.floor(v + 0.5)) for v in x]


def apply_bucket(maps, global_map, raw, bucket):
    return [maps.get(b, global_map)[str(int(x))] for x, b in zip(raw, bucket)]


def by_bucket(real, pred, bucket, order):
    d = pd.DataFrame({"real": real, "pred": pred, "b": bucket})
    rows = {b: {"n": int((d.b == b).sum()), "real_mean": float(d[d.b == b].real.mean()), "sim_mean": float(d[d.b == b].pred.mean())}
            for b in order if (d.b == b).any()}
    gap = sum(v["n"] * abs(v["real_mean"] - v["sim_mean"]) for v in rows.values()) / max(sum(v["n"] for v in rows.values()), 1)
    return rows, float(gap)


def short_metrics(x):
    return {k: x[k] for k in ("n", "mae", "spearman", "exact_acc", "qwk", "macro_f1", "wasserstein", "pred_dist")}


def fit(models):
    n = dict(DEFAULT_N, csat_cal=N_CAL_BIG)
    S = samples(n)
    tr_all = pd.DataFrame(read_jsonl(RS / "csat_allrows_train.jsonl"))
    real_by_delay = {b: tr_all[tr_all.delay_bucket == b].score.values for b in DELAYS}
    tr, dv, te = olist_splits()
    rub_fb = load_json(RESULTS / "p6_rubric_fallback.json")
    shot_ids = {s["id"] for s in rub_fb["shots"]}
    O = {"cal": tr[~tr.id.isin(shot_ids)].sample(N_OLIST["cal"], random_state=SEED),
         "dev": dv.sample(N_OLIST["dev"], random_state=SEED), "test": te.sample(N_OLIST["test"], random_state=SEED)}
    trip = pd.read_csv(RAW / "trip-advisor-hotel-reviews" / "tripadvisor_hotel_reviews.csv")
    trip_tr, _ = train_test_split(trip, test_size=0.30, random_state=SEED, stratify=trip.Rating)
    fbc = {(r["model"], r["item"]): r for r in read_jsonl(Path(PROC).parents[0] / "cache" / "p6_fallback.jsonl")}
    p3 = load_json(RESULTS / "p3_test3_scores.json")
    res = {"settings": {"n_cal_big": N_CAL_BIG, "olist": N_OLIST, "min_bucket": MIN_BUCKET,
                        "selection": "dev: size-weighted mean |simulated - real| of the delay-bucket means (what agent E's "
                                     "reward depends on); dev QWK reported alongside"}}
    cal_main, cal_fb = {"models": {}}, {"models": {}}
    for m in models:
        r = {}
        # ---------------- (a) delay-aware main calibration (Flipkart CSAT)
        cal = collect(m, "csat", "v2", "cal", S)
        dev = collect(m, "csat", "v2", "dev", S)
        test = collect(m, "csat", "v2", "test", S)
        for d in (cal, dev, test):
            d["raw_f"] = d.raw.fillna(5).astype(int)
        gmeth = p3[short(m)]["csat"]["best_v3_on_dev"].split("-")[1]
        gmap_p3 = {str(k): v for k, v in p3[short(m)]["csat"]["calibration_maps_fit_on_cal"][gmeth].items()}
        gmap_big = {str(k): v for k, v in fit_maps(cal.raw_f, cal.real)[gmeth].items()}
        bmaps = bucket_maps(cal.raw_f, cal.delay_bucket, real_by_delay, gmap_big)
        gexp = expected_map(cal.raw_f, tr_all.score.values)
        emaps = bucket_expected_maps(cal.raw_f, cal.delay_bucket, real_by_delay, gexp)
        cands = {"global (Phase 3 map, 100 cal rows)": lambda d: apply_map({int(k): v for k, v in gmap_p3.items()}, d.raw_f),
                 f"global ({gmeth}, {N_CAL_BIG} cal rows)": lambda d: apply_map({int(k): v for k, v in gmap_big.items()}, d.raw_f),
                 "delay-aware (per-bucket quantile)": lambda d: apply_bucket(bmaps, gmap_big, d.raw_f, d.delay_bucket),
                 "delay-aware expected score (per-bucket quantile-interval mean)": lambda d: apply_bucket(emaps, gexp, d.raw_f, d.delay_bucket)}
        devres = {}
        for k, f in cands.items():
            pred = f(dev)
            _, gap = by_bucket(dev.real, pred, dev.delay_bucket, DELAYS)
            mt = score_metrics(dev.real, to_int(pred))
            devres[k] = {"bucket_gap": gap, "qwk": mt["qwk"], "mae": mt["mae"]}
        chosen = min(devres, key=lambda k: devres[k]["bucket_gap"])
        test_rows = {}
        for k, f in [("raw (v2, no calibration)", lambda d: list(d.raw_f))] + list(cands.items()):
            pred = f(test)
            rows, gap = by_bucket(test.real, pred, test.delay_bucket, DELAYS)
            test_rows[k] = {"metrics": short_metrics(score_metrics(test.real, to_int(pred))), "by_delay": rows, "bucket_gap": gap,
                            "mae_continuous": float(np.mean(np.abs(np.asarray(test.real) - np.asarray(pred, dtype=float))))}
        r["delay_aware"] = {"dev": devres, "chosen_on_dev": chosen, "test": test_rows, "bucket_maps": bmaps, "expected_maps": emaps,
                            "global_expected_map": gexp,
                            "global_map_400": gmap_big, "cal_rows_per_bucket": cal.delay_bucket.value_counts().to_dict()}
        cal_main["models"][m] = {"method": gmeth, "map": gmap_p3 if chosen.startswith("global (Phase 3") else gmap_big,
                                 "delay_aware": {"enabled": chosen.startswith("delay-aware"),
                                                 "method": "expected" if "expected" in chosen else "quantile",
                                                 "bucket_maps": emaps if "expected" in chosen else bmaps,
                                                 "buckets_minutes": {"0-5 min": [0, 5], "5-30 min": [5, 30], "30 min-2 h": [30, 120],
                                                                     "2-8 h": [120, 480], "8 h+": [480, None]},
                                                 "global_map": gexp if "expected" in chosen else gmap_big},
                                 "chosen_on_dev": chosen,
                                 "test_after": test_rows[chosen]["metrics"]}
        # ---------------- (b) fallback calibration (Olist only, confirmed licence)
        def fb_frame(rows, card_ids):
            out = []
            for x in rows:
                c = fbc.get((m, x["id"]))
                if c is None:
                    continue
                s, _, valid = parse_score(c["text"])
                out.append({"id": x["id"], "real": int(x["score"]), "raw": s or 5, "valid": valid,
                            "late_bucket": x.get("late_bucket"), "delay_bucket": x.get("delay_bucket")})
            return pd.DataFrame(out)
        oc, od, ot = (fb_frame(O[p].to_dict("records"), None) for p in ("cal", "dev", "test"))
        omaps = fit_maps(oc.raw, oc.real)
        real_by_late = {b: tr[tr.late_bucket == b].score.values for b in LATE}
        ocand = {k: {str(a): b for a, b in v.items()} for k, v in omaps.items()}
        odev = {k: score_metrics(od.real, apply_map({int(a): b for a, b in mp.items()}, od.raw)) for k, mp in ocand.items()}
        ochosen = max(odev, key=lambda k: (odev[k]["qwk"], -odev[k]["wasserstein"]))
        omap = ocand[ochosen]
        olate = bucket_maps(oc.raw, oc.late_bucket, real_by_late, omap)
        og = {int(a): b for a, b in omap.items()}
        dev_gap_global = by_bucket(od.real, apply_map(og, od.raw), od.late_bucket, LATE)[1]
        dev_gap_late = by_bucket(od.real, apply_bucket(olate, omap, od.raw, od.late_bucket), od.late_bucket, LATE)[1]
        late_on = dev_gap_late < dev_gap_global
        o_test = {
            "raw": short_metrics(score_metrics(ot.real, ot.raw)),
            f"fallback global ({ochosen})": short_metrics(score_metrics(ot.real, apply_map({int(a): b for a, b in omap.items()}, ot.raw))),
            "fallback lateness-aware": short_metrics(score_metrics(ot.real, apply_bucket(olate, omap, ot.raw, ot.late_bucket))),
        }
        # fallback prompt + fallback map evaluated on the same Flipkart CSAT test rows as the main calibration
        fc = fb_frame(S[("csat", "test")].head(N_FB_ON_CSAT).to_dict("records"), None)
        fpred = apply_map({int(a): b for a, b in omap.items()}, fc.raw)
        rows_fc, gap_fc = by_bucket(fc.real, fpred, fc.delay_bucket, DELAYS)
        same = test.set_index("id").loc[fc.id]
        main_same = {k: short_metrics(score_metrics(same.real, to_int(cands[k](same.reset_index())))) for k in cands}
        # Atlas: distribution-only map to TripAdvisor (CC BY-NC 4.0) ratings, from the model's raw Olist-cal scores
        q = np.sort(trip_tr.Rating.values)
        cdf = {k: (np.mean(oc.raw < k) + np.mean(oc.raw <= k)) / 2 for k in range(1, 6)}
        tmap = {str(k): int(q[min(int(cdf[k] * len(q)), len(q) - 1)]) for k in range(1, 6)}
        r["fallback"] = {"olist_dev": {k: {"qwk": v["qwk"], "mae": v["mae"], "wasserstein": v["wasserstein"]} for k, v in odev.items()},
                         "olist_chosen_on_dev": ochosen, "olist_test": o_test,
                         "on_flipkart_csat_test": {"metrics": short_metrics(score_metrics(fc.real, fpred)), "by_delay": rows_fc, "bucket_gap": gap_fc,
                                                   "raw": short_metrics(score_metrics(fc.real, fc.raw)),
                                                   "main_calibrations_on_same_rows": main_same},
                         "valid_json": float(pd.concat([oc, od, ot, fc]).valid.mean()),
                         "map": omap, "lateness_maps": olate, "atlas_tripadvisor_distribution_map": tmap,
                         "olist_dev_lateness_gap": {"global": dev_gap_global, "lateness-aware": dev_gap_late, "lateness_aware_enabled": late_on}}
        cal_fb["models"][m] = {"method": ochosen, "map": omap,
                               "lateness_aware": {"enabled": bool(late_on), "bucket_maps": olate, "buckets_days_late": LATE},
                               "atlas_tripadvisor_distribution_map": tmap,
                               "test_olist": o_test[f"fallback global ({ochosen})"],
                               "test_flipkart_csat": r["fallback"]["on_flipkart_csat_test"]["metrics"]}
        res[short(m)] = r
    save_json(res, RESULTS / "p6_followup.json")
    cal_main.update({"fit_on": f"CSAT calibration rows from the train split ({N_CAL_BIG}; real customer scores). Delay-bucket "
                               "target distributions from the whole train split (60,134 rows). Selection on dev.",
                     "source": "eCommerce Customer Service Satisfaction (Kaggle ddosad) - licence TO VERIFY"})
    save_json(cal_main, SIM / "calibration.json")
    cal_fb.update({"fit_on": "Olist order reviews, train split (200 calibration rows; real customer scores), chosen on Olist dev",
                   "source": "Olist (Kaggle olistbr) CC BY-NC-SA 4.0; TripAdvisor Hotel Reviews (Kaggle andrewmvd, Alam et al. 2016) "
                             "CC BY-NC 4.0 for the Atlas distribution-only map",
                   "use_with": "rubric_fallback.json"})
    save_json(cal_fb, SIM / "calibration_fallback.json")
    save_json(rub_fb, SIM / "rubric_fallback.json")
    return res


if __name__ == "__main__":
    {"run": run, "fit": fit}[sys.argv[1]](sys.argv[2:])
