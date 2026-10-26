"""Worker F v5 — F2: why do Agent F predictions "collapse" toward ~3? (builds on v4/f/diagnose_shift.py)

    $PY -m v5.f.collapse extract      # frozen pretrained e5-small embeddings (TRAIN/VAL/TEST) -> $FV5/emb_e5_256.npz
    $PY -m v5.f.collapse analyse      # all analyses -> v5/f/results/f2_collapse.json + figures/f2_*.png

What v4 already showed (not redone): inference is correct, ShopNova texts are not truncated, the ShopNova shape
carries ~no USS signal. What v5 adds, on USS where labels exist:
  A. per-class error on rounded labels (MAE, signed error, counts) — VAL and the already-inspected V3 TEST preds;
  B. calibration curves (mean label per prediction decile) and prediction distributions per sub-corpus;
  C. regression to the mean, quantified two ways:
       slope of prediction on label  b(p|y) = cov(y,p)/var(y)   (1 = no shrinkage, 0 = constant)
       slope of label on prediction  b(y|p) = cov(y,p)/var(p)   (1 = calibrated, >1 = predictions too compressed)
     For a calibrated predictor p = E[y|x], b(p|y) = var(p)/var(y) = R^2: shrinkage is EXPECTED when the text
     explains little of the label. So "compression" is only a defect if b(y|p) is clearly above 1.
  D. effect of truncation side (head vs tail) and length (128/256/512/full) with the V3 Ridge recipe (VAL only);
  E. does the loss/head compress outputs? Same features, same data, VAL only:
       TF-IDF (V3 recipe):    Ridge (MSE) | Huber (SGD, eps 0.5) | ordinal (cumulative binary logistic, Frank & Hall)
       frozen e5 embeddings:  linear MSE | Huber | ordinal | 2-layer MLP MSE (like the fine-tuned head)
  F. "inflating" predictions to the label SD (de-shrinking around the mean) — shown only to quantify the MAE cost;
     it is NOT used by any model.
TEST predictions used here are the V3 ones that were already inspected in V3/V4 (diagnostic only; no selection).
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from v5.f.common import (FIG, FV5, RESULTS, V3_RESULTS, load, mae, qwk, slope, spearman, to_int,  # noqa: E402
                         write_json, y_of)

EMB = FV5 / "emb_e5_256.npz"


def extract():
    """Mean-pooled embeddings of the PRETRAINED (not fine-tuned) multilingual-e5-small, last 256 tokens."""
    import torch
    from transformers import AutoModel, AutoTokenizer
    from real_data.eval_f_v2 import ENC, PREFIX, REVISION
    torch.set_num_threads(1)
    tok = AutoTokenizer.from_pretrained(ENC["e5small"], revision=REVISION["e5small"])
    tok.truncation_side = "left"
    m = AutoModel.from_pretrained(ENC["e5small"], revision=REVISION["e5small"]).float().eval()
    out = {}
    for s in ("train", "val", "test"):
        X = [PREFIX["e5small"] + r["text"] for r in load(s)]
        embs = []
        with torch.no_grad():
            for i in range(0, len(X), 32):
                b = tok(X[i:i + 32], padding=True, truncation=True, max_length=256, return_tensors="pt")
                h = m(**b).last_hidden_state
                a = b["attention_mask"].unsqueeze(-1)
                embs.append(((h * a).sum(1) / a.sum(1)).numpy())
                if i % 640 == 0:
                    print(s, i, flush=True)
        out[s] = np.concatenate(embs).astype(np.float32)
    np.savez_compressed(EMB, **out)
    print("saved", EMB)


# ---------------- analysis helpers ----------------
def per_class(y, p):
    yi = to_int(y)
    p = np.clip(p, 1, 5)
    return {int(k): {"n": int((yi == k).sum()), "mae": round(float(np.abs(p[yi == k] - y[yi == k]).mean()), 3),
                     "signed": round(float((p[yi == k] - y[yi == k]).mean()), 3),
                     "mean_pred": round(float(p[yi == k].mean()), 3)} for k in range(1, 6) if (yi == k).any()}


def summary(y, p, langs=None):
    p = np.clip(np.asarray(p, float), 1, 5)
    out = {"mae": round(mae(y, p), 4), "spearman": round(spearman(y, p), 4), "qwk": round(qwk(y, p), 4),
           "pred_sd": round(float(p.std()), 4), "label_sd": round(float(y.std()), 4),
           "slope_pred_on_label": round(slope(y, p), 4),
           "slope_label_on_pred": round(float(np.cov(y, p, bias=True)[0, 1] / max(p.var(), 1e-12)), 4),
           "r2": round(float(1 - ((y - p) ** 2).mean() / y.var()), 4), "per_class": per_class(y, p),
           "mae_dissatisfied_le2.5": round(mae(y[y <= 2.5], p[y <= 2.5]), 4) if (y <= 2.5).any() else None,
           "mae_high_ge4": round(mae(y[y >= 4], p[y >= 4]), 4) if (y >= 4).any() else None}
    if langs is not None:
        langs = np.asarray(langs)
        for lg in ("en", "zh"):
            k = langs == lg
            out[lg] = {kk: v for kk, v in summary(y[k], p[k]).items() if kk != "per_class"}
            out[lg]["per_class"] = per_class(y[k], p[k])
    return out


def calib_curve(y, p, n=10):
    p = np.clip(p, 1, 5)
    q = np.quantile(p, np.linspace(0, 1, n + 1))
    b = np.clip(np.searchsorted(q, p, side="right") - 1, 0, n - 1)
    return [{"mean_pred": round(float(p[b == i].mean()), 3), "mean_label": round(float(y[b == i].mean()), 3),
             "n": int((b == i).sum())} for i in range(n) if (b == i).any()]


def v3_test_preds():
    """Best-seed-by-VAL TEST predictions stored by V3 (already inspected in V3/V4)."""
    out = {}
    for name, f in (("tfidf_ridge_tail256 (V3)", "tfidf_ridge_tail256tok.json"),
                    ("e5_trim_L6_256 (V3)", "e5small_trim_ft_L6_frac0.5_len256.json"),
                    ("tfidf_logreg_EV (V3)", "tfidf_logreg.json"),
                    ("group_mean (V3)", "group_mean.json")):
        d = json.loads((V3_RESULTS / f).read_text())
        run = next(r for r in d["runs"] if r.get("seed", 0) == d["best_seed_by_val"])
        out[name] = (d["test_ids"], np.array(run["test_pred"], float))
    return out


# ---------------- E. losses on the same features ----------------
def ordinal_fit_predict(Ftr, ytr, Fva, C):
    """Frank & Hall ordinal regression: one binary logistic model per threshold P(y > t), t = 1.5..4.5 on the
    continuous mean label; prediction = 1 + sum_t P(y > t) (expected value under the cumulative model)."""
    from sklearn.linear_model import LogisticRegression
    p = np.ones(Fva.shape[0])
    for t in (1.5, 2.5, 3.5, 4.5):
        z = (ytr > t).astype(int)
        if z.min() == z.max():
            p += z[0]
            continue
        p += LogisticRegression(C=C, max_iter=3000).fit(Ftr, z).predict_proba(Fva)[:, 1]
    return p


def loss_compare_tfidf(tr, va):
    from sklearn.linear_model import Ridge, SGDRegressor
    from v5.f.ridge_v5 import BASE, RidgeV5
    m = RidgeV5(BASE).fit_vec(tr)
    Ftr, Fva = m.X(tr), m.X(va)
    ytr, yva = y_of(tr), y_of(va)
    langs = [r["lang"] for r in va]
    res, preds = {}, {}
    best = min(((mae(yva, Ridge(alpha=a).fit(Ftr, ytr).predict(Fva)), a) for a in (1, 3, 10)))
    preds["ridge_mse"] = Ridge(alpha=best[1]).fit(Ftr, ytr).predict(Fva)
    res["ridge_mse"] = {"alpha": best[1]}
    hub = []
    for a in (1e-6, 1e-5, 1e-4):
        sg = SGDRegressor(loss="huber", epsilon=0.5, alpha=a, max_iter=50, tol=None, random_state=0,
                          learning_rate="invscaling", eta0=0.05)
        sg.fit(Ftr, ytr - ytr.mean())
        hub.append((mae(yva, sg.predict(Fva) + ytr.mean()), a, sg.predict(Fva) + ytr.mean()))
    h = min(hub, key=lambda x: x[0])
    preds["sgd_huber_eps0.5"], res["sgd_huber_eps0.5"] = h[2], {"alpha": h[1]}
    sq = []
    for a in (1e-6, 1e-5, 1e-4):          # same optimiser with squared loss: isolates the loss from the solver
        sg = SGDRegressor(loss="squared_error", alpha=a, max_iter=50, tol=None, random_state=0,
                          learning_rate="invscaling", eta0=0.05)
        sg.fit(Ftr, ytr - ytr.mean())
        sq.append((mae(yva, sg.predict(Fva) + ytr.mean()), a, sg.predict(Fva) + ytr.mean()))
    s = min(sq, key=lambda x: x[0])
    preds["sgd_squared"], res["sgd_squared"] = s[2], {"alpha": s[1]}
    o = min(((mae(yva, ordinal_fit_predict(Ftr, ytr, Fva, C)), C) for C in (3, 10, 30)))
    preds["ordinal_frank_hall"] = ordinal_fit_predict(Ftr, ytr, Fva, o[1])
    res["ordinal_frank_hall"] = {"C": o[1]}
    for k in preds:
        res[k].update(summary(yva, preds[k], langs))
    return res, preds


def loss_compare_emb(tr, va):
    import torch
    from sklearn.linear_model import HuberRegressor, Ridge
    from sklearn.preprocessing import StandardScaler
    E = np.load(EMB)
    sc = StandardScaler().fit(E["train"])
    Ftr, Fva = sc.transform(E["train"]), sc.transform(E["val"])
    ytr, yva = y_of(tr), y_of(va)
    langs = [r["lang"] for r in va]
    res, preds = {}, {}
    b = min(((mae(yva, Ridge(alpha=a).fit(Ftr, ytr).predict(Fva)), a) for a in (10, 100, 1000)))
    preds["linear_mse"], res["linear_mse"] = Ridge(alpha=b[1]).fit(Ftr, ytr).predict(Fva), {"alpha": b[1]}
    b = min(((mae(yva, HuberRegressor(epsilon=1.35, alpha=a, max_iter=2000).fit(Ftr, ytr).predict(Fva)), a)
             for a in (1, 10, 100)))
    preds["linear_huber"] = HuberRegressor(epsilon=1.35, alpha=b[1], max_iter=2000).fit(Ftr, ytr).predict(Fva)
    res["linear_huber"] = {"alpha": b[1], "epsilon": 1.35}
    o = min(((mae(yva, ordinal_fit_predict(Ftr, ytr, Fva, C)), C) for C in (0.01, 0.1, 1)))
    preds["ordinal_frank_hall"], res["ordinal_frank_hall"] = ordinal_fit_predict(Ftr, ytr, Fva, o[1]), {"C": o[1]}
    # small MLP head like the fine-tuned model (384 -> 64 -> 1), MSE vs Huber, epochs picked on VAL
    torch.manual_seed(0)
    torch.set_num_threads(1)
    Xt, Yt, Xv = torch.tensor(Ftr, dtype=torch.float32), torch.tensor(ytr, dtype=torch.float32), \
        torch.tensor(Fva, dtype=torch.float32)
    for lname in ("mse", "huber"):
        torch.manual_seed(0)
        net = torch.nn.Sequential(torch.nn.Dropout(0.1), torch.nn.Linear(Ftr.shape[1], 64), torch.nn.ReLU(),
                                  torch.nn.Linear(64, 1))
        opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=0.01)
        best = (1e9, None, 0)
        for ep in range(60):
            net.train()
            perm = torch.randperm(len(Xt))
            for i in range(0, len(Xt), 64):
                idx = perm[i:i + 64]
                out = net(Xt[idx]).squeeze(-1) + 3.0
                loss = torch.nn.functional.mse_loss(out, Yt[idx]) if lname == "mse" else \
                    torch.nn.functional.huber_loss(out, Yt[idx], delta=0.5)
                opt.zero_grad()
                loss.backward()
                opt.step()
            net.eval()
            with torch.no_grad():
                pv = (net(Xv).squeeze(-1) + 3.0).numpy()
            if mae(yva, pv) < best[0]:
                best = (mae(yva, pv), pv, ep + 1)
        preds[f"mlp_{lname}"], res[f"mlp_{lname}"] = best[1], {"best_epoch": best[2]}
    for k in preds:
        res[k].update(summary(yva, preds[k], langs))
    return res, preds


def truncation(tr, va):
    """V3 Ridge recipe with different windows: tail (end kept) vs head (start kept), 128/256/512 tokens, full."""
    from v4.f.tfidf_predictor import CHARS_PER_TOKEN
    from v5.f.ridge_v5 import BASE, fit_config
    out = {}
    for side in ("tail", "head"):
        for n in (128, 256, 512):
            def cutf(rows, n=n, side=side):
                res = []
                for r in rows:
                    k = int(n * CHARS_PER_TOKEN[r["lang"]])
                    res.append({**r, "text": r["text"][-k:] if side == "tail" else r["text"][:k]})
                return res
            _, _, info, _ = fit_config({**BASE, "tail": 0}, cutf(tr), cutf(va))
            out[f"{side}{n}"] = {k: round(info[k], 4) if isinstance(info[k], float) else info[k]
                                 for k in ("val_mae", "val_mae_en", "val_mae_zh", "val_spearman", "val_slope", "alpha")}
            print(side, n, out[f"{side}{n}"], flush=True)
    _, _, info, _ = fit_config({**BASE, "tail": 0}, tr, va)
    out["full"] = {k: info[k] for k in ("val_mae", "val_mae_en", "val_mae_zh", "val_spearman", "val_slope", "alpha")}
    return out


def analyse():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    tr, va, te = load("train"), load("val"), load("test")
    yva, yte = y_of(va), y_of(te)
    lva, lte = [r["lang"] for r in va], [r["lang"] for r in te]
    res = {}
    grid = json.loads((RESULTS / "f3_ridge_grid.json").read_text())
    pv_ridge = np.array(grid["val_preds"]["B_v3"])
    res["val_ridge_v3recipe"] = summary(yva, pv_ridge, lva)
    # A/B/C on the V3 TEST predictions (already inspected; diagnostic only)
    tp = v3_test_preds()
    res["test_v3_models"] = {}
    for name, (ids, p) in tp.items():
        assert ids == [r["id"] for r in te]
        res["test_v3_models"][name] = summary(yte, p, lte)
        res["test_v3_models"][name]["calibration_deciles"] = calib_curve(yte, p)
        res["test_v3_models"][name]["by_sub"] = {
            s: {"label_mean": round(float(yte[m].mean()), 3), "label_sd": round(float(yte[m].std()), 3),
                "pred_mean": round(float(np.clip(p[m], 1, 5).mean()), 3), "pred_sd": round(float(np.clip(p[m], 1, 5).std()), 3),
                "slope_pred_on_label": round(slope(yte[m], p[m]), 3), "mae": round(mae(yte[m], p[m]), 4)}
            for s in ("SGD", "MWOZ", "ReDial", "CCPE", "JDDC")
            for m in [np.array([r["sub"] == s for r in te])]}
    # F. de-shrinking (VAL): p' = mean + (p - mean) * sd_y / sd_p
    p = np.clip(pv_ridge, 1, 5)
    infl = {}
    for lg in ("en", "zh"):
        k = np.array(lva) == lg
        pk = p[k]
        q = pk.mean() + (pk - pk.mean()) * yva[k].std() / pk.std()
        infl[lg] = {"mae_before": round(mae(yva[k], pk), 4), "mae_inflated_to_label_sd": round(mae(yva[k], q), 4),
                    "qwk_before": round(qwk(yva[k], pk), 4), "qwk_inflated": round(qwk(yva[k], q), 4)}
    res["val_inflation_demo_not_used"] = infl
    # D. truncation
    res["val_truncation_ridge"] = truncation(tr, va)
    # E. losses
    r1, p1 = loss_compare_tfidf(tr, va)
    res["val_loss_compare_tfidf"] = r1
    if EMB.exists():
        r2, p2 = loss_compare_emb(tr, va)
        res["val_loss_compare_frozen_e5"] = r2
    else:
        p2 = {}
        res["val_loss_compare_frozen_e5"] = "NOT RUN (embeddings missing)"
    write_json(RESULTS / "f2_collapse.json", res)

    # ---------- figures (real data) ----------
    names = list(tp)[:2]
    fig, ax = plt.subplots(1, 2, figsize=(10, 4))
    for name, c in zip(names, ("#4c72b0", "#dd8452")):
        cc = res["test_v3_models"][name]["calibration_deciles"]
        ax[0].plot([x["mean_pred"] for x in cc], [x["mean_label"] for x in cc], "o-", c=c, label=name)
        pc = res["test_v3_models"][name]["per_class"]
        ks = sorted(pc, key=int)
        ax[1].plot([int(k) for k in ks], [pc[k]["mean_pred"] for k in ks], "o-", c=c, label=name)
    ax[0].plot([2.5, 4.5], [2.5, 4.5], "k--", lw=0.8)
    ax[0].set(xlabel="mean prediction (TEST decile)", ylabel="mean label", title="Calibration by prediction decile")
    ax[1].plot([1, 5], [1, 5], "k--", lw=0.8, label="ideal")
    ax[1].set(xlabel="true rounded label", ylabel="mean prediction", title="Mean prediction per true class (TEST)")
    for a in ax:
        a.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(FIG / "f2_calibration.png", dpi=120)
    plt.close(fig)
    fig, ax = plt.subplots(1, 5, figsize=(15, 3.2), sharex=True)
    p_r, p_e = tp[names[0]][1], tp[names[1]][1]
    bins = np.arange(1, 5.01, 0.125)
    for j, s in enumerate(("SGD", "MWOZ", "ReDial", "CCPE", "JDDC")):
        m = np.array([r["sub"] == s for r in te])
        ax[j].hist(yte[m], bins=bins, alpha=0.35, color="gray", label="label", density=True)
        ax[j].hist(np.clip(p_r[m], 1, 5), bins=bins, histtype="step", lw=1.6, color="#4c72b0", label="Ridge", density=True)
        ax[j].hist(np.clip(p_e[m], 1, 5), bins=bins, histtype="step", lw=1.6, color="#dd8452", label="e5", density=True)
        ax[j].set_title(f"{s} (TEST n={m.sum()})")
    ax[0].legend(fontsize=7)
    fig.suptitle("Prediction vs label distribution per sub-corpus (V3 models, USS TEST)", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIG / "f2_pred_dist_by_sub.png", dpi=120)
    plt.close(fig)
    fig, ax = plt.subplots(1, 2, figsize=(10, 3.6))
    tcur = res["val_truncation_ridge"]
    for side, c in (("tail", "#4c72b0"), ("head", "#c44e52")):
        ax[0].plot([128, 256, 512], [tcur[f"{side}{n}"]["val_mae"] for n in (128, 256, 512)], "o-", c=c, label=side)
    ax[0].axhline(tcur["full"]["val_mae"], color="k", ls="--", lw=0.8, label="full text")
    ax[0].set(xlabel="tokens kept", ylabel="VAL MAE", title="Truncation side / length (Ridge, VAL)")
    ax[0].legend(fontsize=8)
    allp = {**{"tfidf:" + k: v for k, v in p1.items()}, **{"e5frozen:" + k: v for k, v in p2.items()}}
    ks = list(allp)
    ax[1].barh(range(len(ks)), [res["val_loss_compare_tfidf" if k.startswith("tfidf") else "val_loss_compare_frozen_e5"]
                                [k.split(":")[1]]["pred_sd"] for k in ks], color="#55a868")
    ax[1].axvline(yva.std(), color="k", ls="--", lw=0.8, label="label SD")
    ax[1].set_yticks(range(len(ks)))
    ax[1].set_yticklabels(ks, fontsize=7)
    ax[1].set(xlabel="prediction SD (VAL)", title="Does the loss compress outputs?")
    ax[1].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(FIG / "f2_truncation_and_loss.png", dpi=120)
    print(json.dumps({k: res[k] for k in ("val_truncation_ridge", "val_inflation_demo_not_used")}, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["extract", "analyse"])
    a = ap.parse_args()
    extract() if a.cmd == "extract" else analyse()
