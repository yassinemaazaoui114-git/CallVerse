"""Agent F on REAL text with GENUINE satisfaction labels (subset made by real_data/prepare_subset.py --rating ...).

    python -m real_data.eval_f_real --data <subset folder> --model tinybert_ft --seeds 0 1 2 \
        --save-dir <folder OUTSIDE git> --out results/real_f_<name>

Models:
  mean          predict the TRAIN mean score (the floor every model must beat)
  tfidf_ridge   word 1-2 gram + char 3-5 gram TF-IDF -> Ridge (alpha chosen on VAL)
  tinybert_ft   huawei-noah/TinyBERT_General_4L_312D fine-tuned (the model chosen on simulated data; English vocab)
  mminilm_ft    sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 fine-tuned (multilingual, 118M)
Text only: the simulated "queue state" features of the simulated benchmark do not exist in real data.
TRAIN fits, VAL picks epochs / alpha / best seed, TEST is scored once. Outputs: metrics only (no text).
"""

import argparse
import json
import os
import resource
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent_f.benchmark import metrics  # noqa: E402  (same metrics as the simulated benchmark)

HF = {"tinybert_ft": "huawei-noah/TinyBERT_General_4L_312D",
      "mminilm_ft": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"}


def load(folder, split):
    rows = [json.loads(line) for line in open(Path(folder) / f"{split}.jsonl", encoding="utf-8")]
    return [r["text"] for r in rows], np.array([float(r["rating"]) for r in rows], np.float32), rows


def full_metrics(y, p):
    from sklearn.metrics import confusion_matrix, f1_score
    m = metrics(y, p)
    yr, pr = np.round(y).astype(int), np.clip(np.round(p), 1, 5).astype(int)
    m["f1_macro_5class"] = float(f1_score(yr, pr, average="macro", labels=[1, 2, 3, 4, 5]))
    c = lambda v: np.digitize(v, [2.5, 3.5])
    m["confusion_3class"] = confusion_matrix(c(y), c(np.clip(p, 1, 5)), labels=[0, 1, 2]).tolist()
    m["mae_by_true_score"] = {int(k): float(np.abs(y[yr == k] - np.clip(p[yr == k], 1, 5)).mean())
                              for k in range(1, 6) if (yr == k).any()}
    return m


def run_classic(name, Xtr, ytr, Xva, yva, Xte):
    if name == "mean":
        mu = float(ytr.mean())
        return (lambda X: np.full(len(X), mu)), {"n_params": 1}
    from scipy.sparse import hstack
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import Ridge
    w = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True).fit(Xtr)
    ch = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True).fit(Xtr)
    f = lambda X: hstack([w.transform(X), ch.transform(X)]).tocsr()
    best = None
    for alpha in (0.3, 1, 3, 10):
        m = Ridge(alpha=alpha).fit(f(Xtr), ytr)
        mae = float(np.abs(np.clip(m.predict(f(Xva)), 1, 5) - yva).mean())
        if best is None or mae < best[0]:
            best = (mae, alpha, m)
    m = best[2]
    return (lambda X: m.predict(f(X))), {"alpha": best[1], "n_params": int(m.coef_.size + 1)}


class Reg(nn.Module):
    def __init__(self, bert):
        super().__init__()
        self.bert = bert
        h = bert.config.hidden_size
        self.head = nn.Sequential(nn.Dropout(0.1), nn.Linear(h, 64), nn.ReLU(), nn.Linear(64, 1))

    def forward(self, ids, att):
        out = self.bert(input_ids=ids, attention_mask=att).last_hidden_state
        pooled = (out * att.unsqueeze(-1)).sum(1) / att.sum(1, keepdim=True)     # mean pooling
        return self.head(pooled).squeeze(-1) + 3.0


def run_ft(name, seed, Xtr, ytr, Xva, yva, epochs, save_dir):
    from transformers import AutoModel, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(HF[name])
    torch.manual_seed(seed)
    model = Reg(AutoModel.from_pretrained(HF[name]))
    enc = lambda X: tok(list(X), padding=True, truncation=True, max_length=128, return_tensors="pt")
    opt = torch.optim.AdamW(model.parameters(), lr=4e-5, weight_decay=0.01)

    def predict(X, bs=64):
        model.eval()
        out = []
        with torch.no_grad():
            for i in range(0, len(X), bs):
                b = enc(X[i:i + bs])
                out.append(model(b["input_ids"], b["attention_mask"]).numpy())
        return np.concatenate(out)

    best, best_state, curve = 1e9, None, []
    for ep in range(epochs):
        model.train()
        perm = np.random.default_rng(1000 * seed + ep).permutation(len(Xtr))
        for i in range(0, len(Xtr), 16):
            idx = perm[i:i + 16]
            b = enc([Xtr[j] for j in idx])
            loss = nn.functional.mse_loss(model(b["input_ids"], b["attention_mask"]), torch.as_tensor(ytr[idx]))
            opt.zero_grad()
            loss.backward()
            opt.step()
        mae = float(np.abs(np.clip(predict(Xva), 1, 5) - yva).mean())
        curve.append(round(mae, 4))
        if mae < best:
            best, best_state = mae, {k: v.clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    info = {"seed": seed, "epochs_run": epochs, "best_epoch": int(np.argmin(curve)) + 1, "val_mae_curve": curve,
            "n_params": sum(p.numel() for p in model.parameters()), "base_model": HF[name]}
    if save_dir:
        ck = Path(save_dir) / f"{name}_s{seed}"
        ck.mkdir(parents=True, exist_ok=True)
        torch.save(model.state_dict(), ck / "model.pt")
        (ck / "meta.json").write_text(json.dumps({**info, "val_mae": best}, indent=2))
        info["checkpoint"] = str(ck)
    return predict, info


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--model", required=True, choices=["mean", "tfidf_ridge", *HF])
    ap.add_argument("--seeds", type=int, nargs="+", default=[0])
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--save-dir", default=None, help="checkpoints, OUTSIDE git")
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="", help="free text describing the data (goes into the result file)")
    a = ap.parse_args(argv)
    torch.set_num_threads(a.threads)
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    Xtr, ytr, _ = load(a.data, "train")
    Xva, yva, _ = load(a.data, "val")
    Xte, yte, _ = load(a.data, "test")
    runs = []
    for seed in (a.seeds if a.model in HF else [0]):
        t0 = time.perf_counter()
        if a.model in HF:
            predict, info = run_ft(a.model, seed, Xtr, ytr, Xva, yva, a.epochs, a.save_dir)
        else:
            predict, info = run_classic(a.model, Xtr, ytr, Xva, yva, Xte)
        info["train_s"] = round(time.perf_counter() - t0, 1)
        lat = []
        for t in Xte[:60]:
            t1 = time.perf_counter()
            predict([t])
            lat.append(time.perf_counter() - t1)
        info["latency_ms_p50_cpu"] = round(1000 * float(np.median(lat[10:])), 3)
        runs.append({**info, "val": full_metrics(yva, predict(Xva)), "test": full_metrics(yte, predict(Xte))})
    keys = ["mae", "rmse", "exact_acc", "f1_macro_3class", "f1_macro_5class", "spearman"]
    best = min(runs, key=lambda r: r["val"]["mae"])                       # chosen on VAL, never on TEST
    res = {"model": a.model, "data": a.label, "n": {"train": len(Xtr), "val": len(Xva), "test": len(Xte)},
           "test_mean": {k: float(np.mean([r["test"][k] for r in runs])) for k in keys},
           "test_std": {k: float(np.std([r["test"][k] for r in runs])) for k in keys},
           "best_seed_by_val": best.get("seed", 0), "runs": runs,
           "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{a.model}.json").write_text(json.dumps(res, indent=2))
    print(a.model, {k: f"{res['test_mean'][k]:.4f}±{res['test_std'][k]:.4f}" for k in keys})


if __name__ == "__main__":
    main()
