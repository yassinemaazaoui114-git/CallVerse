"""F2 — a few targeted TF-IDF experiments about DOMAIN MISMATCH (not about more parameters).

    python -m v4.f.f2_experiments --data <f_v3>/data_uss [--test <variant>]

Baseline = V3 TF-IDF+Ridge on the last 256 tokens (re-fitted and saved by tfidf_predictor.py).
Variants, each a question about how the ShopNova conversations differ from USS:
  two_turn          only the FIRST customer turn + the LAST agent turn: the shape of a ShopNova conversation.
                    Question: how much satisfaction signal is left in USS when it looks like ShopNova?
  customer_only     only the customer's turns (last 256 tokens of them). Question: is it the customer's words
                    that carry the signal (ShopNova has one customer message)?
  roles             feature blocks: full tail + customer-only tail + last customer turn (turn/role separation,
                    so "sorry" from the agent and "sorry" from the customer are different features).
  lang_split        baseline features, one Ridge per language (language-aware: EN and ZH labels have different
                    means and spreads; a pooled model mixes them).
  roles_lang_split  both.
Selection: VAL MAE (all), ties within 0.002 -> fewer features. TEST is computed ONLY for the variant given with
--test (the VAL winner), once. Output: v4/f/results/f2_experiments.json (+ f2_test_<variant>.json).
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from v4.f.tfidf_predictor import ALPHAS, tail  # noqa: E402

CUST = ("Customer:", "客户:")
AGENT = ("Agent:", "客服:")


def lines(text):
    return [l for l in text.split("\n") if l.strip()]


def customer_text(text):
    return "\n".join(l for l in lines(text) if l.startswith(CUST))


def two_turn(text):
    ls = lines(text)
    c = next((l for l in ls if l.startswith(CUST)), "")
    a = next((l for l in reversed(ls) if l.startswith(AGENT)), "")
    return f"{c}\n{a}"


def last_customer(text):
    return next((l for l in reversed(lines(text)) if l.startswith(CUST)), "")


VIEWS = {"full": lambda r: tail(r["text"], r["lang"]),
         "two_turn": lambda r: two_turn(r["text"]),
         "customer_only": lambda r: tail(customer_text(r["text"]), r["lang"]),
         "last_customer": lambda r: last_customer(r["text"])}
VARIANTS = {"baseline": (["full"], False), "two_turn": (["two_turn"], False),
            "customer_only": (["customer_only"], False), "roles": (["full", "customer_only", "last_customer"], False),
            "lang_split": (["full"], True), "roles_lang_split": (["full", "customer_only", "last_customer"], True)}


class BlockModel:
    """TF-IDF word(1-2)+char_wb(3-5) per view block (same settings as V3), hstacked, Ridge on top."""

    def __init__(self, views):
        self.views = views

    def fit_vec(self, rows):
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.vecs = []
        for v in self.views:
            X = [VIEWS[v](r) for r in rows]
            w = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, max_features=200000).fit(X)
            c = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True,
                                max_features=300000).fit(X)
            self.vecs.append((v, w, c))
        return self

    def X(self, rows):
        from scipy.sparse import hstack
        blocks = []
        for v, w, c in self.vecs:
            X = [VIEWS[v](r) for r in rows]
            blocks += [w.transform(X), c.transform(X)]
        return hstack(blocks).tocsr()


def run_variant(name, tr, va, te=None):
    from sklearn.linear_model import Ridge
    views, split = VARIANTS[name]
    groups = sorted({r["lang"] for r in tr}) if split else ["all"]
    sel = lambda rows, g: [r for r in rows if g == "all" or r["lang"] == g]
    out = {"variant": name, "views": views, "lang_split": split, "groups": {}}
    pv_all, yv_all, pt_all, yt_all, nparams, models = [], [], [], [], 0, {}
    for g in groups:
        gtr, gva = sel(tr, g), sel(va, g)
        bm = BlockModel(views).fit_vec(gtr)
        Ftr, Fva = bm.X(gtr), bm.X(gva)
        ytr, yva = np.array([r["rating"] for r in gtr]), np.array([r["rating"] for r in gva])
        grid = [(float(np.abs(np.clip(Ridge(alpha=al).fit(Ftr, ytr).predict(Fva), 1, 5) - yva).mean()), al)
                for al in ALPHAS]
        best = min(grid)
        m = Ridge(alpha=best[1]).fit(Ftr, ytr)
        pv = np.clip(m.predict(Fva), 1, 5)
        nparams += int(m.coef_.size + 1)
        out["groups"][g] = {"alpha": best[1], "val_mae_grid": {str(a): round(e, 5) for e, a in grid}}
        models[g] = (bm, m)
        pv_all += list(pv)
        yv_all += list(yva)
        if te is not None:
            gte = sel(te, g)
            pt_all += list(np.clip(m.predict(bm.X(gte)), 1, 5))
            yt_all += [r["rating"] for r in gte]
    out["n_params"] = nparams
    out["val"] = metrics(np.array(yv_all), np.array(pv_all), [r["lang"] for g in groups for r in sel(va, g)])
    if te is not None:
        out["test"] = metrics(np.array(yt_all), np.array(pt_all), [r["lang"] for g in groups for r in sel(te, g)])
    out["_models"] = models
    return out


class BlockSatisfactionPredictor:
    """Saved F2 variant, same interface as SatisfactionPredictor (.scores / .predict). One model per language
    group when lang_split (group 'all' otherwise). Language of new text: tfidf_predictor.guess_lang."""

    def __init__(self, models, meta):
        self.models, self.meta = models, meta

    def scores(self, texts, langs=None):
        from v4.f.tfidf_predictor import guess_lang
        langs = langs or [guess_lang(t) for t in texts]
        out = np.zeros(len(texts))
        for i, (t, lg) in enumerate(zip(texts, langs)):
            g = "all" if "all" in self.models else ("zh" if lg == "zh" else "en")
            parts = self.models[g]
            bm = BlockModel(parts["views"])
            bm.vecs = parts["vecs"]
            out[i] = parts["ridge"].predict(bm.X([{"text": t, "lang": lg}]))[0]
        return np.clip(out, 1, 5)

    def predict(self, texts, langs=None):
        from v4.f.tfidf_predictor import label
        return [{"score": round(float(s), 3), "label": label(float(s))} for s in self.scores(texts, langs)]

    @classmethod
    def load(cls, ckpt_dir, verify=True):
        import joblib
        from v4.f.tfidf_predictor import sha256
        ckpt_dir = Path(ckpt_dir)
        meta = json.loads((ckpt_dir / "meta.json").read_text())
        path = ckpt_dir / meta["model_file"]
        if verify and sha256(path) != meta["sha256"]:
            raise ValueError(f"SHA256 mismatch for {path}: refusing to unpickle")
        return cls(joblib.load(path), meta)


def metrics(y, p, langs):
    from scipy.stats import spearmanr
    langs = np.array(langs)
    m = {"n": int(len(y)), "mae": round(float(np.abs(y - p).mean()), 5),
         "spearman": round(float(spearmanr(y, p).statistic), 4), "pred_sd": round(float(p.std()), 4)}
    for lg in sorted(set(langs)):
        k = langs == lg
        m[f"mae_{lg}"] = round(float(np.abs(y[k] - p[k]).mean()), 5)
        m[f"spearman_{lg}"] = round(float(spearmanr(y[k], p[k]).statistic), 4)
        m[f"pred_sd_{lg}"] = round(float(p[k].std()), 4)
    return m


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--variants", nargs="*", default=list(VARIANTS))
    ap.add_argument("--test", default=None, help="score TEST once for this (VAL-selected) variant")
    ap.add_argument("--save", default=None, help="with --test: save the fitted variant here (joblib + meta + SHA256)")
    a = ap.parse_args(argv)
    load = lambda s: [json.loads(l) for l in open(Path(a.data) / f"{s}.jsonl", encoding="utf-8")]
    tr, va = load("train"), load("val")
    res_p = HERE / "results" / "f2_experiments.json"
    res = json.loads(res_p.read_text()) if res_p.exists() else {"variants": {}}
    if a.test:
        te = load("test")
        t0 = time.perf_counter()
        r = run_variant(a.test, tr, va, te)
        r["seconds"] = round(time.perf_counter() - t0, 1)
        models = r.pop("_models")
        if a.save:
            import joblib
            from v4.f.tfidf_predictor import sha256
            out = Path(a.save)
            out.mkdir(parents=True, exist_ok=True)
            mf = out / "model.joblib"
            # plain parts only (no class from this module inside the pickle: it may run as __main__)
            joblib.dump({g: {"views": bm.views, "vecs": bm.vecs, "ridge": m} for g, (bm, m) in models.items()},
                        mf, compress=3)
            meta = {"model": f"tfidf_{a.test}_tail256", "model_file": mf.name, "sha256": sha256(mf),
                    "size_bytes": mf.stat().st_size, "class": "v4.f.f2_experiments.BlockSatisfactionPredictor",
                    "variant": a.test, "views": r["views"], "lang_split": r["lang_split"], "n_params": r["n_params"],
                    "alphas": {g: v["alpha"] for g, v in r["groups"].items()},
                    "label_type": "human_annotation (third-party annotators, mean of 3-7)",
                    "domain": "task_oriented_dialogue + JDDC e-commerce service (zh)",
                    "languages_validated": ["en", "zh"], "val": r["val"], "test": r["test"],
                    "trained_on": "USS train.jsonl (4,740 dialogues, EN+ZH)"}
            (out / "meta.json").write_text(json.dumps(meta, indent=2))
            r["checkpoint"], r["sha256"], r["size_bytes"] = str(out), meta["sha256"], meta["size_bytes"]
        (HERE / "results" / f"f2_test_{a.test}.json").write_text(json.dumps(r, indent=1))
        print(json.dumps(r, indent=1))
        return
    for name in a.variants:
        if name in res["variants"]:
            print("done already:", name)
            continue
        t0 = time.perf_counter()
        r = run_variant(name, tr, va)
        r["seconds"] = round(time.perf_counter() - t0, 1)
        r.pop("_models")
        res["variants"][name] = r
        res_p.write_text(json.dumps(res, indent=1))                 # resumable: one variant at a time
        print(name, r["val"], r["n_params"], r["seconds"], "s", flush=True)
    base = res["variants"].get("baseline", {}).get("val", {}).get("mae")
    if base is not None:
        ranked = sorted(res["variants"].values(), key=lambda r: (r["val"]["mae"], r["n_params"]))
        best = ranked[0]
        # tie rule: within 0.002 of the best VAL MAE, prefer fewer parameters
        tied = [r for r in ranked if r["val"]["mae"] - best["val"]["mae"] <= 0.002]
        res["selection"] = {"rule": "lowest VAL MAE; within 0.002 prefer fewer parameters",
                            "val_ranking": [(r["variant"], r["val"]["mae"], r["n_params"]) for r in ranked],
                            "selected": min(tied, key=lambda r: r["n_params"])["variant"]}
        res_p.write_text(json.dumps(res, indent=1))
        print("selection:", res["selection"])


if __name__ == "__main__":
    main()
