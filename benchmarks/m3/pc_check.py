"""T24 step 2: re-measure the SWITCHED system on this PC, on the VALIDATION sets only.

    python -m benchmarks.m3.pc_check

Unlike embed_run.py (Linux, one model at a time), this runs the system's own code with config.yaml's
settings: reasons.match_reasons (Intake matcher) and kb.search (rule search with the BGE query prompt).
It prints macro-F1, critical errors, needs-LLM rate, top-1 / top-2 / MRR, latency p50 / p95 and peak RAM
(Windows "peak working set"). Writes benchmarks/m3/results/pc_check.json. The locked test files are never opened.
"""

import ctypes
import ctypes.wintypes as wt
import json
import time

from benchmarks.m3 import common
from callverse import companies
from callverse.intake import reasons as intake
from callverse.kb import search

WARMUP = 10


def peak_ram_mb() -> float:
    """Peak resident memory of this process so far (Windows GetProcessMemoryInfo -> PeakWorkingSetSize)."""
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t)]
    counters = Counters()
    counters.cb = ctypes.sizeof(Counters)
    kernel32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
    kernel32.GetCurrentProcess.restype = wt.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(Counters), wt.DWORD]
    psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    return counters.PeakWorkingSetSize / 1e6


def main() -> None:
    t0 = time.perf_counter()
    intake.get_model()
    load_s = time.perf_counter() - t0
    for _ in range(WARMUP):
        intake.embed(["hello, where is my order?"])

    result = {"model": intake.load_config()["intake"]["embedding_model"], "load_s": round(load_s, 1), "intake": {}}
    times = []
    for company in common.COMPANIES:
        cfg = companies.get(company)
        intake.example_vectors(company)                      # build / read the cache before timing
        true, pred = [], []
        for m in common.intake_val(company):
            start = time.perf_counter()
            found = intake.match_reasons(m["text"], company=company)
            times.append(time.perf_counter() - start)
            true.append(m["reason"])
            pred.append(common.main_reason([r["reason"] for r in found["reasons"]], cfg["main_reason_order"]))
        measures = common.intake_measures(true, pred, cfg["reasons"], common.MONEY[company])
        result["intake"][company] = {k: v for k, v in measures.items() if k != "per_reason"}
    result["intake"]["avg_macro_f1"] = round(sum(result["intake"][c]["macro_f1"] for c in common.COMPANIES) / 2, 4)
    result["intake_latency_ms"] = {"p50": common.percentile_ms(times, 50), "p95": common.percentile_ms(times, 95),
                                   "n": len(times)}

    # Rule search: each question in its own company's rules; same path as the system (query prompt, ranking).
    rankings, expected, search_times = [], [], []
    for q in common.rag_val():
        rules = common.rules(q["company"])
        vectors = search.policy_vectors(q["company"])
        if True:
            start = time.perf_counter()
            ranked = search.rank(search.embed_query(q["question"]), vectors, rules, len(rules))
            search_times.append(time.perf_counter() - start)
        if q["expected"]:
            rankings.append([r["id"] for r in ranked])
            expected.append(q["expected"])
    result["search"] = common.rank_measures(rankings, expected)
    result["search_latency_ms"] = {"p50": common.percentile_ms(search_times, 50),
                                   "p95": common.percentile_ms(search_times, 95), "n": len(search_times)}
    result["peak_ram_mb"] = round(peak_ram_mb())

    out = common.RESULTS / "pc_check.json"
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
