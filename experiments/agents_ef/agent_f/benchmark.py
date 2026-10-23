"""Benchmark ONE Agent F satisfaction model (run each model in its own process so peak RAM is per model).

    python -m agent_f.benchmark --model tfidf_ridge --out results/agent_f
Models (smallest first):
  meta_ridge     context only (queue, wait/SLA, fallback, abandoned, queue state) -> Ridge. No text.
  meta_gbm       same context -> HistGradientBoosting (non-linear, still tiny).
  tfidf_ridge    TF-IDF word 1-2 grams + context -> Ridge.
  bow_mlp        hashed bag-of-words (4096) + context -> 2-layer MLP trained from scratch (PyTorch).
  bge_head       BAAI/bge-small-en-v1.5 (the project's M3, frozen) sentence embedding + context -> MLP head.
  minilm_head    sentence-transformers/all-MiniLM-L6-v2 (frozen) + context -> MLP head.
  tinybert_ft    huawei-noah/TinyBERT_General_4L_312D (14M) fine-tuned end-to-end, [CLS] + context -> head.
  distilbert_ft  distilbert-base-uncased (66M) fine-tuned the same way: the "bigger model" reference.
Training uses TRAIN only; epochs / alpha / early stopping use VAL only; TEST is scored once at the end.
Regression to CSAT (1..5); metrics: MAE, RMSE, exact accuracy (rounded), macro-F1 on 3 classes
(1-2 unhappy / 3 neutral / 4-5 happy), Spearman. Plus parameters, disk size, CPU latency, peak RAM.
All data is SIMULATED (see make_dataset.py).
"""

import argparse
import io
import json
import os
import pickle
import resource
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DATA = Path(__file__).resolve().parent.parent / "results" / "agent_f_data"
EPOCHS = {"tinybert_ft": 3, "distilbert_ft": 2}     # same data, fewer epochs for the 66M model (CPU budget)


def load(split):
    return [json.loads(line) for line in open(DATA / f"{split}.jsonl")]


def meta(rows) -> np.ndarray:
    """13 context features: queue one-hot (4), wait/SLA, fallback, abandoned, queue state (6, as E sees it)."""
    out = []
    for r in rows:
        q = np.zeros(4)
        q[r["queue"]] = 1
        out.append(np.concatenate([q, [min(r["wait_min"] / r["sla_min"], 5.0), float(r["fallback"]),
                                       float(r["abandoned"])], r["state"]]))
    return np.array(out, np.float32)


def metrics(y, p) -> dict:
    from scipy.stats import spearmanr
    from sklearn.metrics import f1_score
    p = np.clip(p, 1, 5)
    c = lambda v: np.digitize(v, [2.5, 3.5])                  # 0 unhappy (1-2), 1 neutral (3), 2 happy (4-5)
    return {"mae": float(np.abs(y - p).mean()), "rmse": float(np.sqrt(((y - p) ** 2).mean())),
            "exact_acc": float((np.round(p) == y).mean()), "f1_macro_3class": float(f1_score(c(y), c(p), average="macro")),
            "spearman": float(spearmanr(y, p).correlation)}


def size_bytes(obj) -> int:
    buf = io.BytesIO()
    if isinstance(obj, nn.Module):
        torch.save(obj.state_dict(), buf)
    else:
        pickle.dump(obj, buf)
    return buf.getbuffer().nbytes


class Head(nn.Module):
    def __init__(self, d_in, hidden=64):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(d_in, hidden), nn.ReLU(), nn.Dropout(0.1), nn.Linear(hidden, 1))

    def forward(self, x):
        return self.net(x).squeeze(-1) + 4.0       # labels centred near 4


def fit_torch(model, Xtr, ytr, Xva, yva, epochs=40, lr=2e-3, batch=128, seed=0):
    """Mini-batch MSE training with early stopping on VAL MAE; returns the best state."""
    torch.manual_seed(seed)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    Xtr, ytr, Xva = torch.as_tensor(Xtr), torch.as_tensor(ytr, dtype=torch.float32), torch.as_tensor(Xva)
    best, best_state, bad = 1e9, None, 0
    for ep in range(epochs):
        model.train()
        perm = torch.randperm(len(Xtr))
        for i in range(0, len(Xtr), batch):
            idx = perm[i:i + batch]
            loss = nn.functional.mse_loss(model(Xtr[idx]), ytr[idx])
            opt.zero_grad()
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            mae = float(np.abs(np.clip(model(Xva).numpy(), 1, 5) - yva).mean())
        if mae < best - 1e-4:
            best, best_state, bad = mae, {k: v.clone() for k, v in model.state_dict().items()}, 0
        else:
            bad += 1
            if bad >= 6:
                break
    model.load_state_dict(best_state)
    model.eval()
    return model, ep + 1


def hashed_bow(texts, dim=4096):
    from sklearn.feature_extraction.text import HashingVectorizer
    hv = HashingVectorizer(n_features=dim, ngram_range=(1, 2), alternate_sign=False, norm="l2")
    return hv, hv.transform(texts).toarray().astype(np.float32)


def run(model_name: str, seed: int = 0, save_dir: str | None = None):
    tr, va, te = load("train"), load("val"), load("test")
    ytr, yva, yte = (np.array([r["csat"] for r in s], np.float32) for s in (tr, va, te))
    mtr, mva, mte = meta(tr), meta(va), meta(te)
    txt = lambda rows: [r["text"] for r in rows]
    t0 = time.perf_counter()
    info = {}

    if model_name in ("meta_ridge", "tfidf_ridge"):
        from scipy.sparse import csr_matrix, hstack
        from sklearn.linear_model import Ridge
        if model_name == "tfidf_ridge":
            from sklearn.feature_extraction.text import TfidfVectorizer
            vec = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True).fit(txt(tr))
            feats = lambda rows, m: hstack([vec.transform(txt(rows)), csr_matrix(m)]).tocsr()
        else:
            vec = None
            feats = lambda rows, m: m
        Xtr, Xva = feats(tr, mtr), feats(va, mva)
        best = min(((float(np.abs(np.clip(Ridge(alpha=a).fit(Xtr, ytr).predict(Xva), 1, 5) - yva).mean()), a)
                    for a in (0.1, 0.3, 1, 3, 10)))
        model = Ridge(alpha=best[1]).fit(Xtr, ytr)
        info["alpha_chosen_on_val"] = best[1]
        predict = lambda rows, m: model.predict(feats(rows, m))
        n_params = int(model.coef_.size + 1)
        disk = size_bytes((vec, model))

    elif model_name == "meta_gbm":
        from sklearn.ensemble import HistGradientBoostingRegressor
        model = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, early_stopping=True,
                                              validation_fraction=None, random_state=0)
        # early stopping on our VAL split: fit with increasing iterations is costly; use sklearn's
        # internal split off TRAIN instead (VAL stays untouched for reporting val metrics)
        model.set_params(validation_fraction=0.1).fit(mtr, ytr)
        predict = lambda rows, m: model.predict(m)
        n_params = int(sum(len(p.nodes) for its in model._predictors for p in its))   # tree nodes
        info["param_note"] = "number of tree nodes"
        disk = size_bytes(model)

    elif model_name == "bow_mlp":
        hv, Btr = hashed_bow(txt(tr))
        Bva = hv.transform(txt(va)).toarray().astype(np.float32)
        net = Head(Btr.shape[1] + mtr.shape[1], hidden=64)
        net, ep = fit_torch(net, np.hstack([Btr, mtr]), ytr, np.hstack([Bva, mva]), yva)
        info["epochs"] = ep

        def predict(rows, m):
            with torch.no_grad():
                return net(torch.as_tensor(np.hstack([hv.transform(txt(rows)).toarray().astype(np.float32), m])
                                           )).numpy()
        n_params = sum(p.numel() for p in net.parameters())
        disk = size_bytes(net)

    elif model_name in ("bge_head", "minilm_head"):
        from sentence_transformers import SentenceTransformer
        name = "BAAI/bge-small-en-v1.5" if model_name == "bge_head" else "sentence-transformers/all-MiniLM-L6-v2"
        enc = SentenceTransformer(name, device="cpu")
        emb = lambda rows: enc.encode(txt(rows), batch_size=64, normalize_embeddings=True, convert_to_numpy=True)
        Etr, Eva = emb(tr), emb(va)
        net = Head(Etr.shape[1] + mtr.shape[1], hidden=64)
        net, ep = fit_torch(net, np.hstack([Etr, mtr]), ytr, np.hstack([Eva, mva]), yva)
        info["epochs"] = ep

        def predict(rows, m):
            with torch.no_grad():
                return net(torch.as_tensor(np.hstack([emb(rows), m]))).numpy()
        n_params = sum(p.numel() for p in enc.parameters()) + sum(p.numel() for p in net.parameters())
        info["encoder_frozen_params"] = sum(p.numel() for p in enc.parameters())
        disk = size_bytes(enc[0].auto_model) + size_bytes(net)

    elif model_name in ("tinybert_ft", "distilbert_ft"):
        from transformers import AutoModel, AutoTokenizer
        name = {"tinybert_ft": "huawei-noah/TinyBERT_General_4L_312D",
                "distilbert_ft": "distilbert-base-uncased"}[model_name]
        tok = AutoTokenizer.from_pretrained(name)
        bert = AutoModel.from_pretrained(name)

        class TB(nn.Module):
            def __init__(self):
                super().__init__()
                self.bert, self.head = bert, Head(bert.config.hidden_size + 13, hidden=64)

            def forward(self, ids, att, m):
                h = self.bert(input_ids=ids, attention_mask=att).last_hidden_state[:, 0]
                return self.head(torch.cat([h, m], -1))

        torch.manual_seed(seed)                              # seeds the head's initial weights too
        model = TB()
        enc = lambda rows: tok(txt(rows), padding=True, truncation=True, max_length=64, return_tensors="pt")
        opt = torch.optim.AdamW(model.parameters(), lr=5e-5, weight_decay=0.01)
        Mtr, Mva = torch.as_tensor(mtr), torch.as_tensor(mva)
        best, best_state, ep_used = 1e9, None, 0

        def pred_rows(rows, m, bs=128):
            out = []
            model.eval()
            with torch.no_grad():
                for i in range(0, len(rows), bs):
                    b = enc(rows[i:i + bs])
                    out.append(model(b["input_ids"], b["attention_mask"], torch.as_tensor(m[i:i + bs])).numpy())
            return np.concatenate(out)
        for ep in range(EPOCHS.get(model_name, 3)):         # epochs capped (CPU budget)
            model.train()
            perm = np.random.default_rng(1000 * seed + ep).permutation(len(tr))
            for i in range(0, len(tr), 32):
                idx = perm[i:i + 32]
                b = enc([tr[j] for j in idx])
                loss = nn.functional.mse_loss(model(b["input_ids"], b["attention_mask"], Mtr[idx]),
                                              torch.as_tensor(ytr[idx]))
                opt.zero_grad()
                loss.backward()
                opt.step()
            mae = float(np.abs(np.clip(pred_rows(va, mva), 1, 5) - yva).mean())
            if mae < best:
                best, best_state, ep_used = mae, {k: v.clone() for k, v in model.state_dict().items()}, ep + 1
        model.load_state_dict(best_state)
        info["epochs"] = ep_used
        info["seed"] = seed
        if save_dir:                                         # checkpoint OUTSIDE git (weights never committed)
            ck = Path(save_dir) / f"{model_name}_s{seed}"
            ck.mkdir(parents=True, exist_ok=True)
            torch.save(model.state_dict(), ck / "model.pt")
            (ck / "meta.json").write_text(json.dumps({"base_model": name, "seed": seed, "epochs": ep_used,
                                                       "val_mae": best, "max_length": 64, "meta_features": 13,
                                                       "data": "SIMULATED"}, indent=2))
            info["checkpoint"] = str(ck)
        predict = pred_rows
        n_params = sum(p.numel() for p in model.parameters())
        disk = size_bytes(model)
    else:
        raise ValueError(model_name)

    train_s = time.perf_counter() - t0
    res = {"model": model_name, "n_params": int(n_params), "disk_mb": round(disk / 1e6, 3),
           "train_s": round(train_s, 1), **info,
           "val": metrics(yva, predict(va, mva)), "test": metrics(yte, predict(te, mte))}
    # latency: one conversation at a time (what F does online), CPU
    lat = []
    for i in range(150):
        r = [te[i]]
        t1 = time.perf_counter()
        predict(r, mte[i:i + 1])
        lat.append(time.perf_counter() - t1)
    res["latency_ms_p50"] = round(1000 * float(np.median(lat[20:])), 3)
    res["latency_ms_p95"] = round(1000 * float(np.percentile(lat[20:], 95)), 3)
    t1 = time.perf_counter()
    predict(te[:512], mte[:512])
    res["throughput_per_s_batch512"] = round(512 / (time.perf_counter() - t1), 1)
    res["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    res["device"] = "cpu"
    res["torch_threads"] = torch.get_num_threads()
    res["data"] = "SIMULATED (agent_f/make_dataset.py)"
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", default="results/agent_f")
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--seed", type=int, default=None, help="tinybert/distilbert: training seed (file gets _s<seed>)")
    ap.add_argument("--save-dir", default=None, help="save the fine-tuned checkpoint here; keep it OUTSIDE git")
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    res = run(a.model, seed=a.seed or 0, save_dir=a.save_dir)
    tag = a.model if a.seed is None else f"{a.model}_s{a.seed}"
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{tag}.json").write_text(json.dumps(res, indent=2))
    print(json.dumps({k: res[k] for k in ("model", "n_params", "disk_mb", "train_s", "latency_ms_p50", "peak_rss_mb")}
                     | {"test_mae": round(res["test"]["mae"], 4), "test_f1": round(res["test"]["f1_macro_3class"], 4)}))


if __name__ == "__main__":
    main()
