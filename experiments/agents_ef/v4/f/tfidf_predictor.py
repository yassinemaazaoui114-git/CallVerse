"""Agent F v4: the TF-IDF + Ridge satisfaction scorer ("last 256 tokens"), saved as a loadable predictor.

Why this file exists
  In V3 the best model on USS VAL and TEST was TF-IDF+Ridge on the last ~256 tokens of each dialogue
  (TEST MAE 0.392, 0.19M parameters), but bench_uss.py only kept its metrics: there was no saved model.
  This file (1) re-fits it with EXACTLY the V3 recipe (v3/f/bench_uss.py, run_classic "tfidf_ridge" with
  --tail-tokens 256), (2) checks that the V3 numbers are reproduced, (3) saves it with a SHA256 so it can
  be loaded later, and (4) offers the same interface as v3/f/f_predictor.SatisfactionPredictor:

      p = TfidfSatisfactionPredictor.load("<f_v3>/ckpt/tfidf_ridge_tail256")
      p.predict(["Customer: my parcel is late\\nAgent: it was delivered today"])  -> [{"score", "label"}]

Recipe (copied from bench_uss.py, not re-designed)
  - keep the last int(256 * chars_per_token[lang]) characters of the dialogue text; chars/token of the e5
    tokenizer measured on VAL in V3: EN 3.97, ZH 1.39 (any non-Chinese text uses the EN value; see below);
  - word 1-2-gram TF-IDF (min_df 2, sublinear tf, max 200k) + char_wb 3-5-gram TF-IDF (min_df 2, sublinear,
    max 300k), both fitted on TRAIN texts only;
  - Ridge regression; alpha picked on VAL from (0.3, 1, 3, 10, 30) by MAE; final model fitted on TRAIN only.

    python -m v4.f.tfidf_predictor --data <f_v3>/data_uss --out <f_v3>/ckpt/tfidf_ridge_tail256 \
        --v3-result v3/f/results/uss/tfidf_ridge_tail256tok.json

Language of new text: USS has only EN and ZH. A text is treated as ZH when at least 30% of its letters are CJK
characters; everything else (EN, FR, ...) uses the EN cut. French is NOT validated for this model (no French
dialogues in USS); callers must mark French scores as not validated (v4/f/m7/satisfaction_v4.py does).
Security note: the model file is a pickle (joblib). Load only files whose SHA256 matches meta.json
(load() checks it).
"""

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))                     # experiments/agents_ef

CHARS_PER_TOKEN = {"en": 3.97, "zh": 1.39}                   # from bench_uss.py (--tail-tokens), measured on VAL
CJK = re.compile(r"[一-鿿㐀-䶿　-〿＀-￯]")
LETTER = re.compile(r"\w", re.UNICODE)
ALPHAS = (0.3, 1, 3, 10, 30)


def label(score: float) -> str:
    """Same 3 classes as v3/f/f_predictor.py."""
    return "unhappy" if score < 2.5 else "neutral" if score < 3.5 else "happy"


def guess_lang(text: str) -> str:
    """'zh' if >= 30% of the letters are CJK, else 'en' (the only two cut lengths the model was built with)."""
    letters = len(LETTER.findall(text)) or 1
    return "zh" if len(CJK.findall(text)) / letters >= 0.3 else "en"


def tail(text: str, lang: str, tail_tokens: int = 256) -> str:
    """The last ~tail_tokens e5 tokens of the text, as in bench_uss.py: text[-int(N * chars_per_token):]."""
    return text[-int(tail_tokens * CHARS_PER_TOKEN["zh" if lang == "zh" else "en"]):]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class TfidfSatisfactionPredictor:
    """Same interface as v3/f/f_predictor.SatisfactionPredictor: .scores(texts) and .predict(texts)."""

    def __init__(self, word, char, ridge, meta):
        self.word, self.char, self.ridge, self.meta = word, char, ridge, meta

    def features(self, texts, langs=None):
        from scipy.sparse import hstack
        langs = langs or [guess_lang(t) for t in texts]
        cut = [tail(t, lg, self.meta["tail_tokens"]) for t, lg in zip(texts, langs)]
        return hstack([self.word.transform(cut), self.char.transform(cut)]).tocsr()

    def raw_scores(self, texts, langs=None):
        """Unclipped Ridge output (the V3 benchmark clipped only inside the metrics)."""
        return np.asarray(self.ridge.predict(self.features(texts, langs)), float)

    def scores(self, texts, langs=None):
        return np.clip(self.raw_scores(texts, langs), 1, 5)

    def predict(self, texts, langs=None):
        return [{"score": round(float(s), 3), "label": label(float(s))} for s in self.scores(texts, langs)]

    @classmethod
    def load(cls, ckpt_dir, verify=True):
        import joblib
        ckpt_dir = Path(ckpt_dir)
        meta = json.loads((ckpt_dir / "meta.json").read_text())
        path = ckpt_dir / meta["model_file"]
        if verify and sha256(path) != meta["sha256"]:
            raise ValueError(f"SHA256 mismatch for {path}: refusing to unpickle")
        obj = joblib.load(path)
        return cls(obj["word"], obj["char"], obj["ridge"], meta)


def fit(train_texts, y_train, val_texts, y_val, alphas=ALPHAS, word_kw=None, char_kw=None):
    """Fit vectorizers on TRAIN, choose alpha on VAL MAE, refit Ridge on TRAIN. Returns (word, char, ridge, info)."""
    from scipy.sparse import hstack
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import Ridge
    word = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, max_features=200000,
                           **(word_kw or {})).fit(train_texts)
    char = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True, max_features=300000,
                           **(char_kw or {})).fit(train_texts)
    f = lambda X: hstack([word.transform(X), char.transform(X)]).tocsr()
    Ftr, Fva = f(train_texts), f(val_texts)
    mae = lambda p: float(np.abs(np.clip(p, 1, 5) - y_val).mean())
    grid = [(mae(Ridge(alpha=al).fit(Ftr, y_train).predict(Fva)), al) for al in alphas]
    best = min(grid)
    ridge = Ridge(alpha=best[1]).fit(Ftr, y_train)
    return word, char, ridge, {"alpha": best[1], "val_mae_grid": {str(a): round(m, 5) for m, a in grid},
                               "n_params": int(ridge.coef_.size + 1), "n_word_features": len(word.vocabulary_),
                               "n_char_features": len(char.vocabulary_)}


def load_rows(folder, split):
    return [json.loads(line) for line in open(Path(folder) / f"{split}.jsonl", encoding="utf-8")]


def main(argv=None):
    import joblib
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--v3-result", required=True, help="v3/f/results/uss/tfidf_ridge_tail256tok.json")
    ap.add_argument("--report", default=str(HERE / "results" / "tfidf_ridge_tail256_reproduction.json"))
    a = ap.parse_args(argv)
    tr, va, te = (load_rows(a.data, s) for s in ("train", "val", "test"))
    cut = lambda rows: [tail(r["text"], r["lang"]) for r in rows]      # the dataset's own language field
    ytr, yva, yte = (np.array([r["rating"] for r in rows], float) for rows in (tr, va, te))
    t0 = time.perf_counter()
    word, char, ridge, info = fit(cut(tr), ytr, cut(va), yva)
    fit_s = time.perf_counter() - t0
    pred = TfidfSatisfactionPredictor(word, char, ridge, {"tail_tokens": 256})
    pv = pred.scores([r["text"] for r in va], [r["lang"] for r in va])
    pt = pred.scores([r["text"] for r in te], [r["lang"] for r in te])
    v3 = json.loads(Path(a.v3_result).read_text())
    v3run = v3["runs"][0]
    assert v3["test_ids"] == [r["id"] for r in te], "TEST order differs from the V3 run"
    v3pred = np.array(v3run["test_pred"], float)
    raw_te = pred.raw_scores([r["text"] for r in te], [r["lang"] for r in te])
    rep = {"what": "re-fit of V3 tfidf_ridge_tail256tok with the V3 recipe; TEST scored once (reproduction only)",
           "alpha": info["alpha"], "v3_alpha": v3run["alpha"], "val_mae_grid": info["val_mae_grid"],
           "val_mae": round(float(np.abs(pv - yva).mean()), 5), "v3_val_mae": round(v3run["val"]["all"]["mae"], 5),
           "test_mae": round(float(np.abs(pt - yte).mean()), 5), "v3_test_mae": round(v3run["test"]["all"]["mae"], 5),
           "n_params": info["n_params"], "v3_n_params": v3run["n_params"],
           "max_abs_diff_vs_v3_test_pred": round(float(np.abs(np.round(raw_te, 4) - v3pred).max()), 6),
           "n_test_pred_equal_4dp": int((np.round(raw_te, 4) == v3pred).sum()), "n_test": len(te),
           "fit_s": round(fit_s, 1)}
    from scipy.stats import spearmanr
    rep["test_spearman"] = round(float(spearmanr(yte, pt).statistic), 4)
    for lg in ("en", "zh"):
        m = np.array([r["lang"] == lg for r in te])
        rep[f"test_mae_{lg}"] = round(float(np.abs(pt[m] - yte[m]).mean()), 4)
    rep["reproduced_within_0.002"] = abs(rep["val_mae"] - rep["v3_val_mae"]) <= 0.002 and \
        abs(rep["test_mae"] - rep["v3_test_mae"]) <= 0.002
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    mf = out / "model.joblib"
    joblib.dump({"word": word, "char": char, "ridge": ridge}, mf, compress=3)
    import sklearn
    meta = {"model": "tfidf_ridge_tail256", "model_file": mf.name, "sha256": sha256(mf),
            "size_bytes": mf.stat().st_size, "tail_tokens": 256, "chars_per_token": CHARS_PER_TOKEN,
            "lang_rule": "zh if >=30% CJK letters else en cut (FR/other: EN cut, NOT validated)",
            "alpha": info["alpha"], "n_params": info["n_params"], "n_word_features": info["n_word_features"],
            "n_char_features": info["n_char_features"], "trained_on": "USS train.jsonl (4,740 dialogues, EN+ZH)",
            "label_type": "human_annotation (third-party annotators, mean of 3-7)",
            "domain": "task_oriented_dialogue + JDDC e-commerce service (zh)",
            "languages_validated": ["en", "zh"], "val_mae": rep["val_mae"], "test_mae": rep["test_mae"],
            "test_spearman": rep["test_spearman"], "sklearn": sklearn.__version__,
            "source_recipe": "v3/f/bench_uss.py run_classic('tfidf_ridge') --tail-tokens 256",
            "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    rep["checkpoint"] = str(out)
    rep["sha256"] = meta["sha256"]
    rep["size_bytes"] = meta["size_bytes"]
    Path(a.report).write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
