"""Worker F v5 — F3: TF-IDF + Ridge satisfaction scorer, configurable, with a VAL-only grid.

    $PY -m v5.f.ridge_v5 grid            # VAL grid -> v5/f/results/f3_ridge_grid.json (TEST never read)
    $PY -m v5.f.ridge_v5 save --config <name>   # refit the selected config on TRAIN, save + SHA256 (no TEST)

Why this file exists
  V3's TF-IDF+Ridge (last ~256 tokens, word 1-2 + char_wb 3-5, alpha on VAL) is the best Agent F model so far
  (TEST MAE 0.392). Its feature settings were copied from v2 and never searched. V5 asks: is there a better
  setting of the SAME cheap model on the SAME splits, chosen on VAL only? The grid is small and one-factor-at-a-time
  from the V3 recipe (12 configs), then one greedy combination of the factors that helped (rule fixed in advance:
  a factor "helps" if it lowers VAL MAE by >= 0.001; factors are added in order of gain, each kept only if the
  combined VAL MAE improves by >= 0.001). Factors:
    tail     tokens kept from the END of the dialogue: 256 (V3) / 512 / full text  (truncation effect)
    word     word n-gram range (1,2) (V3) / (1,3) / none
    char     char_wb 3-5 (V3) / char_wb 2-5 / char 1-3 (Chinese has no spaces: plain char n-grams) / none
    min_df   2 (V3) / 5
    sublin   sublinear tf on (V3) / off
    roles    + word TF-IDF blocks of the customer-only text and of the last customer turn (role / turn separation)
    lang     + language indicator columns (EN / ZH intercepts; language-aware features)
  alpha: (0.3, 1, 3, 10, 30, 100) chosen on VAL MAE inside every config, final Ridge fitted on TRAIN only.
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from v4.f.f2_experiments import customer_text, last_customer  # noqa: E402
from v4.f.tfidf_predictor import CHARS_PER_TOKEN, guess_lang  # noqa: E402
from v5.f.common import FV5, RESULTS, load, mae, slope, spearman, write_json, y_of  # noqa: E402

ALPHAS = (0.3, 1, 3, 10, 30, 100)
BASE = {"tail": 256, "word": [1, 2], "char": "wb35", "min_df": 2, "sublin": True, "roles": False, "lang": False}
ONE_FACTOR = {"B_v3": {},
              "tail512": {"tail": 512}, "tailfull": {"tail": 0},
              "word13": {"word": [1, 3]}, "noword": {"word": None},
              "charwb25": {"char": "wb25"}, "char13": {"char": "c13"}, "nochar": {"char": None},
              "mindf5": {"min_df": 5}, "nosublin": {"sublin": False},
              "roles": {"roles": True}, "lang": {"lang": True}}
CHAR = {"wb35": ("char_wb", (3, 5)), "wb25": ("char_wb", (2, 5)), "c13": ("char", (1, 3))}


def cut(text, lang, n):
    return text if not n else text[-int(n * CHARS_PER_TOKEN["zh" if lang == "zh" else "en"]):]


class RidgeV5:
    """Fitted vectorisers + Ridge for one config. Pure sklearn parts (pickle-safe)."""

    def __init__(self, cfg):
        self.cfg = dict(cfg)

    def _views(self, rows):
        c = self.cfg
        full = [cut(r["text"], r["lang"], c["tail"]) for r in rows]
        v = {"full": full}
        if c["roles"]:
            v["cust"] = [cut(customer_text(r["text"]), r["lang"], c["tail"]) for r in rows]
            v["last"] = [last_customer(r["text"]) for r in rows]
        return v

    def fit_vec(self, rows):
        from sklearn.feature_extraction.text import TfidfVectorizer
        c, views = self.cfg, self._views(rows)
        kw = dict(min_df=c["min_df"], sublinear_tf=c["sublin"])
        self.vecs = []
        if c["word"]:
            self.vecs.append(("full", TfidfVectorizer(ngram_range=tuple(c["word"]), max_features=200000, **kw)
                              .fit(views["full"])))
        if c["char"]:
            an, rg = CHAR[c["char"]]
            self.vecs.append(("full", TfidfVectorizer(analyzer=an, ngram_range=rg, max_features=300000, **kw)
                              .fit(views["full"])))
        if c["roles"]:
            for v in ("cust", "last"):
                self.vecs.append((v, TfidfVectorizer(ngram_range=(1, 2), max_features=200000, **kw).fit(views[v])))
        return self

    def X(self, rows):
        from scipy.sparse import csr_matrix, hstack
        views = self._views(rows)
        blocks = [vec.transform(views[v]) for v, vec in self.vecs]
        if self.cfg["lang"]:
            blocks.append(csr_matrix(np.array([[r["lang"] == "en", r["lang"] == "zh"] for r in rows], float)))
        return hstack(blocks).tocsr()

    def n_features(self):
        return int(sum(len(v.vocabulary_) for _, v in self.vecs) + (2 if self.cfg["lang"] else 0))


def fit_config(cfg, tr, va):
    """Fit on TRAIN, choose alpha on VAL. Returns (model, ridge, info, val_pred)."""
    from sklearn.linear_model import Ridge
    m = RidgeV5(cfg).fit_vec(tr)
    Ftr, Fva = m.X(tr), m.X(va)
    ytr, yva = y_of(tr), y_of(va)
    grid = {}
    for al in ALPHAS:
        grid[al] = mae(yva, Ridge(alpha=al).fit(Ftr, ytr).predict(Fva))
    al = min(grid, key=grid.get)
    ridge = Ridge(alpha=al).fit(Ftr, ytr)
    pv = ridge.predict(Fva)
    lg = np.array([r["lang"] for r in va])
    info = {"config": cfg, "alpha": al, "val_mae_by_alpha": {str(k): round(v, 5) for k, v in grid.items()},
            "val_mae": mae(yva, pv), "val_mae_en": mae(yva[lg == "en"], pv[lg == "en"]),
            "val_mae_zh": mae(yva[lg == "zh"], pv[lg == "zh"]), "val_spearman": spearman(yva, np.clip(pv, 1, 5)),
            "val_slope": slope(yva, pv), "n_features": m.n_features(), "n_params": int(ridge.coef_.size + 1),
            "alpha_at_grid_edge": al in (ALPHAS[0], ALPHAS[-1])}
    return m, ridge, info, pv


def grid(tr, va):
    from v5.registry.registry import finish, register
    out_p = RESULTS / "f3_ridge_grid.json"
    res = json.loads(out_p.read_text()) if out_p.exists() else {"base": BASE, "configs": {}, "val_preds": {}}

    def run(name, cfg):
        if name in res["configs"]:
            return res["configs"][name]["val_mae"]
        rid = register("F", f"F3_ridge_{name}", config=cfg, dataset={"name": "USS v3 splits"},
                       note="F3 Ridge VAL grid; TEST not read")
        t0 = time.perf_counter()
        _, _, info, pv = fit_config(cfg, tr, va)
        info["seconds"] = round(time.perf_counter() - t0, 1)
        res["configs"][name] = info
        res["val_preds"][name] = [round(float(x), 4) for x in pv]
        write_json(out_p, res)
        finish(rid, "completed", results={k: info[k] for k in ("val_mae", "val_mae_en", "val_mae_zh", "alpha")},
               n_params=info["n_params"], duration_s=info["seconds"])
        print(f"{name:12s} VAL MAE {info['val_mae']:.4f} EN {info['val_mae_en']:.4f} ZH {info['val_mae_zh']:.4f} "
              f"alpha {info['alpha']} feats {info['n_features']} {info['seconds']}s", flush=True)
        return info["val_mae"]

    base = run("B_v3", BASE)
    gains = {}
    for name, ch in ONE_FACTOR.items():
        if name == "B_v3":
            continue
        gains[name] = base - run(name, {**BASE, **ch})
    helpful = sorted([k for k, g in gains.items() if g >= 0.001], key=lambda k: -gains[k])
    # greedy combination (rule fixed in the docstring); mutually exclusive factors: keep the first (best) one
    cur, cur_mae, kept, steps = dict(BASE), base, [], []
    for k in helpful:
        ch = ONE_FACTOR[k]
        if any(f in ch for f in set().union(*[ONE_FACTOR[x] for x in kept])):
            steps.append({"factor": k, "skipped": "same factor already kept"})
            continue
        cand = {**cur, **ch}
        name = "G_" + "+".join(kept + [k])
        m = run(name, cand)
        keep = cur_mae - m >= 0.001
        steps.append({"factor": k, "config_name": name, "val_mae": m, "kept": keep})
        if keep:
            cur, cur_mae, kept = cand, m, kept + [k]
    sel = "B_v3" if not kept else "G_" + "+".join(kept)
    if len(kept) == 1:
        sel = kept[0]
    res["one_factor_gain_vs_base"] = {k: round(v, 5) for k, v in gains.items()}
    res["greedy_steps"] = steps
    res["selected"] = {"name": sel, "config": cur, "val_mae": cur_mae,
                       "rule": "one-factor gain >= 0.001, greedy add in gain order, keep if >= 0.001 better"}
    write_json(out_p, res)
    print("selected", res["selected"])


def save(name, tr, va):
    """Refit the chosen config on TRAIN (alpha from VAL), save joblib + meta with SHA256. TEST is NOT read."""
    import joblib
    import sklearn
    g = json.loads((RESULTS / "f3_ridge_grid.json").read_text())
    cfg = g["configs"][name]["config"]
    m, ridge, info, _ = fit_config(cfg, tr, va)
    out = FV5 / "ckpt" / f"ridge_v5_{name}"
    out.mkdir(parents=True, exist_ok=True)
    mf = out / "model.joblib"
    joblib.dump({"cfg": cfg, "vecs": m.vecs, "ridge": ridge}, mf, compress=3)
    sha = hashlib.sha256(mf.read_bytes()).hexdigest()
    meta = {"model": f"ridge_v5_{name}", "model_file": mf.name, "sha256": sha, "size_bytes": mf.stat().st_size,
            "class": "v5.f.ridge_v5.RidgeV5Predictor", **info, "sklearn": sklearn.__version__,
            "label_type": "human_annotation (third-party annotators, mean of 3-7)",
            "languages_validated": ["en", "zh"], "trained_on": "USS train.jsonl (4,740 dialogues, EN+ZH)",
            "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    print(out, sha)
    return out


class RidgeV5Predictor:
    """Loadable v5 Ridge (same interface as V3/V4 predictors: .scores(texts, langs) / .predict)."""

    def __init__(self, parts, meta):
        self.m = RidgeV5(parts["cfg"])
        self.m.vecs = parts["vecs"]
        self.ridge, self.meta = parts["ridge"], meta

    @classmethod
    def load(cls, d, verify=True):
        import joblib
        d = Path(d)
        meta = json.loads((d / "meta.json").read_text())
        p = d / meta["model_file"]
        if verify and hashlib.sha256(p.read_bytes()).hexdigest() != meta["sha256"]:
            raise ValueError("SHA256 mismatch: refusing to unpickle " + str(p))
        return cls(joblib.load(p), meta)

    def raw_scores(self, texts, langs=None):
        langs = langs or [guess_lang(t) for t in texts]
        return self.ridge.predict(self.m.X([{"text": t, "lang": lg} for t, lg in zip(texts, langs)]))

    def scores(self, texts, langs=None):
        return np.clip(self.raw_scores(texts, langs), 1, 5)

    def predict(self, texts, langs=None):
        from v4.f.tfidf_predictor import label
        return [{"score": round(float(s), 3), "label": label(float(s))} for s in self.scores(texts, langs)]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["grid", "save"])
    ap.add_argument("--config", default=None)
    a = ap.parse_args(argv)
    tr, va = load("train"), load("val")
    if a.cmd == "grid":
        grid(tr, va)
    else:
        save(a.config, tr, va)


if __name__ == "__main__":
    main()
