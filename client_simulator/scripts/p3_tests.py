"""Phase 3 (S2): the three tests for each candidate simulator model. Resumable (LLM cache).

python p3_tests.py test1 MODEL...            # quick role-play test (3 cards)
python p3_tests.py test2 MODEL...            # realism vs real messages (30 cards x 3 turns x with/without examples)
python p3_tests.py test3 MODEL... [--n ...]  # satisfaction score vs real scores (CONV + CSAT, v1/v2)
python p3_tests.py eval MODEL...             # metrics, calibration (v3), selection on dev, test numbers
"""
import argparse
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import CACHE, PROC, RESULTS, SEED, load_json, read_jsonl, save_json, score_metrics  # noqa: E402
from llm import cached_chat, parse_score, short, unload_all  # noqa: E402
from p3_make_cards import all_cards, test1_cards  # noqa: E402
from realism import profile, realism_distance  # noqa: E402
from simulator.prompts import breaks_role, roleplay_messages, score_messages  # noqa: E402

RS = PROC / "real_scores"
RM = PROC / "real_messages"
WORKERS = 2
RP_OPTS = dict(temperature=0.8, num_predict=120)
SC_OPTS = dict(temperature=0.0, num_predict=100)

# ------------------------------------------------------------------ test 1
T1_AGENT = "Could you confirm your order number?"


def test1(models):
    cards = test1_cards()
    for m in models:
        for c in cards:
            first = cached_chat("test1", m, "rp1", f"{c['id']}:first", roleplay_messages(c, []), **RP_OPTS)
            hist = [{"role": "customer", "text": first["text"].strip()}, {"role": "agent", "text": T1_AGENT}]
            cached_chat("test1", m, "rp1", f"{c['id']}:reply", roleplay_messages(c, hist), **RP_OPTS)
        print("test1 done", m)


# ------------------------------------------------------------------ test 2
def _real_examples(company, k, seed):
    rows = [r for r in read_jsonl(RM / "first_messages.jsonl") if r["company"] == company]
    rng = random.Random(seed)
    pool = [r["text"] for r in rows if 6 <= len(r["text"].split()) <= 40 and "<URL>" not in r["text"]]
    return rng.sample(pool, k)


def _agent_replies():
    rows = read_jsonl(RM / "agent_replies_sample.jsonl")
    return {c: [r["reply_text"] for r in rows if r["company"] == c and len(r["reply_text"].split()) >= 6] for c in ("shopnova", "atlas")}


def test2(models):
    cards = all_cards()
    replies = _agent_replies()
    for m in models:
        jobs = []
        for i, c in enumerate(cards):
            rng = random.Random(SEED + i)
            agent_turns = rng.sample(replies[c["company"]], 2)
            for cond in ("noex", "ex5"):
                ex = _real_examples(c["company"], 5, SEED + i) if cond == "ex5" else None
                jobs.append((c, cond, ex, agent_turns))

        def run(job):
            c, cond, ex, agent_turns = job
            hist = []
            for t in range(3):
                r = cached_chat("test2", m, f"rp1-{cond}", f"{c['id']}:t{t}", roleplay_messages(c, hist, ex), **RP_OPTS)
                hist.append({"role": "customer", "text": r["text"].strip()})
                if t < 2:
                    hist.append({"role": "agent", "text": agent_turns[t]})
        with ThreadPoolExecutor(WORKERS) as ex_:
            list(ex_.map(run, jobs))
        print("test2 done", m)


def eval_test2(models):
    real = load_json(RESULTS / "p2_real_numbers_and_profile.json")["realism_profile"]
    real_first = real["all_first"]
    lt = [r for r in read_jsonl(RM / "later_turns_sample.jsonl")]
    rl = pd.DataFrame(lt).groupby("company").sample(1500, random_state=SEED)
    real_later = profile(rl.text.tolist(), rl.company.tolist())
    cache = pd.DataFrame(read_jsonl(CACHE / "test2.jsonl"))
    comp = {c["id"]: c["company"] for c in all_cards()}
    out = {"real_first": real_first, "real_later": real_later}
    for m in models:
        out[short(m)] = {}
        for cond in ("noex", "ex5"):
            d = cache[(cache.model == m) & (cache.pv == f"rp1-{cond}")]
            if d.empty:
                continue
            d = d.assign(card=d.item.str.split(":").str[0], turn=d.item.str.split(":").str[1])
            f = d[d.turn == "t0"]
            l = d[d.turn != "t0"]
            pf = profile(f.text.str.strip().tolist(), f.card.map(comp).tolist())
            pl = profile(l.text.str.strip().tolist(), l.card.map(comp).tolist())
            df, parts_f = realism_distance(pf, real_first)
            dl, _ = realism_distance(pl, real_later)
            out[short(m)][cond] = {"profile_first": pf, "profile_later": pl, "distance_first": df,
                                   "distance_later": dl, "distance_mean": (df + dl) / 2, "parts_first": parts_f,
                                   "breaks_role_rate": float(d.text.map(breaks_role).mean()), "n_messages": int(len(d))}
    save_json(out, RESULTS / "p3_test2_realism.json")
    return out


# ------------------------------------------------------------------ test 3
REASON_TXT = {"late_delivery": "a late delivery", "order_status": "the status of your order",
              "refund_request": "a refund", "return_item": "returning an item", "damaged_item": "a damaged, wrong or missing item",
              "other": "another question"}
CHANNEL_TXT = {"Inbound": "by phone (you called them)", "Outcall": "by phone (they called you back)", "Email": "by email"}
DELAY_TXT = {"0-5 min": "less than 5 minutes", "5-30 min": "5 to 30 minutes", "30 min-2 h": "30 minutes to 2 hours",
             "2-8 h": "2 to 8 hours", "8 h+": "more than 8 hours"}


def has_remark(r):
    """Remark present? (missing remarks come back from pandas as NaN, which is truthy)"""
    return isinstance(r.get("remark"), str) and bool(r["remark"].strip())


def csat_card(r):
    s = (f"You are a customer of ShopNova, an online shop. You contacted customer service {CHANNEL_TXT.get(r['channel'], '')} "
         f"about {REASON_TXT[r['reason']]} (topic: {r['sub_category']}). ")
    s += (f"You waited {DELAY_TXT[r['delay_bucket']]} for the first answer. " if r["delay_bucket"] in DELAY_TXT
          else "The waiting time is not known. ")
    s += f'After the contact you wrote this remark: "{r["remark"]}"' if has_remark(r) else "You did not write a remark."
    return s


def conv_card(r):
    return ("You are a traveller who chatted with an automated travel booking assistant (hotels, trains, taxis, "
            f'flights, restaurants). What you wanted at the start: "{r["goal"]}"')


CONV_SHOT_COMMENT = {1: "It did not get me what I needed at all.", 2: "I had to repeat myself and it still got things wrong.",
                     3: "It did the job, nothing special.", 4: "Quick and it answered everything I asked.",
                     5: "Perfect, exactly what I wanted."}


def build_rubrics():
    """Rubric lines + balanced few-shot examples, computed from the TRAIN splits only."""
    tr = pd.DataFrame(read_jsonl(RS / "csat_allrows_train.jsonl"))
    dist = tr.score.value_counts(normalize=True)
    p = {k: round(100 * dist.get(k, 0)) for k in range(1, 6)}
    bd = tr.groupby("delay_bucket").score.agg(["mean", lambda x: (x == 1).mean()])
    br = tr.groupby("reason").score.mean()
    rem = tr[tr.remark.notna()]
    neg = rem.remark.str.lower().str.contains(r"\bnot\b|worst|bad|poor|pathetic|useless|never|no response|waste")
    pos = rem.remark.str.lower().str.contains(r"good|thank|nice|happy|great|excellent|satisf|helpful") & ~neg
    csat_lines = [
        f"Out of 100 real customers, {p[5]} give 5, {p[4]} give 4, {p[3]} give 3, {p[2]} give 2 and {p[1]} give 1. "
        "Most give 5 unless something went wrong; 2 and 3 are rare.",
        "Waiting time matters: answered in under 5 minutes the average is "
        f"{bd.loc['0-5 min', 'mean']:.2f}; after more than 8 hours it is {bd.loc['8 h+', 'mean']:.2f} and "
        f"{100 * bd.loc['8 h+', '<lambda_0>']:.0f}% give 1 (vs {100 * bd.loc['0-5 min', '<lambda_0>']:.0f}% when answered fast).",
        f"Late deliveries score lowest (average {br['late_delivery']:.2f}); damaged-item contacts highest ({br['damaged_item']:.2f}).",
        f"Customers whose remark is negative (not solved, worst, bad, pathetic) give 1 in {100 * (rem[neg].score == 1).mean():.0f}% "
        f"of cases (average {rem[neg].score.mean():.2f}); customers whose remark is positive (good, thanks, happy) give 5 in "
        f"{100 * (rem[pos].score == 5).mean():.0f}% of cases (average {rem[pos].score.mean():.2f}).",
        f"Customers who wrote no remark average {tr[tr.remark.isna()].score.mean():.2f}.",
    ]
    rng = np.random.RandomState(SEED)
    shots_csat = []
    for s in (1, 5, 2, 4, 3):
        cand = rem[(rem.score == s) & rem.remark.str.split().str.len().between(3, 20)]
        r = cand.iloc[rng.randint(len(cand))]
        shots_csat.append({"id": r["id"], "prompt": csat_card(r), "score": int(s), "comment": r["remark"]})

    ct = pd.DataFrame(read_jsonl(RS / "conv_train.jsonl"))
    cd = ct.score.value_counts(normalize=True)
    q = {k: round(100 * cd.get(k, 0)) for k in range(1, 6)}
    ct["any_low"] = ct.turns.apply(lambda ts: any(np.mean(t.get("turn_sat", [3])) <= 2 for t in ts if t["role"] == "user"))
    conv_lines = [
        f"Out of 100 real ratings of such chats, {q[3]} are 3, {q[4]} are 4, {q[2]} are 2, {q[1]} are 1 and {q[5]} are 5. "
        "3 is the normal score for a chat that did its job.",
        f"Chats where at least one of the user's requests went badly average {ct[ct.any_low].score.mean():.2f}; "
        f"the others average {ct[~ct.any_low].score.mean():.2f}.",
        f"Very short chats (6 user turns or fewer) average {ct[ct.n_user_turns <= 6].rating_mean.mean():.2f}; "
        f"longer ones average {ct[ct.n_user_turns > 6].rating_mean.mean():.2f}.",
    ]
    shots_conv = []
    for s in (2, 4, 3):
        cand = ct[ct.score == s]
        r = cand.iloc[rng.randint(len(cand))]
        tr_short = r["turns"][-8:]
        prompt = conv_card(r) + "\n\nThe conversation (last turns):\n" + "\n".join(
            ("Customer: " if x["role"] == "user" else "Agent: ") + x["text"] for x in tr_short)
        shots_conv.append({"id": r["id"], "prompt": prompt, "score": int(s), "comment": CONV_SHOT_COMMENT[s]})
    rub = {"csat": {"lines": csat_lines, "shots": shots_csat}, "conv": {"lines": conv_lines, "shots": shots_conv},
           "note": "computed from train splits only; CSAT shot comments are the customers' real remarks; "
                   "CONV shot comments were written by us (USS has no comments), their scores are real"}
    save_json(rub, RESULTS / "p3_rubrics_from_train.json")
    return rub


def samples(n):
    """Fixed-seed natural-distribution samples. Few-shot ids are excluded from the calibration set."""
    rub = load_json(RESULTS / "p3_rubrics_from_train.json")
    shot_ids = {s["id"] for k in ("csat", "conv") for s in rub[k]["shots"]}
    out = {}
    for name, f in (("conv", "conv"), ("csat", "csat_allrows")):
        for part, k in (("cal", "train"), ("dev", "dev"), ("test", "test")):
            d = pd.DataFrame(read_jsonl(RS / f"{f}_{k}.jsonl"))
            d = d[~d.id.isin(shot_ids)]
            out[(name, part)] = d.sample(min(n[f"{name}_{part}"], len(d)), random_state=SEED)
    return out


def score_call(m, name, version, r, rub):
    card = csat_card(r) if name == "csat" else conv_card(r)
    transcript = None
    if name == "conv":
        transcript = [{"role": "customer" if t["role"] == "user" else "agent", "text": t["text"]} for t in r["turns"]]
    msgs = score_messages(card, transcript, version, rubric=rub[name], shots=rub[name]["shots"])
    return cached_chat(f"test3_{name}", m, f"s{version[1]}", r["id"], msgs, num_ctx=6144, **SC_OPTS)


def test3(models, n, versions=("v1", "v2")):
    rub = build_rubrics()
    S = samples(n)
    for m in models:
        jobs = []
        for name in ("conv", "csat"):
            for part in ("dev", "cal", "test"):
                for v in versions:
                    if v == "v1" and part != "dev":
                        continue  # v1 is only needed to choose the version on dev
                    jobs += [(name, v, r) for r in S[(name, part)].to_dict("records")]
        with ThreadPoolExecutor(WORKERS) as ex:
            list(ex.map(lambda j: score_call(m, j[0], j[1], j[2], rub), jobs))
        print("test3 done", m, len(jobs), "calls")


# ------------------------------------------------------------------ calibration + evaluation
def fit_maps(raw, real):
    raw, real = np.asarray(raw), np.asarray(real)
    maps = {}
    med = {}
    for k in range(1, 6):
        sel = real[raw == k]
        med[k] = int(np.median(sel)) if len(sel) else None
    # fill unseen raw levels with the nearest seen level
    seen = [k for k in med if med[k] is not None]
    maps["median"] = {k: (med[k] if med[k] is not None else med[min(seen, key=lambda s: abs(s - k))]) for k in range(1, 6)}
    iso = IsotonicRegression(y_min=1, y_max=5, out_of_bounds="clip").fit(raw, real)
    maps["isotonic"] = {k: int(np.clip(np.floor(iso.predict([k])[0] + 0.5), 1, 5)) for k in range(1, 6)}
    # distribution matching: map raw quantile (mid-rank) to the real quantile
    cdf_raw = {k: (np.mean(raw < k) + np.mean(raw <= k)) / 2 for k in range(1, 6)}
    q = np.sort(real)
    maps["quantile"] = {k: int(q[min(int(cdf_raw[k] * len(q)), len(q) - 1)]) for k in range(1, 6)}
    return maps


def apply_map(mp, raw):
    return [mp[int(x)] for x in raw]


def collect(m, name, version, part, S):
    cache = {r["item"]: r for r in read_jsonl(CACHE / f"test3_{name}.jsonl")
             if r["model"] == m and r["pv"] == f"s{version[1]}"}
    rows = []
    for r in S[(name, part)].to_dict("records"):
        c = cache.get(r["id"])
        if c is None:
            continue
        s, comment, valid = parse_score(c["text"])
        rows.append({"id": r["id"], "real": r["score"], "raw": s, "valid_json": valid, "parsed": s is not None,
                     "breaks_role": breaks_role(comment or c["text"]), "comment": comment,
                     "reason": r.get("reason"), "delay_bucket": r.get("delay_bucket"), "has_remark": has_remark(r),
                     "wall_s": c.get("wall_s")})
    return pd.DataFrame(rows)


def evaluate(models, n):
    S = samples(n)
    base = load_json(RESULTS / "p1_baselines.json")
    out = {"sample_sizes": n, "selection_rule": "highest dev QWK (tie: lower dev Wasserstein)"}
    # baselines on the exact same test subsets
    for name, bkey, f in (("conv", "conv", "conv"), ("csat", "csat_allrows", "csat_allrows")):
        te = S[(name, "test")]
        pred = pd.read_csv(RESULTS / f"p1_tfidf_pred_{bkey}_test.csv").set_index("id").pred
        maj = base[bkey]["majority_class"]
        out[f"baseline_{name}"] = {"majority": score_metrics(te.score, [maj] * len(te)),
                                   "tfidf_lr": score_metrics(te.score, pred.reindex(te.id).values)}
    for m in models:
        res = {}
        for name in ("conv", "csat"):
            r = {}
            dev1 = collect(m, name, "v1", "dev", S)
            dev2, cal2, test2 = (collect(m, name, "v2", p, S) for p in ("dev", "cal", "test"))
            if dev2.empty or test2.empty:
                continue
            fill = 3 if name == "conv" else 5  # unparseable output -> majority class (counted in invalid rate)
            for d in (dev1, dev2, cal2, test2):
                if not d.empty:
                    d["raw_f"] = d.raw.fillna(fill).astype(int)
            maps = fit_maps(cal2.raw_f, cal2.real)
            cand = {}
            if not dev1.empty:
                cand["v1"] = score_metrics(dev1.real, dev1.raw_f)
            cand["v2"] = score_metrics(dev2.real, dev2.raw_f)
            for k, mp in maps.items():
                cand[f"v3-{k}"] = score_metrics(dev2.real, apply_map(mp, dev2.raw_f))
            best = max(cand, key=lambda k: (cand[k]["qwk"], -cand[k]["wasserstein"]))
            r["dev"] = cand
            r["chosen_on_dev"] = best
            r["calibration_maps_fit_on_cal"] = maps
            r["test_v2_before_calibration"] = score_metrics(test2.real, test2.raw_f)
            best_v3 = max([k for k in cand if k.startswith("v3")], key=lambda k: (cand[k]["qwk"], -cand[k]["wasserstein"]))
            r["best_v3_on_dev"] = best_v3
            r["test_v3_after_calibration"] = score_metrics(test2.real, apply_map(maps[best_v3.split("-")[1]], test2.raw_f))
            if best == "v1":
                t1 = collect(m, name, "v1", "test", S)
                t1["raw_f"] = t1.raw.fillna(fill).astype(int)
                r["test_chosen"] = score_metrics(t1.real, t1.raw_f)
                chosen = t1.assign(pred=t1.raw_f)
            elif best == "v2":
                r["test_chosen"] = r["test_v2_before_calibration"]
                chosen = test2.assign(pred=test2.raw_f)
            else:
                r["test_chosen"] = r["test_v3_after_calibration"]
                chosen = test2.assign(pred=apply_map(maps[best.split("-")[1]], test2.raw_f))
            chosen[["id", "real", "pred"]].to_csv(RESULTS / f"p3_test3_{name}_{short(m).replace(':', '_').replace('/', '_')}_chosen_test.csv", index=False)
            allv2 = pd.concat([dev2, cal2, test2])
            r["invalid_json_rate_v2"] = float(1 - allv2.valid_json.mean())
            r["unparseable_rate_v2"] = float(1 - allv2.parsed.mean())
            r["breaks_role_rate_v2"] = float(allv2.breaks_role.mean())
            if not dev1.empty:
                r["invalid_json_rate_v1"] = float(1 - dev1.valid_json.mean())
            r["sec_per_score_call"] = float(allv2.wall_s.dropna().mean())
            if name == "csat":
                mp = maps[best_v3.split("-")[1]]
                t = test2.assign(cal=apply_map(mp, test2.raw_f))
                r["test_by_reason"] = {k: {"n": len(g), "real_mean": g.real.mean(), "raw_mean": g.raw_f.mean(), "cal_mean": g.cal.mean()}
                                       for k, g in t.groupby("reason")}
                r["test_by_delay"] = {k: {"n": len(g), "real_mean": g.real.mean(), "raw_mean": g.raw_f.mean(), "cal_mean": g.cal.mean()}
                                      for k, g in t.groupby("delay_bucket")}
                r["test_by_has_remark"] = {str(k): {"n": len(g), "real_mean": g.real.mean(), "raw_mean": g.raw_f.mean(), "cal_mean": g.cal.mean()}
                                           for k, g in t.groupby("has_remark")}
            test2.assign(model=short(m)).to_csv(RESULTS / f"p3_test3_{name}_{short(m).replace(':', '_').replace('/', '_')}_test.csv", index=False)
            res[name] = r
        out[short(m)] = res
    save_json(out, RESULTS / "p3_test3_scores.json")
    return out


DEFAULT_N = {"conv_cal": 60, "conv_dev": 60, "conv_test": 120, "csat_cal": 100, "csat_dev": 100, "csat_test": 200}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("models", nargs="*")
    ap.add_argument("--n", type=str, default="")
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    WORKERS = a.workers
    n = dict(DEFAULT_N)
    for kv in filter(None, a.n.split(",")):
        k, v = kv.split("=")
        n[k] = int(v)
    if a.cmd == "test1":
        test1(a.models)
    elif a.cmd == "test2":
        test2(a.models)
    elif a.cmd == "test3":
        test3(a.models, n)
    elif a.cmd == "eval2":
        print(eval_test2(a.models))
    elif a.cmd == "eval":
        evaluate(a.models, n)
    elif a.cmd == "test3v1test":  # v1 on the test sample, needed only when dev selects v1
        rub = build_rubrics()
        S = samples(n)
        for m in a.models:
            for name in ("conv", "csat"):
                jobs = S[(name, "test")].to_dict("records")
                with ThreadPoolExecutor(WORKERS) as ex:
                    list(ex.map(lambda r: score_call(m, name, "v1", r, rub), jobs))
    elif a.cmd == "rubric":
        print(build_rubrics())
    if a.cmd in ("test1", "test2", "test3"):
        unload_all()
