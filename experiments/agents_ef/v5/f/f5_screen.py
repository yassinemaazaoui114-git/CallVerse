"""Worker F v5 — F5: cheap feasibility screen for ONE extra tiny multilingual encoder (VAL only).

    $PY -m v5.f.f5_screen extract --enc mminilm      # frozen mean-pooled embeddings (last 256 tokens)
    $PY -m v5.f.f5_screen probe                      # Ridge probe on frozen embeddings, VAL MAE per encoder

Why a screen and not a fine-tune
  Fine-tuning a 12-layer encoder on this shared CPU costs ~2x the 6-layer e5 (≈ 1.5 h / epoch under load); the
  budget allows it only if there is evidence it could beat e5-small. The cheapest honest evidence is a linear probe:
  frozen mean-pooled embeddings of the PRETRAINED encoders (same truncation, same splits) + Ridge with alpha on VAL.
  Decision rule (fixed before running): fine-tune the candidate only if its probe VAL MAE is at least 0.005 lower
  than e5-small's probe AND >= 2 h of budget remain; otherwise record it as SCREENED OUT.
Candidate: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (cached). It has 117.7M parameters, but
  ~96M of them are the 250k-token embedding table: vocabulary trimming to the TRAIN+VAL tokens (as for e5) leaves
  ~21M (12 x 384 layers), i.e. inside the "tiny" budget; the full model is over 100M and would not be deployed.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from v5.f.common import FV5, RESULTS, load, mae, slope, spearman, write_json, y_of  # noqa: E402

ENCS = {"e5small": ("intfloat/multilingual-e5-small", "query: ", "614241f622f53c4eeff9890bdc4f31cfecc418b3"),
        "mminilm": ("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "", None)}


def emb_path(enc):
    return FV5 / ("emb_e5_256.npz" if enc == "e5small" else f"emb_{enc}_256.npz")


def extract(enc):
    import torch
    from transformers import AutoModel, AutoTokenizer
    torch.set_num_threads(1)
    name, pre, rev = ENCS[enc]
    tok = AutoTokenizer.from_pretrained(name, revision=rev)
    tok.truncation_side = "left"
    m = AutoModel.from_pretrained(name, revision=rev).float().eval()
    n_params = sum(p.numel() for p in m.parameters())
    n_emb = m.get_input_embeddings().weight.numel()
    out = {}
    for s in ("train", "val", "test"):
        X = [pre + r["text"] for r in load(s)]
        embs = []
        with torch.no_grad():
            for i in range(0, len(X), 32):
                b = tok(X[i:i + 32], padding=True, truncation=True, max_length=256, return_tensors="pt")
                h = m(**b).last_hidden_state
                a = b["attention_mask"].unsqueeze(-1)
                embs.append(((h * a).sum(1) / a.sum(1)).numpy())
        out[s] = np.concatenate(embs).astype(np.float32)
        print(enc, s, out[s].shape, flush=True)
    np.savez_compressed(emb_path(enc), **out, n_params=n_params, n_emb_params=n_emb)


def probe():
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler
    tr, va = load("train"), load("val")
    ytr, yva = y_of(tr), y_of(va)
    lg = np.array([r["lang"] for r in va])
    res = {"rule": "fine-tune only if probe VAL MAE <= e5small probe - 0.005 and >= 2 h budget left"}
    for enc in ENCS:
        p = emb_path(enc)
        if not p.exists():
            res[enc] = "NOT RUN (no embeddings)"
            continue
        E = np.load(p)
        sc = StandardScaler().fit(E["train"])
        Ftr, Fva = sc.transform(E["train"]), sc.transform(E["val"])
        grid = {a: mae(yva, Ridge(alpha=a).fit(Ftr, ytr).predict(Fva)) for a in (10, 100, 1000, 3000)}
        a = min(grid, key=grid.get)
        pv = Ridge(alpha=a).fit(Ftr, ytr).predict(Fva)
        res[enc] = {"alpha": a, "val_mae": round(mae(yva, pv), 4), "val_mae_en": round(mae(yva[lg == "en"], pv[lg == "en"]), 4),
                    "val_mae_zh": round(mae(yva[lg == "zh"], pv[lg == "zh"]), 4),
                    "val_spearman": round(spearman(yva, np.clip(pv, 1, 5)), 4), "val_slope": round(slope(yva, pv), 4),
                    "n_params_full": int(E["n_params"]) if "n_params" in E else None,
                    "n_params_embedding_table": int(E["n_emb_params"]) if "n_emb_params" in E else None}
    if isinstance(res.get("e5small"), dict) and isinstance(res.get("mminilm"), dict):
        gain = res["e5small"]["val_mae"] - res["mminilm"]["val_mae"]
        res["mminilm_gain_vs_e5_probe"] = round(gain, 4)
        res["decision"] = "FINE-TUNE CANDIDATE" if gain >= 0.005 else "SCREENED OUT (no probe advantage over e5-small)"
    write_json(RESULTS / "f5_screen.json", res)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["extract", "probe"])
    ap.add_argument("--enc", default="mminilm")
    a = ap.parse_args()
    extract(a.enc) if a.cmd == "extract" else probe()
