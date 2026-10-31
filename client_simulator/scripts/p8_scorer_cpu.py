"""TASK3 step 3: classic CPU scorers. Train on train, choose on dev, report on each REAL test set (bootstrap 95% CIs).
(a) TF-IDF + logistic regression (expected score) / ridge; (b) gradient boosting on features + TF-IDF SVD;
(c) one model on all sources vs per-source; optional isotonic calibration (fit on dev half A, chosen on dev half B)."""
import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import hstack, csr_matrix
from sklearn.decomposition import TruncatedSVD
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression, Ridge

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import PROC, RESULTS, SEED, read_jsonl, save_json  # noqa: E402
from p7_large import with_ci, qwk_fast  # noqa: E402

L = PROC / "lean"
SRC = ["csat", "olist", "tripadvisor", "uss"]
BUCKETS = {"csat": ["0-5 min", "5-30 min", "30 min-2 h", "2-8 h", "8 h+"],
           "olist": ["on time or early", "1-3 days late", "4-7 days late", "8+ days late", "never delivered"]}
MODELS = RESULTS / "p8_models"
MODELS.mkdir(exist_ok=True)


def load(part):
    return pd.DataFrame(read_jsonl(L / f"scorer_{part}.jsonl"))


def feats(d):
    num = np.c_[d.text.str.len().values / 1000, pd.to_numeric(d.text.str.extract(r"turns: (\d+)")[0], errors="coerce").fillna(0).values]
    cat = pd.get_dummies(d[["source", "reason", "bucket"]].astype(str))
    return num, cat


def fit_tfidf_lr(tr):
    vec = TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_features=300000, sublinear_tf=True)
    X = vec.fit_transform(tr.text)
    lr = LogisticRegression(C=2.0, max_iter=300, solver="saga").fit(X, tr.label)
    return {"vec": vec, "lr": lr}


def pred_tfidf_lr(m, d):
    p = m["lr"].predict_proba(m["vec"].transform(d.text))
    return p @ m["lr"].classes_


def fit_tfidf_ridge(tr):
    vec = TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_features=300000, sublinear_tf=True)
    return {"vec": vec, "r": Ridge(alpha=2.0).fit(vec.fit_transform(tr.text), tr.label)}


def pred_tfidf_ridge(m, d):
    return np.clip(m["r"].predict(m["vec"].transform(d.text)), 1, 5)


def fit_gbm(tr):
    vec = TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_features=200000, sublinear_tf=True)
    X = vec.fit_transform(tr.text)
    svd = TruncatedSVD(96, random_state=SEED).fit(X)
    num, cat = feats(tr)
    cols = list(cat.columns)
    Z = np.c_[svd.transform(X), num, cat.values.astype(float)]
    g = HistGradientBoostingRegressor(max_iter=400, learning_rate=0.08, max_leaf_nodes=63, random_state=SEED).fit(Z, tr.label)
    return {"vec": vec, "svd": svd, "cols": cols, "g": g}


def pred_gbm(m, d):
    num, cat = feats(d)
    cat = cat.reindex(columns=m["cols"], fill_value=0)
    Z = np.c_[m["svd"].transform(m["vec"].transform(d.text)), num, cat.values.astype(float)]
    return np.clip(m["g"].predict(Z), 1, 5)


KINDS = {"tfidf_lr": (fit_tfidf_lr, pred_tfidf_lr), "tfidf_ridge": (fit_tfidf_ridge, pred_tfidf_ridge), "gbm_feats_svd": (fit_gbm, pred_gbm)}


def main():
    t0 = time.time()
    tr, dv, te = load("train"), load("dev"), load("test")
    rng = np.random.RandomState(SEED)
    dv["half"] = rng.rand(len(dv)) < 0.5  # True = half A (isotonic fit), False = half B (selection)
    preds = {}   # (kind, scope) -> {"dev": array, "test": array}
    log = {}
    for kind, (fit, pred) in KINDS.items():
        for scope in ["all"] + SRC:
            trs = tr if scope == "all" else tr[tr.source == scope]
            if kind == "gbm_feats_svd" and scope != "all" and len(trs) < 2000:
                continue
            s = time.time()
            m = fit(trs)
            pickle.dump(m, open(MODELS / f"{kind}__{scope}.pkl", "wb"))
            dsel = dv if scope == "all" else dv[dv.source == scope]
            tsel = te if scope == "all" else te[te.source == scope]
            preds[(kind, scope)] = {"dev": pd.Series(pred(m, dsel), index=dsel.index), "test": pd.Series(pred(m, tsel), index=tsel.index)}
            log[f"{kind}__{scope}"] = {"fit_s": round(time.time() - s, 1), "mb": round((MODELS / f"{kind}__{scope}.pkl").stat().st_size / 2**20, 1)}
            print(kind, scope, log[f"{kind}__{scope}"], flush=True)
    # choose per test source on dev half B; isotonic (fit on dev half A) as an option
    res = {"note": "trained on train; isotonic fitted on dev half A; choice on dev half B by QWK (tie: MAE); test reported once",
           "fit_log": log, "per_source": {}}
    for src in SRC:
        dA = dv[(dv.source == src) & dv.half]
        dB = dv[(dv.source == src) & ~dv.half]
        teS = te[te.source == src]
        cands = {}
        for (kind, scope), p in preds.items():
            if scope not in ("all", src):
                continue
            pa, pb, pt = p["dev"].reindex(dA.index), p["dev"].reindex(dB.index), p["test"].reindex(teS.index)
            for cal in ("none", "isotonic"):
                if cal == "isotonic":
                    iso = IsotonicRegression(y_min=1, y_max=5, out_of_bounds="clip").fit(pa.values, dA.label.values)
                    fb, ft = iso.predict(pb.values), iso.predict(pt.values)
                else:
                    fb, ft = pb.values, pt.values
                key = f"{kind} | {'all sources' if scope == 'all' else 'per-source'} | {cal}"
                ib = np.clip(np.floor(fb + 0.5), 1, 5).astype(int)
                cands[key] = {"dev_qwk": qwk_fast(dB.label.values, ib), "dev_mae": float(np.mean(np.abs(dB.label.values - ib))), "test_pred": ft}
        best = max(cands, key=lambda k: (cands[k]["dev_qwk"], -cands[k]["dev_mae"]))
        bk = BUCKETS.get(src)
        out = {"chosen_on_dev": best, "dev": {k: {"qwk": v["dev_qwk"], "mae": v["dev_mae"]} for k, v in cands.items()}}
        out["test_chosen"] = with_ci(teS.label.values, cands[best]["test_pred"], teS.bucket.values if bk else None, bk)
        # the same (unchosen) candidates on test, for transparency
        out["test_all_candidates"] = {k: {x: with_ci(teS.label.values, v["test_pred"])[x] for x in ("mae", "qwk", "within1_acc", "wasserstein")}
                                      for k, v in cands.items()}
        pd.DataFrame({"id": teS.id.values, "label": teS.label.values, "pred": cands[best]["test_pred"]}).to_csv(
            RESULTS / f"p8_scorer_cpu_test_{src}.csv", index=False)
        res["per_source"][src] = out
        print(src, best, round(out["test_chosen"]["qwk"], 3), round(out["test_chosen"]["mae"], 3), flush=True)
    # speed: ms per single score (one row at a time, CPU) for each kind, all-sources model
    sample = te.sample(200, random_state=SEED)
    res["ms_per_score"] = {}
    for kind, (_, pred) in KINDS.items():
        m = pickle.load(open(MODELS / f"{kind}__all.pkl", "rb"))
        s = time.time()
        for i in range(len(sample)):
            pred(m, sample.iloc[[i]])
        res["ms_per_score"][kind] = round(1000 * (time.time() - s) / len(sample), 2)
    res["seconds"] = round(time.time() - t0)
    save_json(res, RESULTS / "p8_scorer_cpu.json")


if __name__ == "__main__":
    main()
