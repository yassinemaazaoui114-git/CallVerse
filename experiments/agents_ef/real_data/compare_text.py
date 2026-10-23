"""Synthetic (simulated Agent F data) vs authentic text: how different are they? Aggregates only, no text output.

    python -m real_data.compare_text --sim results/agent_f_data --real <subset folder> --out results/real_f_olist
Measures: length, label distribution / imbalance, share of distinct texts, vocabulary overlap, and how well each
tokenizer fits (sub-word pieces per word: TinyBERT is English-only, multilingual MiniLM covers pt/fr/en).
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import numpy as np


def rows(folder, split):
    return [json.loads(line) for line in open(Path(folder) / f"{split}.jsonl", encoding="utf-8")]


def words(t):
    return re.findall(r"\w+", t.lower())


def stats(texts, labels):
    w = [words(t) for t in texts]
    lens = np.array([len(x) for x in w])
    c = Counter(round(x) for x in labels)
    return {"n": len(texts), "words_mean": float(lens.mean()), "words_p95": float(np.percentile(lens, 95)),
            "distinct_text_share": len(set(texts)) / len(texts),
            "type_token_ratio": len({x for ws in w for x in ws}) / max(1, sum(lens)),
            "label_share_1to5": {k: round(c[k] / len(labels), 4) for k in range(1, 6)},
            "imbalance_max_over_min_class": round(max(c.values()) / max(1, min(c.get(k, 0) for k in range(1, 6))), 2)}


def pieces_per_word(tok, texts):
    n_w = n_p = n_unk = 0
    for t in texts[:500]:
        for w in words(t):
            p = tok.tokenize(w)
            n_w, n_p = n_w + 1, n_p + len(p)
            n_unk += sum(x == tok.unk_token for x in p)
    return {"pieces_per_word": round(n_p / max(1, n_w), 3), "unk_share": round(n_unk / max(1, n_p), 4)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", default="results/agent_f_data")
    ap.add_argument("--real", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    sim = rows(a.sim, "train") + rows(a.sim, "test")
    real = rows(a.real, "train") + rows(a.real, "val") + rows(a.real, "test")
    st, rt = [r["text"] for r in sim], [r["text"] for r in real]
    res = {"simulated": stats(st, [r["csat"] for r in sim]), "authentic": stats(rt, [r["rating"] for r in real])}
    sv, rv = Counter(w for t in st for w in words(t)), Counter(w for t in rt for w in words(t))
    res["authentic_tokens_seen_in_simulated_vocab"] = round(sum(c for w, c in rv.items() if w in sv) / sum(rv.values()), 4)
    try:
        from transformers import AutoTokenizer
        for name, hf in (("tinybert", "huawei-noah/TinyBERT_General_4L_312D"),
                         ("multilingual_minilm", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")):
            tok = AutoTokenizer.from_pretrained(hf)
            res[f"tokenizer_{name}"] = {"simulated": pieces_per_word(tok, st), "authentic": pieces_per_word(tok, rt)}
    except Exception as e:                      # tokenizers optional (offline machine)
        res["tokenizer_error"] = str(e)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "text_comparison.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
