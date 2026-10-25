"""Agent F v3 benchmark: predict DIALOGUE-LEVEL user satisfaction (1-5) after a support dialogue ends.

    python v3/f/bench_uss.py --data <f_v3/data_uss> --model e5small_trim_ft --seeds 0 1 2 \
        --save-dir <f_v3/ckpt> --out v3/f/results/uss [--train-langs en] [--layers 6] [--device cuda --fp16]

Data = jsonl made by v3/f/uss_data.py: one row per DIALOGUE (text = all turns, "Customer:/Agent:" lines),
rating = mean of the annotators' OVERALL ratings. Splits are by dialogue, so no turn leaks across splits.
Why each candidate is here:
  mean, group_mean        floors: TRAIN mean overall / per sub-dataset (a model must beat the per-group floor,
                          otherwise it only learned "which corpus is this")
  tfidf_ridge             word 1-2 + char 3-5 gram TF-IDF + Ridge (same code as v2), alpha on VAL
  tfidf_logreg            same features, multinomial logistic regression on rounded labels; prediction = expected
                          value of the class probabilities (an ordinal-friendly classifier), C on VAL
  hgb_features            HistGradientBoosting on simple dialogue features (length, turns, '?', thanks, sorry...)
  *_ft                    fine-tuned transformer encoders (mean pooling + small regression head, MSE loss)
                          dialogue text truncated from the LEFT to --max-len tokens: the END of the dialogue
                          (how it was resolved) is kept, because it matters most for after-the-fact satisfaction.
  *_trim_ft               multilingual encoders with the vocabulary trimmed to tokens of TRAIN+VAL dialogue texts
                          (unlabelled use only, never TEST); --layers N keeps only the first N transformer layers.
TRAIN fits, VAL picks epoch / alpha / C / best seed, TEST is scored once per run. Output: metrics only, no text.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))                 # experiments/agents_ef
from real_data.eval_f_v2 import ENC, PREFIX, REVISION, Reg, peak_ram_mb, trim_model  # noqa: E402

FT = {"tinybert_ft": ("tinybert", False), "e5small_trim_ft": ("e5small", True),
      "mminilm_trim_ft": ("mminilm", True), "mminilmv2l6_trim_ft": ("mminilmv2l6", True)}
CLASSIC = ["mean", "group_mean", "tfidf_ridge", "tfidf_logreg", "hgb_features"]


# ---------------- data ----------------
def load(folder, split, langs=None):
    rows = [json.loads(line) for line in open(Path(folder) / f"{split}.jsonl", encoding="utf-8")]
    return [r for r in rows if not langs or r["lang"] in langs]


def to_int(y):
    """Mean of annotators (e.g. 3.33) -> ordinal class 1..5 by rounding half up (3.5 -> 4)."""
    return np.clip(np.floor(np.asarray(y, float) + 0.5), 1, 5).astype(int)


def subsample(rows, frac, seed=13):
    """Stratified TRAIN subsample: the same fraction of every sub-dataset, deterministic (CPU budget only).
    One RNG per sub-dataset, so an EN-only run picks exactly the same EN dialogues as an all-language run."""
    import random
    out = []
    for sub in sorted({r["sub"] for r in rows}):
        part = [r for r in rows if r["sub"] == sub]
        out += random.Random(f"{seed}-{sub}").sample(part, round(frac * len(part)))
    return out


# ---------------- metrics ----------------
def metrics(y, p):
    """All ordinal metrics for true mean ratings y and predicted scores p (both on the 1-5 scale)."""
    from scipy.stats import spearmanr
    from sklearn.metrics import cohen_kappa_score, confusion_matrix, f1_score, precision_recall_fscore_support
    y, p = np.asarray(y, float), np.clip(np.asarray(p, float), 1, 5)
    yi, pi = to_int(y), to_int(p)
    c3 = lambda v: np.digitize(v, [2.5, 3.5])               # 1-2 / 3 / 4-5 on the continuous scale
    y3, p3 = c3(y), c3(p)
    pr, rc, f1, sup = precision_recall_fscore_support(y3, p3, labels=[0, 1, 2], zero_division=0)
    m = {"n": int(len(y)), "mae": float(np.abs(y - p).mean()), "rmse": float(np.sqrt(((y - p) ** 2).mean())),
         "qwk": float(cohen_kappa_score(yi, pi, weights="quadratic", labels=[1, 2, 3, 4, 5])),
         "spearman": float(spearmanr(y, p).correlation) if np.std(p) > 0 else float("nan"),
         "exact_acc": float((yi == pi).mean()), "within1_acc": float((np.abs(yi - pi) <= 1).mean()),
         "f1_macro_3class": float(f1_score(y3, p3, average="macro", labels=[0, 1, 2], zero_division=0)),
         "per_class_3": {k: {"precision": float(pr[i]), "recall": float(rc[i]), "f1": float(f1[i]),
                             "support": int(sup[i])} for i, k in enumerate(["low_1-2", "mid_3", "high_4-5"])},
         "confusion_5": confusion_matrix(yi, pi, labels=[1, 2, 3, 4, 5]).tolist(),
         "confusion_3": confusion_matrix(y3, p3, labels=[0, 1, 2]).tolist(),
         # calibration of error: mean signed error (pred - true) per TRUE class (regression-to-the-mean check)
         "signed_error_by_true_class": {int(k): float((p[yi == k] - y[yi == k]).mean())
                                        for k in range(1, 6) if (yi == k).any()},
         "mae_by_true_class": {int(k): float(np.abs(p[yi == k] - y[yi == k]).mean())
                               for k in range(1, 6) if (yi == k).any()},
         "pred_std": float(np.std(p)), "true_std": float(np.std(y))}
    return m


def grouped(rows, pred):
    y = np.array([r["rating"] for r in rows], float)
    out = {"all": metrics(y, pred)}
    keys = sorted({("lang", r["lang"]) for r in rows} | {("sub", r["sub"]) for r in rows if "sub" in r})
    for kind, val in keys:
        mask = np.array([r.get(kind) == val for r in rows])
        if mask.sum() >= 20:
            out[f"{kind}:{val}"] = metrics(y[mask], np.asarray(pred)[mask])
    return out


# ---------------- classic models ----------------
FEAT_WORDS = {"thank": r"thank|merci|谢谢|感谢", "sorry": r"sorry|désolé|抱歉|不好意思",
              "no": r"\bno\b|\bnot\b|不|没", "bye": r"bye|再见", "great": r"great|perfect|好的|满意"}


def features(r):
    user = [l[l.index(":") + 1:] for l in r["text"].split("\n") if l.startswith(("Customer:", "客户:"))]
    last = user[-1] if user else ""
    low = r["text"].lower()
    f = [r["n_turns"], r["n_user_turns"], r["n_chars"], np.mean([len(u) for u in user]) if user else 0,
         len(last), sum(u.count("?") + u.count("？") for u in user), float(r["lang"] == "zh")]
    f += [len(re.findall(p, low)) for p in FEAT_WORDS.values()]
    f += [len(re.findall(p, last.lower())) for p in FEAT_WORDS.values()]
    return f


def run_classic(name, tr, va):
    ytr, yva = np.array([r["rating"] for r in tr]), np.array([r["rating"] for r in va])
    mae = lambda p: float(np.abs(np.clip(p, 1, 5) - yva).mean())
    if name == "mean":
        mu = float(ytr.mean())
        return (lambda rows: np.full(len(rows), mu)), {"n_params": 1}
    if name == "group_mean":
        mus = {s: float(np.mean([r["rating"] for r in tr if r["sub"] == s])) for s in {r["sub"] for r in tr}}
        return (lambda rows: np.array([mus[r["sub"]] for r in rows])), {"n_params": len(mus),
                                                                        "note": "uses the sub-dataset id"}
    if name == "hgb_features":
        from sklearn.ensemble import HistGradientBoostingRegressor
        Ftr, Fva = np.array([features(r) for r in tr]), np.array([features(r) for r in va])
        best = min((mae(HistGradientBoostingRegressor(max_depth=d, learning_rate=0.05, max_iter=200,
                                                      random_state=0).fit(Ftr, ytr).predict(Fva)), d)
                   for d in (2, 3, 4))
        m = HistGradientBoostingRegressor(max_depth=best[1], learning_rate=0.05, max_iter=200,
                                          random_state=0).fit(Ftr, ytr)
        return (lambda rows: m.predict(np.array([features(r) for r in rows]))), \
            {"max_depth": best[1], "n_features": Ftr.shape[1], "n_params": "200 trees"}
    from scipy.sparse import hstack
    from sklearn.feature_extraction.text import TfidfVectorizer
    Xtr = [r["text"] for r in tr]
    w = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, max_features=200000).fit(Xtr)
    ch = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True,
                         max_features=300000).fit(Xtr)
    f = lambda rows: hstack([w.transform([r["text"] for r in rows]), ch.transform([r["text"] for r in rows])]).tocsr()
    Ftr, Fva = f(tr), f(va)
    if name == "tfidf_ridge":
        from sklearn.linear_model import Ridge
        best = min((mae(Ridge(alpha=al).fit(Ftr, ytr).predict(Fva)), al) for al in (0.3, 1, 3, 10, 30))
        m = Ridge(alpha=best[1]).fit(Ftr, ytr)
        return (lambda rows: m.predict(f(rows))), {"alpha": best[1], "n_params": int(m.coef_.size + 1)}
    from sklearn.linear_model import LogisticRegression
    yi = to_int(ytr)

    def fit(C):
        return LogisticRegression(C=C, max_iter=2000).fit(Ftr, yi)
    ev = lambda m, F: m.predict_proba(F) @ m.classes_.astype(float)
    best = min((mae(ev(fit(C), Fva)), C) for C in (0.3, 1, 3, 10, 30))
    m = fit(best[1])
    return (lambda rows: ev(m, f(rows))), {"C": best[1], "n_params": int(m.coef_.size + m.intercept_.size),
                                           "classes": m.classes_.tolist()}


# ---------------- fine-tuned encoders ----------------
def build_remap(tok, texts):
    """Keep special tokens + every token id seen in the (unlabelled TRAIN+VAL) texts. old id -> new id."""
    used = set(tok.all_special_ids)
    for i in range(0, len(texts), 256):
        for ids in tok(texts[i:i + 256], truncation=False)["input_ids"]:
            used.update(ids)
    kept = sorted(used)
    remap = torch.full((len(tok),), kept.index(tok.unk_token_id), dtype=torch.long)
    remap[torch.tensor(kept)] = torch.arange(len(kept))
    assert int(remap[tok.pad_token_id]) == tok.pad_token_id, "pad id must not move"
    return kept, remap


def keep_layers(bert, n):
    """Layer truncation: keep the first n transformer layers (lower layers carry general language knowledge)."""
    bert.encoder.layer = nn.ModuleList(list(bert.encoder.layer)[:n])
    bert.config.num_hidden_layers = n
    return bert


def run_ft(name, seed, tr, va, te, a):
    from transformers import AutoModel, AutoTokenizer
    enc_key, trim = FT[name]
    rev = REVISION.get(enc_key)
    tok = AutoTokenizer.from_pretrained(ENC[enc_key], revision=rev)
    tok.truncation_side = "left"                            # keep the END of long dialogues
    pre = PREFIX.get(enc_key, "")
    bert = AutoModel.from_pretrained(ENC[enc_key], revision=rev).float()
    full_params = sum(p.numel() for p in bert.parameters())
    remap = None
    if trim:
        kept, remap = build_remap(tok, [pre + r["text"] for r in tr + va])
        bert = trim_model(bert, kept)
    if a.layers:
        bert = keep_layers(bert, a.layers)
    torch.manual_seed(seed)
    dev = torch.device(a.device)
    model = Reg(bert, remap).to(dev)
    if dev.type == "cuda":
        torch.cuda.reset_peak_memory_stats()
    enc = lambda X: {k: v.to(dev) for k, v in tok([pre + x for x in X], padding=True, truncation=True,
                                                    max_length=a.max_len, return_tensors="pt").items()}
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=0.01)
    Xtr, ytr = [r["text"] for r in tr], np.array([r["rating"] for r in tr], np.float32)
    Xva, yva = [r["text"] for r in va], np.array([r["rating"] for r in va], np.float32)

    def predict(X, bs=32):
        model.eval()
        out = []
        with torch.no_grad():
            for i in range(0, len(X), bs):
                b = enc(X[i:i + bs])
                out.append(model(b["input_ids"], b["attention_mask"]).float().cpu().numpy())
        return np.concatenate(out)

    best, best_state, curve, ep_s = 1e9, None, [], []
    for ep in range(a.epochs):
        t0 = time.perf_counter()
        model.train()
        perm = np.random.default_rng(1000 * seed + ep).permutation(len(Xtr))
        for i in range(0, len(Xtr), a.batch):
            idx = perm[i:i + a.batch]
            b = enc([Xtr[j] for j in idx])
            with torch.autocast(device_type=dev.type, dtype=torch.float16, enabled=a.fp16 and dev.type == "cuda"):
                pred = model(b["input_ids"], b["attention_mask"])
            loss = nn.functional.mse_loss(pred.float(), torch.as_tensor(ytr[idx], device=dev))
            opt.zero_grad()
            loss.backward()
            opt.step()
        mae = float(np.abs(np.clip(predict(Xva), 1, 5) - yva).mean())
        curve.append(round(mae, 4))
        ep_s.append(round(time.perf_counter() - t0, 1))
        print(f"  {name} seed {seed} epoch {ep + 1}: VAL MAE {mae:.4f} ({ep_s[-1]} s)", flush=True)
        if mae < best:
            best, best_state = mae, {k: v.clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    n_params = sum(p.numel() for p in model.parameters())
    trunc = float(np.mean([len(tok(pre + r["text"])["input_ids"]) > a.max_len for r in te]))
    info = {"seed": seed, "best_epoch": int(np.argmin(curve)) + 1, "val_mae_curve": curve, "epoch_s": ep_s,
            "n_params": n_params, "encoder_params_before_trim": full_params, "base_model": ENC[enc_key],
            "revision": rev, "vocab_kept": int(model.bert.config.vocab_size), "trimmed": trim,
            "layers": int(model.bert.config.num_hidden_layers), "max_len": a.max_len,
            "test_share_truncated": round(trunc, 3), "device": str(dev),
            "fp16": bool(a.fp16 and dev.type == "cuda"),
            "peak_vram_mb": round(torch.cuda.max_memory_allocated() / 2**20, 1) if dev.type == "cuda" else None,
            "disk_mb_fp32": round(sum(v.numel() * v.element_size() for v in model.state_dict().values()) / 1e6, 1)}
    if a.save_dir:
        ck = Path(a.save_dir) / f"{a.tag}_s{seed}"
        ck.mkdir(parents=True, exist_ok=True)
        torch.save(model.state_dict(), ck / "model.pt")
        (ck / "meta.json").write_text(json.dumps({**info, "val_mae": best, "max_length": a.max_len,
                                                  "prefix": pre, "truncation_side": "left"}, indent=2))
        info["checkpoint"] = str(ck)
    return (lambda rows: predict([r["text"] for r in rows])), info


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--model", required=True, choices=[*CLASSIC, *FT])
    ap.add_argument("--seeds", type=int, nargs="+", default=[0])
    ap.add_argument("--epochs", type=int, default=5)
    ap.add_argument("--lr", type=float, default=4e-5)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--max-len", type=int, default=256)
    ap.add_argument("--layers", type=int, default=0, help="keep only the first N transformer layers (0 = all)")
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--tail-tokens", type=int, default=0,
                    help="diagnostic for classic models: keep only about the last N e5 tokens of each dialogue "
                         "(what a left-truncated transformer sees), using chars/token measured on VAL: "
                         "EN 3.97, ZH 1.39; 0 = full text")
    ap.add_argument("--train-frac", type=float, default=0,
                    help="CPU budget: keep this fraction of the TRAIN dialogues of every sub-dataset (seed 13); 0 = all")
    ap.add_argument("--train-langs", nargs="*", default=None, help="train AND evaluate on these languages only")
    ap.add_argument("--save-dir", default=None)
    ap.add_argument("--device", default="cpu", help="cpu or cuda (RTX 4050)")
    ap.add_argument("--fp16", action="store_true", help="CUDA only: mixed precision")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    torch.set_num_threads(a.threads)
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    a.tag = a.model + (f"_L{a.layers}" if a.layers else "") + ("_" + "".join(a.train_langs) if a.train_langs else "") \
        + (f"_frac{a.train_frac:g}" if a.train_frac else "") \
        + (f"_tail{a.tail_tokens}tok" if a.tail_tokens else "") + (f"_len{a.max_len}" if a.model in FT else "")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if (out / f"{a.tag}.json").exists():
        print("exists, skipping:", out / f"{a.tag}.json")
        return
    tr, va, te = (load(a.data, s, a.train_langs) for s in ("train", "val", "test"))
    if a.train_frac:
        tr = subsample(tr, a.train_frac)
    if a.tail_tokens:
        cpt = {"en": 3.97, "zh": 1.39}          # e5 tokenizer, measured on VAL (2026-10-25)
        cut = lambda r: {**r, "text": r["text"][-int(a.tail_tokens * cpt[r["lang"]]):]}
        tr, va, te = ([cut(r) for r in rows] for rows in (tr, va, te))
    runs = []
    for seed in (a.seeds if a.model in FT else [0]):
        t0 = time.perf_counter()
        if a.model in FT:
            predict, info = run_ft(a.model, seed, tr, va, te, a)
        else:
            predict, info = run_classic(a.model, tr, va)
        info["train_s"] = round(time.perf_counter() - t0, 1)
        lat = []
        for r in te[:70]:                                   # batch 1, real TEST-length dialogues
            t1 = time.perf_counter()
            predict([r])
            lat.append(time.perf_counter() - t1)
        lat = np.array(lat[10:]) * 1000
        info["latency_ms_cpu_batch1"] = {"p50": round(float(np.percentile(lat, 50)), 2),
                                         "p95": round(float(np.percentile(lat, 95)), 2)}
        pv, pt = np.asarray(predict(va), float), np.asarray(predict(te), float)
        runs.append({**info, "val": grouped(va, pv), "test": grouped(te, pt),
                     "test_pred": [round(float(x), 4) for x in pt]})   # predictions only (no text) for analysis
    keys = ["mae", "rmse", "qwk", "spearman", "exact_acc", "within1_acc", "f1_macro_3class"]
    groups = list(runs[0]["test"])
    agg = lambda split, fn: {g: {k: float(fn([r[split][g][k] for r in runs])) for k in keys} for g in groups}
    best = min(runs, key=lambda r: r["val"]["all"]["mae"])
    res = {"model": a.tag, "base": a.model, "train_langs": a.train_langs or "all",
           "n": {"train": len(tr), "val": len(va), "test": len(te)},
           "test_ids": [r["id"] for r in te],
           "val_mean": agg("val", np.mean), "test_mean": agg("test", np.mean), "test_std": agg("test", np.std),
           "best_seed_by_val": best.get("seed", 0), "runs": runs, "peak_rss_mb": round(peak_ram_mb(), 1),
           "threads": a.threads, "device": a.device, "args": {k: v for k, v in vars(a).items() if k != "out"}}
    (out / f"{a.tag}.json").write_text(json.dumps(res, indent=1))
    print(a.tag, {g: f"MAE {res['test_mean'][g]['mae']:.3f}±{res['test_std'][g]['mae']:.3f} "
                     f"QWK {res['test_mean'][g]['qwk']:.3f}" for g in groups if ":" not in g or "lang" in g},
          "params", runs[0]["n_params"])


if __name__ == "__main__":
    main()
