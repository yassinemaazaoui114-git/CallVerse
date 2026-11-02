"""Large-sample rerun of the follow-up evaluations (qwen3.5:4b, phi4-mini:3.8b). Resumable (LLM cache).
Before every batch of LLM calls: the laptop must be on mains power and the GPU not throttled, otherwise STOP (exit 3).

python p7_large.py run MODEL...   # LLM calls in power-checked batches
python p7_large.py fit MODEL...   # fit on train, select on dev, test with bootstrap 95% CIs -> results/p7_large.json + kit files
"""
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import CACHE, PROC, RESULTS, ROOT, SEED, load_json, read_jsonl, save_json, score_metrics  # noqa: E402
from llm import cached_chat, parse_score, short, unload_all  # noqa: E402
from p3_tests import DEFAULT_N, apply_map, csat_card, fit_maps, samples, score_call  # noqa: E402
from p6_followup import (DELAYS, LATE, MIN_BUCKET, bucket_expected_maps, bucket_maps, expected_map, fb_call,  # noqa: E402
                         olist_card, olist_splits, apply_bucket, to_int)

SIM = ROOT / "simulator"
RS = PROC / "real_scores"
# sizes (user minimums: CSAT test >= 1000; delay-aware fit >= 1500 train rows, >= 100 per bucket; Olist >= 500 train/dev and
# 500 test; fallback on the same CSAT test; full USS travel test split)
N = dict(DEFAULT_N, csat_cal=1500, csat_dev=500, csat_test=1000, conv_test=186)
MIN_PER_BUCKET = 150      # top-up target per delay bucket in the calibration set (random train rows of that bucket)
N_OLIST = {"cal": 500, "dev": 200, "test": 500}
BATCH = 200
B = 2000


# ------------------------------------------------------------------ power / throttle guard
def power_ok():
    bat = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Battery).BatteryStatus"],
                         capture_output=True, text=True).stdout.strip()
    q = ("clocks_throttle_reasons.hw_slowdown,clocks_throttle_reasons.hw_thermal_slowdown,"
         "clocks_throttle_reasons.sw_thermal_slowdown,clocks_throttle_reasons.hw_power_brake_slowdown")
    thr = subprocess.run(["nvidia-smi", f"--query-gpu={q}", "--format=csv,noheader"], capture_output=True, text=True).stdout.strip()
    ok = bat in ("2", "") and "Active" not in thr.replace("Not Active", "")
    return ok, f"BatteryStatus={bat or 'no battery'}; throttle(hw,hw_thermal,sw_thermal,power_brake)={thr}"


def guarded(jobs, fn, label):
    for i in range(0, len(jobs), BATCH):
        ok, info = power_ok()
        if not ok:
            msg = f"STOPPED before batch {i // BATCH + 1} of {label}: {info} {time.ctime()}"
            with open(ROOT / "logs" / "llm_runs.log", "a", encoding="utf-8") as f:
                f.write(msg + "\n")
            print(msg)
            unload_all()
            sys.exit(3)
        with ThreadPoolExecutor(4) as ex:
            list(ex.map(fn, jobs[i:i + BATCH]))
        print(f"{label}: {min(i + BATCH, len(jobs))}/{len(jobs)} ({info})", flush=True)


# ------------------------------------------------------------------ samples (supersets of the earlier ones: same seed, prefix)
def large_samples():
    S = samples(N)
    cal = S[("csat", "cal")]
    rub = load_json(RESULTS / "p3_rubrics_from_train.json")
    shot_ids = {s["id"] for k in ("csat", "conv") for s in rub[k]["shots"]}
    tr = pd.DataFrame(read_jsonl(RS / "csat_allrows_train.jsonl"))
    tr = tr[~tr.id.isin(shot_ids) & ~tr.id.isin(cal.id)]
    extra = []
    for b in DELAYS:
        need = MIN_PER_BUCKET - int((cal.delay_bucket == b).sum())
        if need > 0:
            extra.append(tr[tr.delay_bucket == b].sample(need, random_state=SEED))
    topup = pd.concat(extra) if extra else tr.iloc[:0]
    return S, cal, topup


def olist_samples():
    tr, dv, te = olist_splits()
    rub_fb = load_json(RESULTS / "p6_rubric_fallback.json")
    shot_ids = {s["id"] for s in rub_fb["shots"]}
    return tr, {"cal": tr[~tr.id.isin(shot_ids)].sample(N_OLIST["cal"], random_state=SEED),
                "dev": dv.sample(N_OLIST["dev"], random_state=SEED), "test": te.sample(N_OLIST["test"], random_state=SEED)}


def run(models):
    rub = load_json(RESULTS / "p3_rubrics_from_train.json")
    rub_fb = load_json(RESULTS / "p6_rubric_fallback.json")
    S, cal, topup = large_samples()
    _, O = olist_samples()
    csat_rows = {"cal": pd.concat([cal, topup]).to_dict("records"), "dev": S[("csat", "dev")].to_dict("records"),
                 "test": S[("csat", "test")].to_dict("records")}
    conv_test = S[("conv", "test")].to_dict("records")
    for m in models:
        t0 = time.time()
        guarded([r for p in ("test", "dev", "cal") for r in csat_rows[p]], lambda r: score_call(m, "csat", "v2", r, rub), f"{short(m)} CSAT main")
        guarded(conv_test, lambda r: score_call(m, "conv", "v2", r, rub), f"{short(m)} CONV full test")
        guarded([r for p in ("test", "dev", "cal") for r in O[p].to_dict("records")], lambda r: fb_call(m, r["id"], olist_card(r), rub_fb),
                f"{short(m)} Olist fallback")
        guarded(csat_rows["test"], lambda r: fb_call(m, r["id"], csat_card(r), rub_fb), f"{short(m)} fallback on CSAT test")
        unload_all()
        with open(ROOT / "logs" / "llm_runs.log", "a", encoding="utf-8") as f:
            f.write(f"large rerun p7 {short(m)} {int(time.time() - t0)}s {time.ctime()} [mains power, checked per batch]\n")


# ------------------------------------------------------------------ bootstrap
def qwk_fast(a, b):
    a, b = np.asarray(a, int) - 1, np.asarray(b, int) - 1
    O = np.zeros((5, 5))
    np.add.at(O, (a, b), 1)
    W = np.subtract.outer(np.arange(5), np.arange(5)) ** 2 / 16
    E = np.outer(O.sum(1), O.sum(0)) / O.sum()
    den = (W * E).sum()
    return 0.0 if den == 0 else 1 - (W * O).sum() / den


IDX_CACHE = {}


def boot_idx(n):
    if n not in IDX_CACHE:
        rng = np.random.RandomState(0)
        IDX_CACHE[n] = rng.randint(0, n, (B, n))
    return IDX_CACHE[n]


def ci(vals):
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]


def with_ci(real, pred_cont, bucket=None, order=None):
    """Metrics (integer score = rounded) + bootstrap 95% CIs for MAE, QWK and every bucket mean (real and simulated)."""
    real = np.asarray(real, int)
    pc = np.asarray(pred_cont, float)
    pi = np.asarray(to_int(pc), int)
    out = score_metrics(real, pi)
    idx = boot_idx(len(real))
    out["mae_ci"] = ci([np.mean(np.abs(real[i] - pi[i])) for i in idx])
    out["qwk_ci"] = ci([qwk_fast(real[i], pi[i]) for i in idx])
    if bucket is not None:
        bucket = np.asarray(bucket)
        rows, gaps = {}, []
        for b in order:
            sel = bucket == b
            if not sel.any():
                continue
            rows[b] = {"n": int(sel.sum()), "real_mean": float(real[sel].mean()), "sim_mean": float(pc[sel].mean())}
        bi = {b: np.where(bucket == b)[0] for b in rows}
        for b in rows:  # resample inside each bucket (bucket sizes fixed)
            ib = bi[b]
            rs = np.random.RandomState(1).randint(0, len(ib), (B, len(ib)))
            rows[b]["real_mean_ci"] = ci(real[ib][rs].mean(1))
            rows[b]["sim_mean_ci"] = ci(pc[ib][rs].mean(1))
            rows[b]["gap_ci"] = ci(np.abs(pc[ib][rs].mean(1) - real[ib][rs].mean(1)))
        for i in idx:
            r_, p_, b_ = real[i], pc[i], bucket[i]
            g, n = 0.0, 0
            for b in rows:
                s = b_ == b
                if s.any():
                    g += s.sum() * abs(p_[s].mean() - r_[s].mean())
                    n += s.sum()
            gaps.append(g / n)
        tot = sum(v["n"] for v in rows.values())
        out["by_bucket"] = rows
        out["bucket_gap"] = float(sum(v["n"] * abs(v["sim_mean"] - v["real_mean"]) for v in rows.values()) / tot)
        out["bucket_gap_ci"] = ci(gaps)
    return out


# ------------------------------------------------------------------ fit
def frame(m, name, rows, cache="test3"):
    if cache == "test3":
        c = {r["item"]: r for r in read_jsonl(CACHE / f"test3_{name}.jsonl") if r["model"] == m and r["pv"] == "s2"}
    else:
        c = {r["item"]: r for r in read_jsonl(CACHE / "p6_fallback.jsonl") if r["model"] == m and r["pv"] == "fb1"}
    out = []
    for r in rows:
        x = c.get(r["id"])
        if x is None:
            continue
        s, _, valid = parse_score(x["text"])
        out.append({"id": r["id"], "real": int(r["score"]), "raw": s if s is not None else (3 if name == "conv" else 5),
                    "valid": valid, "delay_bucket": r.get("delay_bucket"), "late_bucket": r.get("late_bucket")})
    return pd.DataFrame(out)


def fit(models):
    S, cal_nat, topup = large_samples()
    tr_olist, O = olist_samples()
    tr_all = pd.DataFrame(read_jsonl(RS / "csat_allrows_train.jsonl"))
    real_by_delay = {b: tr_all[tr_all.delay_bucket == b].score.values for b in DELAYS}
    real_by_late = {b: tr_olist[tr_olist.late_bucket == b].score.values for b in LATE}
    p3 = load_json(RESULTS / "p3_test3_scores.json")
    te_rows = S[("csat", "test")]
    # baselines on the same large CSAT test and the full CONV test, with CIs
    res = {"sizes": {"csat_cal_natural": len(cal_nat), "csat_cal_topup": len(topup), "csat_dev": len(S[("csat", "dev")]),
                     "csat_test": len(te_rows), "conv_test": len(S[("conv", "test")]), "olist": N_OLIST,
                     "min_per_bucket_target": MIN_PER_BUCKET, "bootstrap": B},
           "selection": "delay-aware: smallest dev size-weighted bucket-mean gap; fallback map: dev QWK; lateness-aware: dev bucket gap"}
    base = load_json(RESULTS / "p1_baselines.json")
    for name, key, rows in (("csat", "csat_allrows", te_rows), ("conv", "conv", S[("conv", "test")])):
        tf = pd.read_csv(RESULTS / f"p1_tfidf_pred_{key}_test.csv").set_index("id").pred
        maj = base[key]["majority_class"]
        bk = rows.delay_bucket.values if name == "csat" else None
        res[f"baseline_{name}"] = {"majority": with_ci(rows.score, [maj] * len(rows), bk, DELAYS),
                                   "tfidf_lr": with_ci(rows.score, tf.reindex(rows.id).values, bk, DELAYS)}
    cal_main, cal_fb = {"models": {}}, {"models": {}}
    for m in models:
        r = {}
        cal_all = frame(m, "csat", pd.concat([cal_nat, topup]).to_dict("records"))
        nat_ids = set(cal_nat.id)
        cal = cal_all[cal_all.id.isin(nat_ids)]
        dev = frame(m, "csat", S[("csat", "dev")].to_dict("records"))
        test = frame(m, "csat", te_rows.to_dict("records"))
        meth = p3[short(m)]["csat"]["best_v3_on_dev"].split("-")[1]
        gmap_p3 = {str(k): v for k, v in p3[short(m)]["csat"]["calibration_maps_fit_on_cal"][meth].items()}
        gmap_L = {str(k): v for k, v in fit_maps(cal.raw, cal.real)[meth].items()}
        bq = bucket_maps(cal_all.raw, cal_all.delay_bucket, real_by_delay, gmap_L)
        gexp = expected_map(cal.raw, tr_all.score.values)
        be = bucket_expected_maps(cal_all.raw, cal_all.delay_bucket, real_by_delay, gexp)
        cands = {
            "global (Phase 3 map, 100 cal rows)": lambda d: [gmap_p3[str(x)] for x in d.raw],
            f"global ({meth}, {len(cal)} cal rows)": lambda d: [gmap_L[str(x)] for x in d.raw],
            "delay-aware (per-bucket quantile)": lambda d: apply_bucket(bq, gmap_L, d.raw, d.delay_bucket),
            "delay-aware expected score (per-bucket quantile-interval mean)": lambda d: apply_bucket(be, gexp, d.raw, d.delay_bucket),
        }
        devres = {k: with_ci(dev.real, f(dev), dev.delay_bucket, DELAYS) for k, f in cands.items()}
        chosen = min(devres, key=lambda k: devres[k]["bucket_gap"])
        testres = {"raw (v2, no calibration)": with_ci(test.real, test.raw, test.delay_bucket, DELAYS)}
        testres.update({k: with_ci(test.real, f(test), test.delay_bucket, DELAYS) for k, f in cands.items()})
        r["csat"] = {"dev": {k: {"bucket_gap": v["bucket_gap"], "qwk": v["qwk"], "mae": v["mae"]} for k, v in devres.items()},
                     "chosen_on_dev": chosen, "test": testres, "n_cal_rows_per_bucket": cal_all.delay_bucket.value_counts().to_dict(),
                     "maps": {"global_large": gmap_L, "bucket_quantile": bq, "global_expected": gexp, "bucket_expected": be},
                     "invalid_json_rate": float(1 - pd.concat([cal_all, dev, test]).valid.mean())}
        exp_on = "expected" in chosen
        cal_main["models"][m] = {
            "method": meth, "map": gmap_L,
            "delay_aware": {"enabled": chosen.startswith("delay-aware"), "method": "expected" if exp_on else "quantile",
                            "bucket_maps": be if exp_on else bq, "global_map": gexp if exp_on else gmap_L,
                            "buckets_minutes": {"0-5 min": [0, 5], "5-30 min": [5, 30], "30 min-2 h": [30, 120], "2-8 h": [120, 480], "8 h+": [480, None]}},
            "chosen_on_dev": chosen,
            "test_after": {k: testres[chosen][k] for k in ("n", "mae", "mae_ci", "qwk", "qwk_ci", "wasserstein", "bucket_gap", "bucket_gap_ci")}}
        # CONV full test, Phase 3 chosen version/map (v2 raw; v3 map fitted on the CONV calibration sample)
        conv = frame(m, "conv", S[("conv", "test")].to_dict("records"))
        cv = p3[short(m)]["conv"]
        ch = cv["chosen_on_dev"]
        cmap = cv["calibration_maps_fit_on_cal"][ch.split("-")[1]] if ch.startswith("v3") else None
        r["conv"] = {"chosen_version_phase3": ch,
                     "raw_v2": with_ci(conv.real, conv.raw),
                     "chosen": with_ci(conv.real, [cmap[str(x)] for x in conv.raw] if cmap else conv.raw)}
        # fallback (Olist only)
        oc, od, ot = (frame(m, None, O[p].to_dict("records"), cache="fb") for p in ("cal", "dev", "test"))
        omaps = {k: {str(a): b for a, b in v.items()} for k, v in fit_maps(oc.raw, oc.real).items()}
        odev = {k: with_ci(od.real, [mp[str(x)] for x in od.raw]) for k, mp in omaps.items()}
        och = max(odev, key=lambda k: (odev[k]["qwk"], -odev[k]["wasserstein"]))
        omap = omaps[och]
        olate = bucket_maps(oc.raw, oc.late_bucket, real_by_late, omap)
        dg = with_ci(od.real, [omap[str(x)] for x in od.raw], od.late_bucket, LATE)["bucket_gap"]
        dl = with_ci(od.real, apply_bucket(olate, omap, od.raw, od.late_bucket), od.late_bucket, LATE)["bucket_gap"]
        fc = frame(m, None, te_rows.to_dict("records"), cache="fb")
        same = test.set_index("id").loc[fc.id].reset_index()
        r["fallback"] = {
            "olist_dev": {k: {"qwk": v["qwk"], "mae": v["mae"], "wasserstein": v["wasserstein"]} for k, v in odev.items()},
            "olist_chosen_on_dev": och, "lateness_dev_gap": {"global": dg, "lateness-aware": dl, "enabled": dl < dg},
            "olist_test": {"raw": with_ci(ot.real, ot.raw, ot.late_bucket, LATE),
                           f"fallback global ({och})": with_ci(ot.real, [omap[str(x)] for x in ot.raw], ot.late_bucket, LATE),
                           "fallback lateness-aware": with_ci(ot.real, apply_bucket(olate, omap, ot.raw, ot.late_bucket), ot.late_bucket, LATE)},
            "on_csat_test": {"fallback": with_ci(fc.real, [omap[str(x)] for x in fc.raw], fc.delay_bucket, DELAYS),
                             "main_on_same_rows": {k: with_ci(same.real, cands[k](same), same.delay_bucket, DELAYS)
                                                   for k in ("global (Phase 3 map, 100 cal rows)", chosen)}},
            "valid_json": float(pd.concat([oc, od, ot, fc]).valid.mean()), "map": omap, "lateness_maps": olate}
        q = np.sort(pd.read_csv(ROOT / "data" / "raw" / "trip-advisor-hotel-reviews" / "tripadvisor_hotel_reviews.csv").Rating.values)
        cdf = {k: (np.mean(oc.raw < k) + np.mean(oc.raw <= k)) / 2 for k in range(1, 6)}
        tmap = {str(k): int(q[min(int(cdf[k] * len(q)), len(q) - 1)]) for k in range(1, 6)}
        cal_fb["models"][m] = {"method": och, "map": omap,
                               "lateness_aware": {"enabled": bool(dl < dg), "bucket_maps": olate, "buckets_days_late": LATE},
                               "atlas_tripadvisor_distribution_map": tmap,
                               "test_olist": {k: r["fallback"]["olist_test"][f"fallback global ({och})"][k] for k in ("n", "mae", "mae_ci", "qwk", "qwk_ci", "wasserstein")},
                               "test_csat": {k: r["fallback"]["on_csat_test"]["fallback"][k] for k in ("n", "mae", "mae_ci", "qwk", "qwk_ci", "wasserstein")}}
        res[short(m)] = r
    save_json(res, RESULTS / "p7_large.json")
    cal_main.update({"fit_on": f"Flipkart CSAT train rows: {len(cal_nat)} natural + {len(topup)} bucket top-ups (>= {MIN_PER_BUCKET} per delay "
                               "bucket); bucket targets from the whole train split; chosen on 500 dev rows",
                     "source": "eCommerce Customer Service Satisfaction (Kaggle ddosad) - licence TO VERIFY"})
    cal_fb.update({"fit_on": f"Olist train split ({N_OLIST['cal']} calibration rows), chosen on {N_OLIST['dev']} Olist dev rows",
                   "source": "Olist (Kaggle olistbr) CC BY-NC-SA 4.0; TripAdvisor Hotel Reviews (Kaggle andrewmvd) CC BY-NC 4.0 for the "
                             "Atlas distribution-only map (off by default)", "use_with": "rubric_fallback.json"})
    save_json(cal_main, SIM / "calibration.json")
    save_json(cal_fb, SIM / "calibration_fallback.json")
    print(json.dumps({m: {"chosen": res[m]["csat"]["chosen_on_dev"]} for m in res if ":" in m}))


if __name__ == "__main__":
    {"run": run, "fit": fit}[sys.argv[1]](sys.argv[2:])
