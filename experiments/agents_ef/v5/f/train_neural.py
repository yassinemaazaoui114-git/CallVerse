"""Worker F v5 — F4: fine-tune the vocab-trimmed 6-layer multilingual-e5-small satisfaction regressor (CPU, resumable).

    nice -n 10 $PY -m v5.f.train_neural --name n1_warm_full_mse --init v3 --loss mse --epochs 2 --lr 2e-5

Why this file exists
  V3 trained the e5 model on only 50% of TRAIN for 3 epochs with a constant learning rate, and the best epoch was
  always the last one (VAL curves still falling): the model was budget-limited, not converged. V5 tests a few
  evidence-driven changes, one at a time, selected on VAL only:
    --train-frac 1.0      full TRAIN (V3 used 0.5)
    --init v3             warm start from the selected V3 checkpoint (e5small_trim_ft_L6_frac0.5_len256_s1)
    --init scratch        the documented V3 initialisation (pretrained e5-small, vocab trimmed to TRAIN+VAL tokens,
                          first 6 layers kept, fresh regression head)
    --loss mse|huber|wmse wmse = MSE weighted toward rare (extreme) rounded label classes, inverse-sqrt frequency
    --pool mean|cls       pooling of the encoder output (V3: mean)
    --max-len 256|384     tokens kept from the END of the dialogue (left truncation, as V3)
  Learning-rate schedule: linear warm-up (6% of steps) then linear decay to 0 (V3: constant).
  LoRA is NOT used: the model has 17.4M parameters; full fine-tuning already fits in < 5 GB RAM on CPU and LoRA
  would not make a CPU forward/backward pass faster (the encoder still runs in full) — no real benefit here.

Protocol: TRAIN fits, VAL picks the epoch (best VAL MAE). This script NEVER reads TEST. TEST predictions are
made later by v5/f/score_test.py, only for models in the freeze file.
Resumable: state.pt (model + optimiser + scheduler + position) is written every --save-every steps and at the end of
each epoch; re-running the same command continues where it stopped.
Outputs (outside git, $FV5/runs/<name>/): best/model.pt + meta.json (V3-compatible: loadable with
v3/f/f_predictor.SatisfactionPredictor), state.pt (deleted after the run); v5/f/results/neural/<name>.json.
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

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from v5.f.common import FV3, FV5, RESULTS, load, mae, slope, spearman, to_int, y_of  # noqa: E402

V3_CKPT = FV3 / "ckpt" / "e5small_trim_ft_L6_frac0.5_len256_s1"


class RegCLS(nn.Module):
    """Same head as V3 Reg (real_data/eval_f_v2.py) but pooling = first token ([CLS]/<s>) instead of the mean."""

    def __init__(self, reg):
        super().__init__()
        self.bert, self.head = reg.bert, reg.head
        self.register_buffer("remap", reg.remap)

    def forward(self, ids, att):
        if self.remap.numel():
            ids = self.remap[ids]
        out = self.bert(input_ids=ids, attention_mask=att).last_hidden_state
        return self.head(out[:, 0]).squeeze(-1) + 3.0


def build(a):
    """Return (model, tokenizer, prefix, base_meta)."""
    from transformers import AutoModel, AutoTokenizer
    if a.init == "v3":
        from v3.f.f_predictor import build_model
        model, meta = build_model(V3_CKPT)
        tok = AutoTokenizer.from_pretrained(meta["base_model"], revision=meta["revision"])
        base = {"init": "v3_checkpoint", "init_path": str(V3_CKPT), "base_model": meta["base_model"],
                "revision": meta["revision"], "prefix": meta["prefix"]}
    else:
        from real_data.eval_f_v2 import ENC, PREFIX, REVISION, Reg, trim_model
        from v3.f.bench_uss import build_remap, keep_layers
        rev = REVISION["e5small"]
        tok = AutoTokenizer.from_pretrained(ENC["e5small"], revision=rev)
        pre = PREFIX["e5small"]
        bert = AutoModel.from_pretrained(ENC["e5small"], revision=rev).float()
        rows = load("train") + load("val")                   # unlabelled text only (vocabulary), never TEST
        kept, remap = build_remap(tok, [pre + r["text"] for r in rows])
        bert = keep_layers(trim_model(bert, kept), 6)
        torch.manual_seed(a.seed)
        model = Reg(bert, remap)
        base = {"init": "scratch_v3_recipe", "base_model": ENC["e5small"], "revision": rev, "prefix": pre}
    if a.pool == "cls":
        model = RegCLS(model)
    tok.truncation_side = "left"
    return model, tok, base["prefix"], base


def class_weights(y):
    """Inverse-sqrt frequency of the rounded label class, normalised to mean 1 over TRAIN."""
    yi = to_int(y)
    cnt = {k: (yi == k).sum() for k in range(1, 6)}
    w = np.array([1.0 / np.sqrt(cnt[k]) for k in yi])
    return (w / w.mean()).astype(np.float32), {int(k): int(v) for k, v in cnt.items()}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--init", choices=["v3", "scratch"], default="v3")
    ap.add_argument("--loss", choices=["mse", "huber", "wmse"], default="mse")
    ap.add_argument("--huber-delta", type=float, default=0.5)
    ap.add_argument("--pool", choices=["mean", "cls"], default="mean")
    ap.add_argument("--max-len", type=int, default=256)
    ap.add_argument("--train-frac", type=float, default=1.0)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--warmup", type=float, default=0.06)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--save-every", type=int, default=60, help="steps between resumable state saves")
    ap.add_argument("--max-steps", type=int, default=0, help="smoke test only: stop after N steps")
    a = ap.parse_args(argv)
    torch.set_num_threads(a.threads)
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    run = FV5 / "runs" / a.name
    run.mkdir(parents=True, exist_ok=True)
    out_json = RESULTS / "neural" / f"{a.name}.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    if out_json.exists() and json.loads(out_json.read_text()).get("status") == "completed":
        print("completed already:", out_json)
        return

    tr, va = load("train"), load("val")
    if a.train_frac < 1:
        from v3.f.bench_uss import subsample
        tr = subsample(tr, a.train_frac)
    Xtr, ytr = [r["text"] for r in tr], y_of(tr).astype(np.float32)
    Xva, yva = [r["text"] for r in va], y_of(va)
    w_tr, cls_count = class_weights(ytr)

    model, tok, pre, base = build(a)
    n_params = sum(p.numel() for p in model.parameters())
    steps_per_epoch = (len(Xtr) + a.batch - 1) // a.batch
    total = steps_per_epoch * a.epochs
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=0.01)
    warm = max(1, int(a.warmup * total))
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: (s + 1) / warm if s < warm else max(0.0, (total - s) / max(1, total - warm)))
    state = {"epoch": 0, "step_in_epoch": 0, "best": 1e9, "curve": [], "epoch_s": [], "val_preds": {},
             "losses": []}
    sp = run / "state.pt"
    from v5.registry.registry import finish, register
    if not sp.exists() and not a.max_steps:
        register("F", f"F4_{a.name}", config=dict(vars(a)), seed=a.seed,
                 dataset={"name": "USS v3 splits", "train": len(tr), "val": len(va)},
                 note="F4 e5-small trimmed L6 fine-tune; VAL-only selection; TEST not read")
    if sp.exists():                                          # resume
        ck = torch.load(sp, map_location="cpu", weights_only=False)
        model.load_state_dict(ck["model"])
        opt.load_state_dict(ck["opt"])
        sched.load_state_dict(ck["sched"])
        state = ck["state"]
        print(f"resumed at epoch {state['epoch']} step {state['step_in_epoch']}", flush=True)

    enc = lambda X: tok([pre + x for x in X], padding=True, truncation=True, max_length=a.max_len,
                        return_tensors="pt")

    def predict(X, bs=32):
        model.eval()
        out = []
        with torch.no_grad():
            for i in range(0, len(X), bs):
                b = enc(X[i:i + bs])
                out.append(model(b["input_ids"], b["attention_mask"]).float().numpy())
        return np.concatenate(out)

    def save_state():
        tmp = run / "state.pt.tmp"
        torch.save({"model": model.state_dict(), "opt": opt.state_dict(), "sched": sched.state_dict(),
                    "state": state}, tmp)
        os.replace(tmp, sp)

    def loss_fn(pred, y, w):
        if a.loss == "huber":
            return nn.functional.huber_loss(pred, y, delta=a.huber_delta)
        se = (pred - y) ** 2
        return (se * w).mean() if a.loss == "wmse" else se.mean()

    t_start = time.perf_counter()
    while state["epoch"] < a.epochs:
        ep = state["epoch"]
        t0 = time.perf_counter() - state.get("epoch_elapsed", 0.0)
        perm = np.random.default_rng(1000 * a.seed + ep).permutation(len(Xtr))
        model.train()
        for s in range(state["step_in_epoch"], steps_per_epoch):
            idx = perm[s * a.batch:(s + 1) * a.batch]
            b = enc([Xtr[j] for j in idx])
            pred = model(b["input_ids"], b["attention_mask"])
            loss = loss_fn(pred.float(), torch.as_tensor(ytr[idx]), torch.as_tensor(w_tr[idx]))
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            state["losses"].append(round(float(loss.detach()), 4))
            state["step_in_epoch"] = s + 1
            if (s + 1) % 20 == 0:
                print(f"  ep {ep + 1} step {s + 1}/{steps_per_epoch} loss {np.mean(state['losses'][-20:]):.4f} "
                      f"lr {sched.get_last_lr()[0]:.2e} {time.perf_counter() - t0:.0f}s", flush=True)
            if a.max_steps and s + 1 >= a.max_steps:
                print("max-steps reached (smoke test)")
                return
            if (s + 1) % a.save_every == 0:
                state["epoch_elapsed"] = time.perf_counter() - t0
                save_state()
        pv = predict(Xva)
        m = mae(yva, pv)
        state["curve"].append(round(m, 5))
        state["epoch_s"].append(round(time.perf_counter() - t0, 1))
        state["val_preds"][str(ep + 1)] = [round(float(x), 4) for x in pv]
        print(f"{a.name} epoch {ep + 1}: VAL MAE {m:.4f} Spearman {spearman(yva, pv):.4f} "
              f"({state['epoch_s'][-1]} s)", flush=True)
        if m < state["best"]:
            state["best"] = m
            state["best_epoch"] = ep + 1
            bd = run / "best"
            bd.mkdir(exist_ok=True)
            sd = model.state_dict()
            if a.pool == "cls":
                sd = {k: v for k, v in sd.items()}
            torch.save(sd, bd / "model.pt")
            meta = {"seed": a.seed, "best_epoch": ep + 1, "val_mae": m, "base_model": base["base_model"],
                    "revision": base["revision"], "layers": 6, "max_length": a.max_len, "prefix": pre,
                    "truncation_side": "left", "pool": a.pool, "loss": a.loss, "init": base["init"],
                    "n_params": n_params, "trained_on": f"USS TRAIN x{a.train_frac:g} ({len(tr)} dialogues)",
                    "label_type": "human_annotation (third-party annotators, mean of 3-7)"}
            (bd / "meta.json").write_text(json.dumps(meta, indent=2))
        state["epoch"] = ep + 1
        state["step_in_epoch"] = 0
        state["epoch_elapsed"] = 0.0
        save_state()

    bestp = np.array(state["val_preds"][str(state["best_epoch"])])
    vrows_lang = np.array([r["lang"] for r in va])
    res = {"name": a.name, "status": "completed", "args": vars(a), "base": base, "n_params": n_params,
           "n_train": len(tr), "train_class_counts": cls_count, "val_mae_curve": state["curve"],
           "epoch_s": state["epoch_s"], "best_epoch": state["best_epoch"], "val_mae": state["best"],
           "val_mae_en": mae(yva[vrows_lang == "en"], bestp[vrows_lang == "en"]),
           "val_mae_zh": mae(yva[vrows_lang == "zh"], bestp[vrows_lang == "zh"]),
           "val_spearman": spearman(yva, bestp), "val_slope": slope(yva, bestp),
           "val_pred_std": float(np.std(np.clip(bestp, 1, 5))), "val_ids": [r["id"] for r in va],
           "val_pred_best": bestp.tolist(), "val_preds_by_epoch": state["val_preds"],
           "train_loss_every_step": state["losses"], "checkpoint": str(run / "best"),
           "wall_s_this_process": round(time.perf_counter() - t_start, 1)}
    out_json.write_text(json.dumps(res, indent=1))
    finish(f"F4_{a.name}", "completed", results={"val_mae": state["best"], "best_epoch": state["best_epoch"],
                                                  "val_mae_curve": state["curve"]},
           checkpoint=str(run / "best" / "model.pt"), n_params=n_params, duration_s=float(sum(state["epoch_s"])))
    print("done", a.name, "best epoch", state["best_epoch"], "VAL MAE", round(state["best"], 4))


if __name__ == "__main__":
    main()
