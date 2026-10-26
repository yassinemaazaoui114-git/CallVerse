"""Worker F v5 — score ONE frozen candidate on TEST, once, and measure its cost (run each model in its own process).

    $PY -m v5.f.score_test --name <candidate>     -> v5/f/results/test/<candidate>.json

Guard: refuses unless results/FREEZE_candidates.json exists and lists the candidate (common.test_scoring_allowed).
Refuses a second run (the TEST file exists) — TEST is scored once per model.
Also measured (same machine state for all candidates, 2 threads, CPU shared with Worker E):
  load_s        time to load the model (imports included)
  latency       batch-1 p50 / p95 over 60 VAL dialogues (10 warm-up calls not counted) — VAL text, so cost is
                measured without touching TEST more than the single scoring pass
  peak_rss_mb   peak resident memory of this process (ru_maxrss)
  n_params      model parameters (Ridge: coefficients + intercept)
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
from v5.f.common import FREEZE, FV3, RESULTS, load, test_scoring_allowed, write_json  # noqa: E402


def loader(spec):
    """spec from the freeze file: {"kind": "ridge_v3"|"ridge_v5"|"neural", "path": ...}."""
    kind, path = spec["kind"], spec["path"]
    if kind == "ridge_v3":
        from v4.f.tfidf_predictor import TfidfSatisfactionPredictor
        m = TfidfSatisfactionPredictor.load(path)
        return (lambda rows: m.scores([r["text"] for r in rows], [r["lang"] for r in rows])), \
            int(m.ridge.coef_.size + 1), m.meta["sha256"]
    if kind == "ridge_v5":
        from v5.f.ridge_v5 import RidgeV5Predictor
        m = RidgeV5Predictor.load(path)
        return (lambda rows: m.scores([r["text"] for r in rows], [r["lang"] for r in rows])), \
            int(m.ridge.coef_.size + 1), m.meta["sha256"]
    if kind == "neural":
        import hashlib
        import torch
        torch.set_num_threads(2)
        from v3.f.f_predictor import SatisfactionPredictor
        m = SatisfactionPredictor.load(path)
        sha = hashlib.sha256((Path(path) / "model.pt").read_bytes()).hexdigest()
        return (lambda rows: m.scores([r["text"] for r in rows])), int(sum(p.numel() for p in m.model.parameters())), sha
    raise ValueError(kind)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    a = ap.parse_args(argv)
    test_scoring_allowed(a.name)
    out = RESULTS / "test" / f"{a.name}.json"
    if out.exists():
        raise SystemExit(f"TEST already scored for {a.name}: {out}")
    spec = json.loads(FREEZE.read_text())["candidates"][a.name]
    t0 = time.perf_counter()
    predict, n_params, sha = loader(spec)
    load_s = time.perf_counter() - t0
    va = load("val")
    lat = []
    for r in va[:70]:
        t1 = time.perf_counter()
        predict([r])
        lat.append(time.perf_counter() - t1)
    lat = np.array(lat[10:]) * 1000
    te = load("test")
    t2 = time.perf_counter()
    pt = np.asarray(predict(te), float)
    batch_s = time.perf_counter() - t2
    res = {"name": a.name, "spec": spec, "sha256": sha, "n_params": n_params, "load_s": round(load_s, 2),
           "latency_ms_batch1_val": {"p50": round(float(np.percentile(lat, 50)), 2),
                                     "p95": round(float(np.percentile(lat, 95)), 2)},
           "test_batch_s": round(batch_s, 1), "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
           "test_ids": [r["id"] for r in te], "test_pred": [round(float(x), 5) for x in pt],
           "load_average_1_5_15": [round(x, 2) for x in __import__("os").getloadavg()],
           "scored_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    write_json(out, res)
    from v5.registry.registry import finish, register
    register("F", f"F7_test_{a.name}", config=spec, dataset={"name": "USS v3 TEST", "n": len(te)},
             note="single TEST scoring after freeze")
    finish(f"F7_test_{a.name}", "completed",
           results={"test_mae": float(np.abs(np.clip(pt, 1, 5) - np.array([r["rating"] for r in te])).mean())},
           n_params=n_params)
    print(a.name, "TEST MAE", round(float(np.abs(np.clip(pt, 1, 5) - np.array([r["rating"] for r in te])).mean()), 4),
          {k: res[k] for k in ("load_s", "latency_ms_batch1_val", "peak_rss_mb", "n_params")})


if __name__ == "__main__":
    main()
