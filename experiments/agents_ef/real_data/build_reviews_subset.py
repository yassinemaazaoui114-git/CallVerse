"""EN/FR subset with GENUINE 1-5 star ratings (Amazon Multilingual Reviews, MTEB mirror) for Agent F.

    python -m real_data.build_reviews_subset --raw <folder with {en,fr}_{validation,test}.jsonl> \
        --per-lang 1000 --out <folder OUTSIDE git>

Source: huggingface.co/datasets/mteb/amazon_reviews_multi (Amazon Multilingual Reviews Corpus, Keung et al. 2020;
non-commercial research licence). Label 0-4 = stars 1-5 given by the customer = a genuine satisfaction rating
(product satisfaction, not support-conversation satisfaction). The official splits are kept apart:
our TRAIN/VAL come from the official validation split, our TEST from the official test split.
The corpus is balanced by its authors (equal count per star): imbalance is NOT realistic here.
Output = the same jsonl format as prepare_subset.py, plus profile.json (aggregates only).
"""

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from real_data.prepare_subset import drop_near_duplicates, leakage_report, norm_text  # noqa: E402


def load(path, lang):
    rows = []
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        rows.append({"id": r["id"], "conv": r["id"], "text": r["text"].strip(), "lang": lang, "intent": "review",
                     "scenario": "", "rating": float(r["label"]) + 1.0, "ts": None, "handle_min": None})
    return rows


def take(rows, n_per_star, rng, seen):
    """n_per_star rows per star, skipping texts already used (normalised dedup across all splits)."""
    out = []
    for star in range(1, 6):
        pool = [r for r in rows if r["rating"] == star]
        for i in rng.permutation(len(pool)):
            r = pool[i]
            h = hashlib.sha1(norm_text(r["text"]).encode()).hexdigest()
            if h in seen:
                continue
            seen.add(h)
            r["hash"] = h
            out.append(r)
            if sum(x["rating"] == star for x in out) >= n_per_star:
                break
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--per-lang", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    rng = np.random.default_rng(a.seed)
    n = a.per_lang // 5                                       # rows per star per language
    parts, seen = {"train": [], "val": [], "test": []}, set()
    for lang in ("en", "fr"):
        test = take(load(Path(a.raw) / f"{lang}_test.jsonl", lang), round(n * 0.2), rng, seen)
        dev = take(load(Path(a.raw) / f"{lang}_validation.jsonl", lang), round(n * 0.8), rng, seen)
        k = int(round(len(dev) * 0.75))
        dev = [dev[i] for i in rng.permutation(len(dev))]
        parts["train"] += dev[:k]
        parts["val"] += dev[k:]
        parts["test"] += test
    near = drop_near_duplicates(parts)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for s, rs in parts.items():
        with open(out / f"{s}.jsonl", "w", encoding="utf-8") as f:
            for r in rs:
                f.write(json.dumps({k: v for k, v in r.items() if k != "hash"}, ensure_ascii=False) + "\n")
    prof = {"source": "mteb/amazon_reviews_multi (en, fr); TRAIN/VAL from official validation, TEST from official test",
            "splits": {s: {"n": len(v), "by_lang": dict(Counter(r["lang"] for r in v)),
                           "by_star": dict(Counter(int(r["rating"]) for r in v))} for s, v in parts.items()},
            "leakage": {**leakage_report(parts), "near_duplicates_removed": near},
            "words_mean": float(np.mean([len(r["text"].split()) for v in parts.values() for r in v]))}
    (out / "profile.json").write_text(json.dumps(prof, indent=2))
    print(json.dumps(prof, indent=1))


if __name__ == "__main__":
    main()
