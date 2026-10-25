"""CPU inference cost of saved Agent F checkpoints, each in its OWN process (so peak RAM is per model).

    python v3/f/latency_bench.py --ckpt-root <f_v3/ckpt> --data <f_v3/data_uss> --tags <tag> ... \
        [--int8 <tag> ...] --out v3/f/results/latency_cpu.json
Per model: load time (build + weights + tokenizer), latency batch 1 on 100 TEST dialogues (10 warm-up dropped),
p50 / p95, peak RSS of the process, 1-min load average (if > 2, other jobs shared the 4 cores: upper bound).
Threads = 2. GPU = NOT VERIFIED (no GPU here).
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

H = Path(__file__).resolve().parent
CHILD = r'''
import json, os, resource, sys, time
sys.path.insert(0, sys.argv[1])
import numpy as np, torch
torch.set_num_threads(2)
from f_predictor import SatisfactionPredictor
ck, data, int8 = sys.argv[2], sys.argv[3], sys.argv[4] == "1"
rows = [json.loads(l) for l in open(os.path.join(data, "test.jsonl"), encoding="utf-8")][:110]
t = time.perf_counter(); f = SatisfactionPredictor.load(ck, int8=int8); load_s = time.perf_counter() - t
lat = []
for r in rows:
    t = time.perf_counter(); f.scores([r["text"]]); lat.append(time.perf_counter() - t)
lat = np.array(lat[10:]) * 1000
print(json.dumps({"load_s": round(load_s, 2), "p50": round(float(np.percentile(lat, 50)), 2),
                  "p95": round(float(np.percentile(lat, 95)), 2), "n": len(lat),
                  "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
                  "load_avg_1min": round(os.getloadavg()[0], 2)}))
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt-root", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--tags", nargs="+", required=True)
    ap.add_argument("--int8", nargs="*", default=[])
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    env = {**os.environ, "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2", "TOKENIZERS_PARALLELISM": "false"}
    rows = []
    for tag, int8 in [(t, False) for t in a.tags] + [(t, True) for t in a.int8]:
        res = json.loads((H / "results" / "uss" / f"{tag}.json").read_text())
        ck = Path(a.ckpt_root) / f"{tag}_s{res['best_seed_by_val']}"
        outp = subprocess.run([sys.executable, "-c", CHILD, str(H), str(ck), a.data, "1" if int8 else "0"],
                              capture_output=True, text=True, env=env)
        line = [l for l in outp.stdout.splitlines() if l.startswith("{")]
        if not line:
            print("FAILED", tag, outp.stderr[-500:])
            continue
        m = json.loads(line[-1])
        size = (ck / ("model_int8.pt" if int8 else "model.pt"))
        rows.append({"model": tag + ("_int8" if int8 else ""), "checkpoint": str(ck), **m,
                     "file_mb": round(size.stat().st_size / 1e6, 1) if size.exists() else None})
        print(rows[-1])
    Path(a.out).write_text(json.dumps({"threads": 2, "batch": 1, "device": "cpu", "rows": rows}, indent=1))


if __name__ == "__main__":
    main()
