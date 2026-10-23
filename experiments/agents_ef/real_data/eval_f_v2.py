"""Agent F v2: tiny multilingual satisfaction models on GENUINE ratings, per language and together.

    python -m real_data.eval_f_v2 --data <subset> --model e5small_trim_ft --seeds 0 1 2 \
        --vocab-corpus <unlabelled texts, never TEST> --save-dir <OUTSIDE git> --out results/f_v2_enfr

Subset format = real_data/prepare_subset.py / build_reviews_subset.py (jsonl with text, lang, rating 1-5).
Candidates (why each is here):
  mean / tfidf_ridge            floors: a model must beat these to be worth its RAM
  sentiment_zeroshot            Intake's own sentiment model (M4, English RoBERTa) mapped to 1-5 WITHOUT training:
                                shows that "sentiment" is not "satisfaction"
  sentiment_ridge               same 3 sentiment probabilities, Ridge fitted on TRAIN ratings
  *_frozen_ridge                pretrained multilingual sentence embeddings, frozen, + Ridge (no fine-tuning)
  tinybert_ft                   English-only 14M (winner of the SIMULATED benchmark)
  mminilm_ft                    paraphrase-multilingual-MiniLM-L12 (118M; winner on Olist)
  *_trim_ft                     the same multilingual encoders with the 250k-token vocabulary TRIMMED to the tokens
                                of an unlabelled corpus (EN/FR/PT): most of their parameters are the embedding table,
                                so trimming gives < 100M (often ~30M) with the same transformer layers.
TRAIN fits, VAL picks epoch / alpha / best seed, TEST scored once. Metrics overall and per language.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from real_data.eval_f_real import full_metrics  # noqa: E402

ENC = {
    "tinybert": "huawei-noah/TinyBERT_General_4L_312D",
    "mminilm": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "e5small": "intfloat/multilingual-e5-small",
    "mminilmv2l6": "nreimers/mMiniLMv2-L6-H384-distilled-from-XLMR-Large",
}
PREFIX = {"e5small": "query: "}
# pinned Hugging Face revisions (reproducibility): the commit the validated Agent F checkpoint was trained from
REVISION = {"e5small": "614241f622f53c4eeff9890bdc4f31cfecc418b3"}          # e5 models expect this prefix
SENTIMENT = "cardiffnlp/twitter-roberta-base-sentiment-latest"   # Intake M4 (config.yaml)
FT = {"tinybert_ft": ("tinybert", False), "mminilm_ft": ("mminilm", False), "mminilm_trim_ft": ("mminilm", True),
      "e5small_trim_ft": ("e5small", True), "mminilmv2l6_trim_ft": ("mminilmv2l6", True)}
FROZEN = {"mminilm_frozen_ridge": "mminilm", "e5small_frozen_ridge": "e5small"}
CLASSIC = ["mean", "tfidf_ridge", "sentiment_zeroshot", "sentiment_ridge"]


def peak_ram_mb():
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    except ImportError:                       # Windows
        import psutil
        return psutil.Process().memory_info().peak_wset / 2**20


def load(folder, split, langs=None):
    rows = [json.loads(line) for line in open(Path(folder) / f"{split}.jsonl", encoding="utf-8")]
    if langs:
        rows = [r for r in rows if r["lang"] in langs]
    return rows


def corpus_texts(paths, limit=40000):
    out = []
    for p in paths or []:
        for line in open(p, encoding="utf-8"):
            out.append(json.loads(line)["text"])
    return out[:limit]


# ---------------- vocabulary trimming ----------------
def build_remap(tok, texts):
    """Keep special tokens + every token id seen in the corpus. Returns (kept_ids, remap old->new, oov->unk)."""
    used = set(tok.all_special_ids)
    for i in range(0, len(texts), 512):
        for ids in tok(texts[i:i + 512], truncation=True, max_length=256)["input_ids"]:
            used.update(ids)
    kept = sorted(used)                     # sorted: ids 0..3 (<s>,<pad>,</s>,<unk>) keep their positions
    remap = torch.full((len(tok),), kept.index(tok.unk_token_id), dtype=torch.long)
    remap[torch.tensor(kept)] = torch.arange(len(kept))
    assert int(remap[tok.pad_token_id]) == tok.pad_token_id, "pad id must not move (position ids depend on it)"
    return kept, remap


def trim_model(bert, kept):
    emb = bert.get_input_embeddings()
    new = nn.Embedding(len(kept), emb.embedding_dim, padding_idx=emb.padding_idx)
    new.weight.data = emb.weight.data[torch.tensor(kept)].clone()
    bert.set_input_embeddings(new)
    bert.config.vocab_size = len(kept)
    return bert


class Reg(nn.Module):
    def __init__(self, bert, remap=None):
        super().__init__()
        self.bert = bert
        self.register_buffer("remap", remap if remap is not None else torch.zeros(0, dtype=torch.long))
        h = bert.config.hidden_size
        self.head = nn.Sequential(nn.Dropout(0.1), nn.Linear(h, 64), nn.ReLU(), nn.Linear(64, 1))

    def forward(self, ids, att):
        if self.remap.numel():
            ids = self.remap[ids]
        out = self.bert(input_ids=ids, attention_mask=att).last_hidden_state
        pooled = (out * att.unsqueeze(-1)).sum(1) / att.sum(1, keepdim=True)
        return self.head(pooled).squeeze(-1) + 3.0


def oov_rate(tok, remap, texts):
    if remap is None:
        return 0.0
    ids = torch.tensor([i for t in texts for i in tok(t, truncation=True, max_length=128)["input_ids"]])
    unk_new = int(remap[tok.unk_token_id])
    return float(((remap[ids] == unk_new) & (ids != tok.unk_token_id)).float().mean())


def run_ft(name, seed, tr, va, te, a):
    from transformers import AutoModel, AutoTokenizer
    enc_key, trim = FT[name]
    rev = REVISION.get(enc_key)
    tok = AutoTokenizer.from_pretrained(ENC[enc_key], revision=rev)
    pre = PREFIX.get(enc_key, "")
    bert = AutoModel.from_pretrained(ENC[enc_key], revision=rev).float()          # some checkpoints ship in fp16
    full_params = sum(p.numel() for p in bert.parameters())
    remap = None
    if trim:
        kept, remap = build_remap(tok, [pre + t for t in corpus_texts(a.vocab_corpus)])
        bert = trim_model(bert, kept)
    torch.manual_seed(seed)
    dev = torch.device(a.device)
    model = Reg(bert, remap).to(dev)
    if dev.type == "cuda":
        torch.cuda.reset_peak_memory_stats()
    enc = lambda X: {k: v.to(dev) for k, v in tok([pre + x for x in X], padding=True, truncation=True,
                                                    max_length=128, return_tensors="pt").items()}
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=0.01)
    Xtr, ytr = [r["text"] for r in tr], np.array([r["rating"] for r in tr], np.float32)
    Xva, yva = [r["text"] for r in va], np.array([r["rating"] for r in va], np.float32)

    def predict(X, bs=64):
        model.eval()
        out = []
        with torch.no_grad():
            for i in range(0, len(X), bs):
                b = enc(X[i:i + bs])
                out.append(model(b["input_ids"], b["attention_mask"]).float().cpu().numpy())
        return np.concatenate(out)

    best, best_state, curve = 1e9, None, []
    for ep in range(a.epochs):
        model.train()
        perm = np.random.default_rng(1000 * seed + ep).permutation(len(Xtr))
        for i in range(0, len(Xtr), 16):
            idx = perm[i:i + 16]
            b = enc([Xtr[j] for j in idx])
            with torch.autocast(device_type=dev.type, dtype=torch.float16, enabled=a.fp16 and dev.type == "cuda"):
                pred = model(b["input_ids"], b["attention_mask"])
            loss = nn.functional.mse_loss(pred.float(), torch.as_tensor(ytr[idx], device=dev))
            opt.zero_grad()
            loss.backward()
            opt.step()
        mae = float(np.abs(np.clip(predict(Xva), 1, 5) - yva).mean())
        curve.append(round(mae, 4))
        if mae < best:
            best, best_state = mae, {k: v.clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    n_params = sum(p.numel() for p in model.parameters())
    info = {"seed": seed, "best_epoch": int(np.argmin(curve)) + 1, "val_mae_curve": curve, "n_params": n_params,
            "encoder_params_before_trim": full_params, "base_model": ENC[enc_key], "revision": rev,
            "vocab_kept": int(model.bert.config.vocab_size), "trimmed": trim,
            "test_oov_token_rate": oov_rate(tok, remap, [pre + r["text"] for r in te]),
            "device": str(dev), "fp16": bool(a.fp16 and dev.type == "cuda"),
            "peak_vram_mb": round(torch.cuda.max_memory_allocated() / 2**20, 1) if dev.type == "cuda" else None,
            "disk_mb_fp32": round(sum(v.numel() * v.element_size() for v in model.state_dict().values()) / 1e6, 1)}
    if a.save_dir:
        ck = Path(a.save_dir) / f"{name}_s{seed}"
        ck.mkdir(parents=True, exist_ok=True)
        torch.save(model.state_dict(), ck / "model.pt")
        (ck / "meta.json").write_text(json.dumps({**info, "val_mae": best, "max_length": 128, "prefix": pre}, indent=2))
        info["checkpoint"] = str(ck)
    return (lambda rows: predict([r["text"] for r in rows])), info


def run_frozen(name, tr, va):
    from sentence_transformers import SentenceTransformer
    from sklearn.linear_model import Ridge
    key = FROZEN[name]
    m = SentenceTransformer(ENC[key], device="cpu")
    pre = PREFIX.get(key, "")
    emb = lambda rows: m.encode([pre + r["text"] for r in rows], batch_size=64, normalize_embeddings=True)
    Etr, Eva = emb(tr), emb(va)
    ytr, yva = np.array([r["rating"] for r in tr]), np.array([r["rating"] for r in va])
    best = min(((float(np.abs(np.clip(Ridge(alpha=al).fit(Etr, ytr).predict(Eva), 1, 5) - yva).mean()), al)
                for al in (0.3, 1, 3, 10)))
    rg = Ridge(alpha=best[1]).fit(Etr, ytr)
    n = sum(p.numel() for p in m.parameters()) + rg.coef_.size + 1
    return (lambda rows: rg.predict(emb(rows))), {"alpha": best[1], "n_params": int(n)}


def run_classic(name, tr, va):
    ytr, yva = np.array([r["rating"] for r in tr]), np.array([r["rating"] for r in va])
    if name == "mean":
        mu = float(ytr.mean())
        return (lambda rows: np.full(len(rows), mu)), {"n_params": 1}
    if name == "tfidf_ridge":
        from real_data.eval_f_real import run_classic as rc
        f, info = rc("tfidf_ridge", [r["text"] for r in tr], ytr, [r["text"] for r in va], yva, None)
        return (lambda rows: f([r["text"] for r in rows])), info
    from transformers import pipeline
    clf = pipeline("text-classification", model=SENTIMENT, device="cpu", top_k=None)

    def probs(rows):
        out = clf([r["text"] for r in rows], truncation=True, max_length=512, batch_size=32)
        return np.array([[{d["label"]: d["score"] for d in o}[k] for k in ("negative", "neutral", "positive")]
                         for o in out])
    if name == "sentiment_zeroshot":           # 1 star = surely negative, 5 = surely positive, 3 = neutral
        return (lambda rows: probs(rows) @ np.array([1.0, 3.0, 5.0])), {"n_params": 124_647_939, "trained": False}
    from sklearn.linear_model import Ridge
    rg = Ridge(alpha=1.0).fit(probs(tr), ytr)
    return (lambda rows: rg.predict(probs(rows))), {"n_params": 124_647_939 + 4, "trained": "ridge on 3 probs"}


def by_lang(rows, pred):
    y = np.array([r["rating"] for r in rows], np.float32)
    out = {"all": full_metrics(y, pred)}
    for lg in sorted({r["lang"] for r in rows}):
        m = np.array([r["lang"] == lg for r in rows])
        if m.sum() >= 20:
            out[lg] = full_metrics(y[m], pred[m])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--model", required=True, choices=[*CLASSIC, *FROZEN, *FT])
    ap.add_argument("--seeds", type=int, nargs="+", default=[0])
    ap.add_argument("--epochs", type=int, default=5)
    ap.add_argument("--lr", type=float, default=4e-5)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--train-langs", nargs="*", default=None, help="train on these languages only")
    ap.add_argument("--vocab-corpus", nargs="*", default=None, help="UNLABELLED texts for vocab trimming (not TEST)")
    ap.add_argument("--save-dir", default=None)
    ap.add_argument("--device", default="cpu", help="cpu or cuda (RTX 4050)")
    ap.add_argument("--fp16", action="store_true", help="CUDA only: mixed precision training")
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="")
    a = ap.parse_args(argv)
    torch.set_num_threads(a.threads)
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    tr, va, te = load(a.data, "train", a.train_langs), load(a.data, "val", a.train_langs), load(a.data, "test")
    runs = []
    for seed in (a.seeds if a.model in FT else [0]):
        t0 = time.perf_counter()
        if a.model in FT:
            predict, info = run_ft(a.model, seed, tr, va, te, a)
        elif a.model in FROZEN:
            predict, info = run_frozen(a.model, tr, va)
        else:
            predict, info = run_classic(a.model, tr, va)
        info["train_s"] = round(time.perf_counter() - t0, 1)
        lat = []
        for r in te[:60]:
            t1 = time.perf_counter()
            predict([r])
            lat.append(time.perf_counter() - t1)
        info["latency_ms_p50_cpu_batch1"] = round(1000 * float(np.median(lat[10:])), 3)
        pv, pt = np.asarray(predict(va), float), np.asarray(predict(te), float)
        runs.append({**info, "val": by_lang(va, pv), "test": by_lang(te, pt)})
    keys = ["mae", "rmse", "f1_macro_3class", "f1_macro_5class", "spearman"]
    groups = list(runs[0]["test"])
    best = min(runs, key=lambda r: r["val"]["all"]["mae"])
    res = {"model": a.model, "data": a.label, "train_langs": a.train_langs or "all",
           "n": {"train": len(tr), "val": len(va), "test": len(te)},
           "test_mean": {g: {k: float(np.mean([r["test"][g][k] for r in runs])) for k in keys} for g in groups},
           "test_std": {g: {k: float(np.std([r["test"][g][k] for r in runs])) for k in keys} for g in groups},
           "best_seed_by_val": best.get("seed", 0), "runs": runs,
           "peak_rss_mb": round(peak_ram_mb(), 1),
           "threads": a.threads, "device": a.device}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tag = a.model + ("_" + "".join(a.train_langs) if a.train_langs else "")
    (out / f"{tag}.json").write_text(json.dumps(res, indent=2))
    print(tag, {g: f"MAE {res['test_mean'][g]['mae']:.3f}±{res['test_std'][g]['mae']:.3f} "
                   f"F1 {res['test_mean'][g]['f1_macro_3class']:.3f}" for g in groups},
          "params", runs[0]["n_params"])


if __name__ == "__main__":
    main()
