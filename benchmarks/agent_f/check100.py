"""F1b: check Semah's agent F model file once, on 100 real Amazon TEST reviews.

Run ONCE: python -m benchmarks.agent_f.check100  -> results/check100_ids.json + results/check100.json
No training, no tuning: it only loads models/agent_f/satisfaction.pkl and scores.
Sample rule = the project's own loader: load("test", 100, seed=2026), i.e. a plain seeded random
draw (not stratified). The test split itself is balanced (1000 reviews per star).
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter

import numpy as np

from benchmarks.agent_f.benchmark import metrics
from benchmarks.agent_f.common import DATA, ROOT, load
from callverse.quality.satisfaction import TEXT_MODEL, predict_satisfaction

SEED, N = 2026, 100
TRAIN_MEAN = 3.0  # not stored in his JSON; the train split is balanced (his mean baseline gives MAE 1.2005 = mean ~3.0)


def rss_mb() -> float:
    """Memory used by this process (RSS = Windows 'working set'), in MB. No extra library needed."""
    if os.name != "nt":  # Linux / Mac: peak RSS from the standard library
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e3
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):  # PROCESS_MEMORY_COUNTERS from the Windows API
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                           "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                           "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
    pmc = PMC(); pmc.cb = ctypes.sizeof(PMC)
    k32 = ctypes.WinDLL("kernel32"); k32.GetCurrentProcess.restype = wintypes.HANDLE
    get_info = ctypes.WinDLL("psapi").GetProcessMemoryInfo
    get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    get_info(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return pmc.WorkingSetSize / 1e6


def main():
    res = ROOT / "benchmarks/agent_f/results"
    texts, stars = load("test", N, seed=SEED)
    # Ids only (no texts): the review_id of each sampled row, in order.
    rows = [json.loads(l) for l in (DATA / "test.jsonl").open(encoding="utf-8")]
    by_text = {r["text"]: r for r in rows}
    ids = [by_text[t].get("id", by_text[t].get("review_id")) for t in texts]
    (res / "check100_ids.json").write_text(json.dumps({"split": "test", "seed": SEED, "n": N, "ids": ids}, indent=1))

    rss_before = rss_mb()
    s = time.perf_counter()
    predict_satisfaction({"messages": [{"role": "user", "text": "warm-up"}]}, stacker=False)  # loads the pickle
    load_s = time.perf_counter() - s
    rss_after = rss_mb()

    preds, ms = [], []
    for t in texts:  # one record per review, same shape the RL layer sends (user message only)
        s = time.perf_counter()
        preds.append(predict_satisfaction({"messages": [{"role": "user", "text": t}]}, stacker=False)["score"])
        ms.append((time.perf_counter() - s) * 1000)

    out = {
        "split": "SetFit/amazon_reviews_multi_en test (real, held out)", "seed": SEED, "n": N,
        "star_counts": dict(sorted(Counter(stars).items())),
        "model_file": {"path": "models/agent_f/satisfaction.pkl", "bytes": TEXT_MODEL.stat().st_size},
        "test_file_bytes": (DATA / "test.jsonl").stat().st_size,
        "agent_f": metrics(stars, preds),
        "baseline_train_mean": {"value": TRAIN_MEAN, **metrics(stars, [TRAIN_MEAN] * N)},
        "baseline_delay_only": "not possible: Amazon reviews have no delivery delay",
        "his_n5000_expected": {"mae": 0.6054, "within_1": 0.9218, "spearman": 0.8016, "mae_raw": 0.6439},
        "speed": {"load_s": round(load_s, 2), "rss_before_mb": round(rss_before, 1),
                  "rss_after_load_mb": round(rss_after, 1),
                  "ms_mean": round(float(np.mean(ms)), 3), "ms_p95": round(float(np.percentile(ms, 95)), 3),
                  "limit_ms": 200},
    }
    (res / "check100.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
