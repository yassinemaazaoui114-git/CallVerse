"""Cost of the recommended scorer (TF-IDF+Ridge tail-256): load time, batch-1 latency, peak RSS. CPU, 2 threads.

    python -m v4.f.latency_tfidf --fv3 <f_v3> --corpus <m7_corpus>
Output: v4/f/results/latency_tfidf.json
"""
import argparse
import json
import resource
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fv3", required=True)
    ap.add_argument("--corpus", required=True)
    a = ap.parse_args(argv)
    from v3.m7.conversations import dialogue_text, load_conversations
    t0 = time.perf_counter()
    from v4.f.tfidf_predictor import TfidfSatisfactionPredictor
    p = TfidfSatisfactionPredictor.load(Path(a.fv3) / "ckpt/tfidf_ridge_tail256")
    load_s = time.perf_counter() - t0
    sn = [dialogue_text(c) for c in load_conversations(Path(a.corpus) / "dev" / "traces")]
    uss = [json.loads(l)["text"] for l in open(Path(a.fv3) / "data_uss/val.jsonl", encoding="utf-8")][:100]
    out = {"load_s_incl_imports": round(load_s, 3)}
    for name, texts in (("shopnova_dev", sn), ("uss_val_first100", uss)):
        lat = []
        for t in texts:
            t1 = time.perf_counter()
            p.predict([t])
            lat.append(1000 * (time.perf_counter() - t1))
        lat = np.array(lat[5:])
        out[name] = {"n": len(lat), "p50_ms": round(float(np.percentile(lat, 50)), 2),
                     "p95_ms": round(float(np.percentile(lat, 95)), 2)}
    out["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    out["note"] = "CPU shared with other workers (load average printed by the caller)"
    (HERE / "results" / "latency_tfidf.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out))


if __name__ == "__main__":
    main()
