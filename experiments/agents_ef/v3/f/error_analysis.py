"""Agent F v3 error analysis on the USS TEST split (predictions already stored in the result JSONs).

    python v3/f/error_analysis.py --data <f_v3/data_uss> --models <tag> [<tag> ...] --out v3/f/results/error_analysis.json
For each model (best seed by VAL): error per true class, per sub-dataset/language, long vs short dialogues,
"polite but unsatisfied" and "negative words but satisfied" cases (found with simple cue words versus the LABEL),
and annotator disagreement versus model error. Snippets: at most 5, < 160 chars, last customer turn only,
from the PUBLIC USS data.
"""
import argparse
import json
import re
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

H = Path(__file__).resolve().parent
POLITE = r"thank|thanks|appreciate|great|perfect|谢谢|感谢|好的|辛苦"
NEG = r"\bnot\b|\bno\b|wrong|don't|doesn't|didn't|can't|problem|terrible|bad|不|没|差|投诉|怎么回事|太慢"


def last_user(text):
    us = [l.split(":", 1)[1].strip() for l in text.split("\n") if l.startswith(("Customer:", "客户:"))]
    return us[-1] if us else ""


def user_text(text):
    return " ".join(l.split(":", 1)[1] for l in text.split("\n") if l.startswith(("Customer:", "客户:")))


def summary(err, mask):
    mask = np.asarray(mask)
    return {"n": int(mask.sum()), "mae": float(np.abs(err[mask]).mean()) if mask.any() else None,
            "mean_signed_error": float(err[mask].mean()) if mask.any() else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--snippet-model", default=None)
    a = ap.parse_args()
    te = {json.loads(l)["id"]: json.loads(l) for l in open(Path(a.data) / "test.jsonl", encoding="utf-8")}
    out = {"definitions": {
        "true_class": "mean annotator OVERALL rating rounded half up",
        "long": "n_chars above the median of its language (TEST)",
        "polite_but_unsatisfied": f"last customer turn matches /{POLITE}/ AND true mean rating < 3",
        "negative_but_satisfied": f">= 2 negative cue words /{NEG}/ in customer turns AND true mean rating >= 4",
        "disagreement": "std of the annotators' OVERALL ratings for that dialogue"}, "models": {}}
    for tag in a.models:
        d = json.loads((H / "results" / "uss" / f"{tag}.json").read_text())
        run = min(d["runs"], key=lambda r: r["val"]["all"]["mae"])
        rows = [te[i] for i in d["test_ids"]]
        y = np.array([r["rating"] for r in rows])
        p = np.clip(np.array(run["test_pred"]), 1, 5)
        err = p - y
        yi = np.clip(np.floor(y + 0.5), 1, 5).astype(int)
        lang = np.array([r["lang"] for r in rows])
        med = {lg: np.median([r["n_chars"] for r, l in zip(rows, lang) if l == lg]) for lg in set(lang)}
        long_ = np.array([r["n_chars"] > med[r["lang"]] for r in rows])
        polite = np.array([bool(re.search(POLITE, last_user(r["text"]).lower())) for r in rows])
        nneg = np.array([len(re.findall(NEG, user_text(r["text"]).lower())) for r in rows])
        sd = np.array([np.std(r["ratings"]) for r in rows])
        res = {"seed": run.get("seed", 0), "n": len(rows),
               "by_true_class": {int(k): summary(err, yi == k) for k in range(1, 6) if (yi == k).any()},
               "by_lang": {lg: summary(err, lang == lg) for lg in sorted(set(lang))},
               "by_sub": {s: summary(err, np.array([r["sub"] == s for r in rows]))
                          for s in sorted({r["sub"] for r in rows})},
               "long_vs_short": {f"{lg}_{k}": summary(err, (lang == lg) & (long_ if k == "long" else ~long_))
                                 for lg in sorted(set(lang)) for k in ("long", "short")},
               "polite_but_unsatisfied": summary(err, polite & (y < 3)),
               "polite_and_not_unsatisfied": summary(err, polite & (y >= 3)),
               "negative_but_satisfied": summary(err, (nneg >= 2) & (y >= 4)),
               "other_satisfied": summary(err, (nneg < 2) & (y >= 4)),
               "disagreement_bins": {"sd=0": summary(err, sd == 0), "0<sd<=0.5": summary(err, (sd > 0) & (sd <= 0.5)),
                                     "sd>0.5": summary(err, sd > 0.5)},
               "spearman_abs_error_vs_annotator_sd": {
                   lg: float(spearmanr(np.abs(err[lang == lg]), sd[lang == lg]).correlation) for lg in sorted(set(lang))}}
        # how close is the model to "one human": annotators' leave-one-out MAE on the same TEST dialogues
        loo = [abs(r["ratings"][i] - np.mean(r["ratings"][:i] + r["ratings"][i + 1:])) for r in rows
               for i in range(len(r["ratings"]))]
        res["human_loo_mae_same_test"] = float(np.mean(loo))
        if tag == (a.snippet_model or a.models[0]):
            worst = np.argsort(-np.abs(err))
            snips = []
            for lg, k in (("en", 3), ("zh", 2)):
                for j in [j for j in worst if lang[j] == lg][:k]:
                    snips.append({"id": rows[j]["id"], "true": round(float(y[j]), 2), "pred": round(float(p[j]), 2),
                                  "annotators": rows[j]["ratings"], "last_customer_turn": last_user(rows[j]["text"])[:160]})
            res["worst_error_snippets_public_USS"] = snips
        out["models"][tag] = res
    Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps({t: {k: v for k, v in m.items() if k in ("by_true_class", "polite_but_unsatisfied",
                                                              "negative_but_satisfied", "disagreement_bins")}
                      for t, m in out["models"].items()}, indent=1)[:3000])


if __name__ == "__main__":
    main()
