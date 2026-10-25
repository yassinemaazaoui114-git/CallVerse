"""Post-training dynamic int8 quantization of a saved Agent F checkpoint: size, CPU latency, accuracy before/after.

    python v3/f/quantize_f.py --ckpt <f_v3/ckpt/<tag>_s<seed>> --data <f_v3/data_uss> --out v3/f/results/quant_<tag>.json
              [--save-int8]
Same TEST split as the benchmark (scored once; nothing is chosen on it: quantization has no tuning knob here).
Latency: batch 1, 2 threads, the first 70 TEST dialogues (first 10 = warm-up, dropped). Load time = build + load weights.
"""

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))
from bench_uss import grouped, load  # noqa: E402
from f_predictor import SatisfactionPredictor, build_model, quantize  # noqa: E402


def state_mb(model):
    buf = io.BytesIO()
    torch.save(model.state_dict(), buf)
    return round(buf.tell() / 1e6, 1)


def measure(pred, te):
    lat = []
    for r in te[:70]:
        t = time.perf_counter()
        pred.scores([r["text"]])
        lat.append(time.perf_counter() - t)
    lat = np.array(lat[10:]) * 1000
    load_avg = os.getloadavg()[0]                       # >2 means other jobs shared the 4 CPU cores
    p = pred.scores([r["text"] for r in te])
    return {"latency_ms_cpu_batch1": {"p50": round(float(np.percentile(lat, 50)), 2),
                                      "p95": round(float(np.percentile(lat, 95)), 2),
                                      "load_avg_1min": round(load_avg, 2)},
            "test": grouped(te, p), "test_pred": [round(float(x), 4) for x in p]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--langs", nargs="*", default=None)
    ap.add_argument("--save-int8", action="store_true")
    a = ap.parse_args(argv)
    torch.set_num_threads(a.threads)
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    te = load(a.data, "test", a.langs)
    t = time.perf_counter()
    fp32 = SatisfactionPredictor.load(a.ckpt)
    load_fp32 = time.perf_counter() - t
    res = {"ckpt": a.ckpt, "threads": a.threads, "n_test": len(te),
           "fp32": {"load_s": round(load_fp32, 2), "state_dict_mb": state_mb(fp32.model),
                    "file_mb": round((Path(a.ckpt) / "model.pt").stat().st_size / 1e6, 1), **measure(fp32, te)}}
    model, _ = build_model(a.ckpt)
    q = quantize(model)
    if a.save_int8:
        torch.save(q.state_dict(), Path(a.ckpt) / "model_int8.pt")
    t = time.perf_counter()
    int8 = SatisfactionPredictor.load(a.ckpt, int8=True)
    load_int8 = time.perf_counter() - t
    res["int8_dynamic"] = {"load_s": round(load_int8, 2), "state_dict_mb": state_mb(int8.model),
                           "file_mb": round((Path(a.ckpt) / "model_int8.pt").stat().st_size / 1e6, 1)
                           if (Path(a.ckpt) / "model_int8.pt").exists() else None,
                           "note": "nn.Linear weights int8; embeddings stay fp32", **measure(int8, te)}
    # int8 can shift every prediction by a constant. Re-centre with ONE offset fitted on VAL (never TEST):
    # offset = mean(VAL label - int8 VAL prediction).
    if (Path(a.data) / "val.jsonl").exists():
        va = load(a.data, "val", a.langs)
        off = float(np.mean([r["rating"] for r in va]) - np.mean(int8.scores([r["text"] for r in va])))
        pt = np.clip(np.array(res["int8_dynamic"]["test_pred"]) + off, 1, 5)
        res["int8_dynamic_val_recentred"] = {"offset_from_val": round(off, 4), "test": grouped(te, pt),
                                             "test_pred": [round(float(x), 4) for x in pt]}
    d = np.abs(np.array(res["fp32"]["test_pred"]) - np.array(res["int8_dynamic"]["test_pred"]))
    res["fp32_vs_int8_abs_pred_diff"] = {"mean": float(d.mean()), "max": float(d.max())}
    Path(a.out).write_text(json.dumps(res, indent=1))
    for k in ("fp32", "int8_dynamic", "int8_dynamic_val_recentred"):
        if k in res:
            print(k, res[k].get("state_dict_mb"), "MB", res[k].get("latency_ms_cpu_batch1"), "MAE",
                  round(res[k]["test"]["all"]["mae"], 4))


if __name__ == "__main__":
    main()
