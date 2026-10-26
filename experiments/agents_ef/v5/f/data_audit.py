"""Worker F v5 — F1 data audit of the USS splits used by every Agent F model.

    $PY -m v5.f.data_audit            -> v5/f/results/f1_data_audit.json (+ figures/f1_label_dist.png)

Why this file exists
  The V3 split removed exact duplicates INSIDE each sub-corpus before splitting, but nobody checked
  (a) normalised duplicates (case / spaces / punctuation / digits) ACROSS splits, (b) near-duplicates across splits,
  (c) label / language counts per split, (d) personal data in the text. A model that "remembers" a TRAIN dialogue
  that re-appears in TEST would get an optimistic TEST score; this script measures how often that can happen.
What it checks (all on the jsonl files, TEST texts are read only for overlap and PII counts, never for modelling):
  1. exact text hash and normalised text hash overlaps between TRAIN, VAL, TEST;
  2. near-duplicates: char 3-5-gram TF-IDF cosine of every VAL/TEST dialogue to its nearest TRAIN dialogue
     (vectoriser fitted on TRAIN only); share above 0.8 / 0.9 / 0.95, per sub-corpus, and whether the labels of
     near-duplicate pairs agree (if they do not, a near-copy does not leak the label);
  3. label distributions (mean, SD, rounded class counts) and language counts per split and sub-corpus;
  4. PII regex scan (e-mail, phone-like digit runs, URLs, card-like numbers, JDDC placeholders) with counts only;
     no matched text is written to the output.
"""

import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from v5.f.common import DATA, FIG, RESULTS, load, to_int, write_json  # noqa: E402

PII = {"email": r"[\w.+-]+@[\w-]+\.[\w.]+",
       "url": r"https?://\S+|www\.\S+",
       "phone_like_7plus_digits": r"(?<!\d)(?:\+?\d[\d \-]{6,}\d)(?!\d)",
       "card_like_13_19_digits": r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)",
       "jddc_placeholder": r"\[(?:数字x|金额x|日期x|时间x|姓名x|地址x|电话x|站点x|组织机构x|链接x|邮箱x|ORDERID_\d+|USERID_\d+)\]"}


def norm(t: str) -> str:
    """Normalised text: NFKC, lower case, role tags removed, digits -> 0, punctuation and spaces removed."""
    t = unicodedata.normalize("NFKC", t).lower()
    t = re.sub(r"^(customer|agent|客户|客服):", "", t, flags=re.M)
    t = re.sub(r"\d", "0", t)
    return re.sub(r"[\W_]+", "", t)


def h(t):
    return hashlib.sha1(t.encode("utf-8")).hexdigest()


def label_stats(rows):
    y = np.array([r["rating"] for r in rows])
    return {"n": len(rows), "mean": round(float(y.mean()), 3), "sd": round(float(y.std()), 3),
            "rounded_counts": {int(k): int(v) for k, v in sorted(Counter(to_int(y)).items())},
            "share_le_2.5": round(float((y <= 2.5).mean()), 4), "share_ge_4": round(float((y >= 4).mean()), 4),
            "n_annotators": {int(k): int(v) for k, v in sorted(Counter(len(r["ratings"]) for r in rows).items())}}


def main():
    sp = {s: load(s) for s in ("train", "val", "test")}
    out = {"data_folder": str(DATA),
           "sha256": {s: hashlib.sha256((DATA / f"{s}.jsonl").read_bytes()).hexdigest() for s in sp}}
    # 1. exact / normalised duplicates
    dup = {}
    for kind, fn in (("exact", lambda r: h(r["text"])), ("normalised", lambda r: h(norm(r["text"])))):
        hs = {s: Counter(fn(r) for r in rows) for s, rows in sp.items()}
        d = {"within": {s: int(sum(c - 1 for c in hs[s].values() if c > 1)) for s in sp}}
        for a, b in (("train", "val"), ("train", "test"), ("val", "test")):
            common = set(hs[a]) & set(hs[b])
            d[f"{a}&{b}_texts"] = len(common)
            d[f"{a}&{b}_rows_in_{b}"] = int(sum(hs[b][x] for x in common))
        dup[kind] = d
    # which sub-corpora are affected by normalised cross-split overlaps, and do labels agree?
    tr_norm = {}
    for r in sp["train"]:
        tr_norm.setdefault(h(norm(r["text"])), []).append(r)
    pairs = []
    for s in ("val", "test"):
        for r in sp[s]:
            for t in tr_norm.get(h(norm(r["text"])), []):
                pairs.append({"split": s, "sub": r["sub"], "abs_label_diff": abs(r["rating"] - t["rating"]),
                              "n_chars": r["n_chars"]})
    dup["normalised_cross_pairs_by_sub"] = dict(Counter(f'{p["split"]}:{p["sub"]}' for p in pairs))
    dup["normalised_cross_pairs_label_abs_diff_mean"] = round(float(np.mean([p["abs_label_diff"] for p in pairs])), 3) \
        if pairs else None
    dup["normalised_cross_pairs_median_chars"] = float(np.median([p["n_chars"] for p in pairs])) if pairs else None
    out["duplicates"] = dup
    # 2. near-duplicates (nearest TRAIN neighbour)
    from sklearn.feature_extraction.text import TfidfVectorizer
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True,
                          max_features=300000).fit([r["text"] for r in sp["train"]])
    Xtr = vec.transform([r["text"] for r in sp["train"]])
    ytr = np.array([r["rating"] for r in sp["train"]])
    near = {}
    for s in ("val", "test"):
        X = vec.transform([r["text"] for r in sp[s]])
        S = (X @ Xtr.T).toarray()
        nn_i, nn_s = S.argmax(1), S.max(1)
        y = np.array([r["rating"] for r in sp[s]])
        subs = np.array([r["sub"] for r in sp[s]])
        res = {"cos_quantiles": {q: round(float(np.quantile(nn_s, q)), 3) for q in (0.5, 0.9, 0.99)}}
        for th in (0.8, 0.9, 0.95):
            m = nn_s >= th
            res[f"share_ge_{th}"] = round(float(m.mean()), 4)
            res[f"n_ge_{th}_by_sub"] = {k: int(v) for k, v in Counter(subs[m]).items()}
            # if a near-copy leaked the label, |y - y_nn| would be ~0; compare with random TRAIN pairs
            res[f"label_abs_diff_to_nn_ge_{th}"] = round(float(np.abs(y[m] - ytr[nn_i[m]]).mean()), 3) if m.any() else None
        res["label_abs_diff_random_train_pair"] = round(float(np.abs(y - np.random.default_rng(0).choice(ytr, len(y))).mean()), 3)
        res["label_abs_diff_to_nn_all"] = round(float(np.abs(y - ytr[nn_i]).mean()), 3)
        near[s] = res
    out["near_duplicates_char_tfidf_nn_train"] = near
    # 3. labels and languages
    out["labels"] = {s: {"all": label_stats(rows), **{k: label_stats([r for r in rows if r["sub"] == k])
                                                      for k in sorted({r["sub"] for r in rows})},
                         "lang": dict(Counter(r["lang"] for r in rows))} for s, rows in sp.items()}
    out["languages_with_labels"] = sorted({r["lang"] for rows in sp.values() for r in rows})
    out["french_support_dialogues_with_labels"] = 0
    # 4. PII scan: counts of matching dialogues per pattern and sub-corpus (no text written)
    pii = {}
    for k, pat in PII.items():
        rx = re.compile(pat)
        pii[k] = {sub: int(sum(1 for rows in sp.values() for r in rows if r["sub"] == sub and rx.search(r["text"])))
                  for sub in ("SGD", "MWOZ", "ReDial", "CCPE", "JDDC")}
    out["pii_regex_dialogue_counts"] = pii
    write_json(RESULTS / "f1_data_audit.json", out)
    # figure: label distribution per split and language (real data)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 2, figsize=(10, 3.4), sharey=False)
    bins = np.arange(0.875, 5.2, 0.25)
    for j, lg in enumerate(("en", "zh")):
        for s, c in zip(sp, ("#4c72b0", "#dd8452", "#55a868")):
            y = [r["rating"] for r in sp[s] if r["lang"] == lg]
            ax[j].hist(y, bins=bins, density=True, histtype="step", lw=1.8, color=c, label=f"{s} (n={len(y)})")
        ax[j].set_title(f"USS {lg.upper()} — mean annotator OVERALL rating")
        ax[j].set_xlabel("label (1-5)")
        ax[j].legend(fontsize=8)
    ax[0].set_ylabel("density")
    fig.tight_layout()
    fig.savefig(FIG / "f1_label_dist.png", dpi=120)
    print(json.dumps({k: out[k] for k in ("duplicates", "near_duplicates_char_tfidf_nn_train", "pii_regex_dialogue_counts")}, indent=1))


if __name__ == "__main__":
    main()
