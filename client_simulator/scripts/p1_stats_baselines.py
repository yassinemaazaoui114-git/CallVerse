"""Phase 1 (D6): real score statistics, charts, and CPU baselines (majority, TF-IDF + LR)."""
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from common import FIG, PROC, RAW, REAL, RESULTS, SCORES, read_jsonl, save_json, score_metrics, plot_style

RS = PROC / "real_scores"
plt = plot_style()
DELAY_ORDER = ["0-5 min", "5-30 min", "30 min-2 h", "2-8 h", "8 h+", "unknown"]


def load(name, part):
    return pd.DataFrame(read_jsonl(RS / f"{name}_{part}.jsonl"))


def dist(s):
    vc = s.value_counts()
    return {k: round(float(vc.get(k, 0)) / len(s), 4) for k in SCORES}


def group_stats(df, col, order=None):
    g = df.groupby(col)["score"].agg(["count", "mean"])
    g["share_1"] = df.groupby(col)["score"].apply(lambda x: (x == 1).mean())
    g["share_5"] = df.groupby(col)["score"].apply(lambda x: (x == 5).mean())
    if order:
        g = g.reindex([o for o in order if o in g.index])
    return g.round(4)


def bar(ax, labels, values, title, ylabel, n=None, ylim=(1, 5)):
    ax.bar(range(len(labels)), values, color=REAL, width=0.6)
    ax.set_xticks(range(len(labels)), labels, rotation=30, ha="right")
    ax.set_title(title, loc="left")
    ax.set_ylabel(ylabel)
    if ylim:
        ax.set_ylim(*ylim)
    for i, v in enumerate(values):
        lab = f"{v:.2f}" + (f"\nn={n[i]}" if n is not None else "")
        ax.text(i, v + (0.05 if ylim else 0.005), lab, ha="center", va="bottom", fontsize=8, color="#52514e")


def charts_and_stats():
    stats = {}
    csat = pd.DataFrame(read_jsonl(RS / "csat_all.jsonl"))
    conv = pd.concat([load("conv", p) for p in ("train", "dev", "test")])
    olist = pd.read_csv(RS / "olist_scores_delay.csv")
    trip = pd.read_csv(RAW / "trip-advisor-hotel-reviews" / "tripadvisor_hotel_reviews.csv").rename(columns={"Rating": "score"})

    # 1. score distributions (small multiples)
    sets = {"Flipkart CSAT (customer)": csat.score, "USS travel dialogues (annotators)": conv.score,
            "Olist reviews (customer, PT)": olist.review_score, "TripAdvisor hotels (customer)": trip.score}
    fig, axes = plt.subplots(1, 4, figsize=(14, 3.2), sharey=True)
    for ax, (name, s) in zip(axes, sets.items()):
        d = dist(s)
        ax.bar(SCORES, [d[k] for k in SCORES], color=REAL, width=0.6)
        ax.set_title(f"{name}\nn={len(s):,}", loc="left", fontsize=9)
        ax.set_xticks(SCORES)
        for k in SCORES:
            ax.text(k, d[k] + 0.01, f"{d[k]:.0%}", ha="center", fontsize=8, color="#52514e")
    axes[0].set_ylabel("share of rows")
    fig.tight_layout()
    fig.savefig(FIG / "real_score_distributions.png")
    stats["distributions"] = {k: dist(v) for k, v in sets.items()}
    stats["means"] = {k: round(float(v.mean()), 4) for k, v in sets.items()}

    # 2. CSAT by reason and by response-time bucket
    by_reason = group_stats(csat, "reason").sort_values("mean")
    by_delay = group_stats(csat, "delay_bucket", DELAY_ORDER)
    by_cat = group_stats(csat, "category").sort_values("mean")
    by_channel = group_stats(csat, "channel")
    by_tenure = group_stats(csat, "tenure_bucket")
    csat["has_remark"] = csat.remark.notna()
    by_remark = group_stats(csat, "has_remark")
    fig, axes = plt.subplots(1, 2, figsize=(12, 3.8))
    bar(axes[0], by_reason.index.tolist(), by_reason["mean"].tolist(), "Flipkart CSAT: mean score by contact reason",
        "mean CSAT (1-5)", by_reason["count"].astype(int).tolist())
    bar(axes[1], by_delay.index.tolist(), by_delay["mean"].tolist(), "Flipkart CSAT: mean score by time to first response",
        "mean CSAT (1-5)", by_delay["count"].astype(int).tolist())
    fig.tight_layout()
    fig.savefig(FIG / "csat_by_reason_and_delay.png")

    # 3. CONV by conversation length (user turns)
    conv["len_bucket"] = pd.cut(conv.n_user_turns, [0, 6, 9, 12, 15, 100], labels=["1-6", "7-9", "10-12", "13-15", "16+"])
    by_len = conv.groupby("len_bucket", observed=True)["rating_mean"].agg(["count", "mean"]).round(4)
    by_len_score = conv.groupby("len_bucket", observed=True)["score"].agg(["mean"]).round(4)
    conv_by_src = group_stats(conv, "source")
    # dialogues where at least one user turn was rated <=2 by majority of annotators
    conv["any_low_turn"] = conv.turns.apply(lambda ts: any(np.mean(t.get("turn_sat", [3])) <= 2 for t in ts if t["role"] == "user"))
    by_lowturn = group_stats(conv, "any_low_turn")
    fig, axes = plt.subplots(1, 2, figsize=(12, 3.8))
    bar(axes[0], [str(x) for x in by_len.index], by_len["mean"].tolist(),
        "USS travel dialogues: mean annotator rating by length", "mean rating (1-5)", by_len["count"].astype(int).tolist(), ylim=(2, 4))
    # Olist: delay drives score
    bins = [-1e9, 0, 3, 7, 14, 1e9]
    labs = ["on time/early", "1-3 d late", "4-7 d late", "8-14 d late", "15+ d late"]
    olist["late_bucket"] = pd.cut(olist.days_late, bins, labels=labs).astype(str)
    olist.loc[olist.days_late.isna(), "late_bucket"] = "not delivered"
    ol = olist.rename(columns={"review_score": "score"})
    by_late = group_stats(ol, "late_bucket", labs + ["not delivered"])
    bar(axes[1], by_late.index.tolist(), by_late["mean"].tolist(), "Olist (customer reviews): mean score by delivery lateness",
        "mean review score (1-5)", by_late["count"].astype(int).tolist())
    fig.tight_layout()
    fig.savefig(FIG / "conv_length_and_olist_lateness.png")

    # remark length vs score (CSAT text rows)
    txt = csat[csat.has_remark].copy()
    txt["words"] = txt.remark.str.split().str.len()
    words_by_score = txt.groupby("score")["words"].median().to_dict()

    stats.update({
        "csat_by_reason": by_reason.to_dict("index"), "csat_by_delay": by_delay.to_dict("index"),
        "csat_by_category": by_cat.to_dict("index"), "csat_by_channel": by_channel.to_dict("index"),
        "csat_by_tenure": by_tenure.to_dict("index"), "csat_by_has_remark": {str(k): v for k, v in by_remark.to_dict("index").items()},
        "csat_remark_median_words_by_score": {int(k): float(v) for k, v in words_by_score.items()},
        "conv_by_length_rating_mean": {str(k): v for k, v in by_len.to_dict("index").items()},
        "conv_by_length_score_mean": {str(k): v for k, v in by_len_score.to_dict("index").items()},
        "conv_by_source": conv_by_src.to_dict("index"),
        "conv_by_any_low_turn": {str(k): v for k, v in by_lowturn.to_dict("index").items()},
        "olist_by_lateness": by_late.to_dict("index"),
        "share_1_and_5": {k: {"share_1": dist(v)[1], "share_5": dist(v)[5]} for k, v in sets.items()},
    })
    save_json(stats, RESULTS / "p1_real_stats.json")
    return stats


def conv_text(df):
    return df.turns.apply(lambda ts: " ".join(("U: " if t["role"] == "user" else "A: ") + t["text"] for t in ts))


def csat_text(df):
    return ("reason_" + df.reason + " delay_" + df.delay_bucket.str.replace(r"[^a-z0-9]", "", regex=True)
            + " chan_" + df.channel + " " + df.remark.fillna(""))


def baselines():
    res = {}
    for name, fx in (("conv", conv_text), ("csat_text", csat_text), ("csat_allrows", csat_text)):
        tr, dv, te = (load(name, p) for p in ("train", "dev", "test"))
        maj = int(tr.score.mode()[0])
        vec = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)
        Xtr = vec.fit_transform(fx(tr))
        best = None
        for C in (0.1, 0.3, 1, 3, 10):  # tune C on dev only
            for cw in (None, "balanced"):
                m = LogisticRegression(C=C, max_iter=2000, class_weight=cw).fit(Xtr, tr.score)
                dm = score_metrics(dv.score, m.predict(vec.transform(fx(dv))))
                if best is None or dm["qwk"] > best[0]["qwk"]:
                    best = (dm, C, cw, m)
        dm, C, cw, m = best
        pred = m.predict(vec.transform(fx(te)))
        res[name] = {
            "majority_class": maj,
            "majority_test": score_metrics(te.score, [maj] * len(te)),
            "tfidf_lr_test": score_metrics(te.score, pred),
            "tfidf_lr_dev": dm, "tfidf_lr_params": {"C": C, "class_weight": cw, "selected_on": "dev QWK"},
        }
        te[["id"]].assign(pred=pred).to_csv(RESULTS / f"p1_tfidf_pred_{name}_test.csv", index=False)
    save_json(res, RESULTS / "p1_baselines.json")
    return res


if __name__ == "__main__":
    s = charts_and_stats()
    b = baselines()
    for k, v in b.items():
        print(k, "maj", {x: v["majority_test"][x] for x in ("mae", "exact_acc", "qwk", "macro_f1")},
              "lr", {x: v["tfidf_lr_test"][x] for x in ("mae", "spearman", "exact_acc", "qwk", "macro_f1")})
