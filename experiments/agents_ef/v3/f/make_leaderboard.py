"""USS leaderboard from v3/f/results/uss/*.json (+ quant_*.json and latency_*.json when present).

    python v3/f/make_leaderboard.py  ->  v3/f/results/leaderboard_uss.json / .csv  (+ prints markdown tables)
One table per evaluation group (all / lang:en / lang:zh / each sub-dataset). Within a group, rows are ranked by
VAL MAE of that group (selection); TEST mean +- std over seeds is shown. EN-only models appear only in EN groups.
"""
import csv
import json
from pathlib import Path

H = Path(__file__).resolve().parent
R = H / "results"
KEYS = ["mae", "rmse", "qwk", "spearman", "exact_acc", "within1_acc", "f1_macro_3class"]


def best_run(d):
    return min(d["runs"], key=lambda r: r["val"]["all"]["mae"])


def main():
    lat = {}
    for p in R.glob("latency_*.json"):                     # quiet-window re-measurements (latency_bench.py)
        for row in json.loads(p.read_text())["rows"]:
            lat[row["model"]] = row
    rows = []
    for p in sorted((R / "uss").glob("*.json")):
        d = json.loads(p.read_text())
        b = best_run(d)
        for g in d["test_mean"]:
            if g == "all" and d["train_langs"] != "all":       # language-restricted model: only its own groups
                continue
            row = {"group": g, "model": d["model"], "train_langs": d["train_langs"],
                   "train_n": d["n"]["train"], "seeds": len(d["runs"]),
                   "n_params": b["n_params"] if isinstance(b["n_params"], int) else None,
                   "val_mae": d["val_mean"][g]["mae"]}
            for k in KEYS:
                row[f"test_{k}"] = d["test_mean"][g][k]
                row[f"test_{k}_std"] = d["test_std"][g][k]
            row["disk_mb_fp32"] = b.get("disk_mb_fp32")
            row["latency_p50_ms_bench"] = b["latency_ms_cpu_batch1"]["p50"]
            row["latency_p95_ms_bench"] = b["latency_ms_cpu_batch1"]["p95"]
            q = lat.get(d["model"])
            row["latency_p50_ms_quiet"] = q["p50"] if q else None
            row["latency_p95_ms_quiet"] = q["p95"] if q else None
            row["train_s_best_seed"] = b["train_s"]
            row["peak_rss_mb"] = d["peak_rss_mb"]
            row["best_epoch"] = b.get("best_epoch")
            row["max_len"] = b.get("max_len")
            row["layers"] = b.get("layers")
            row["source"] = str(p.relative_to(H))
            rows.append(row)
    rows.sort(key=lambda r: (r["group"], r["val_mae"]))
    for i, r in enumerate(rows):
        r["rank_in_group_by_val"] = 1 + sum(1 for x in rows if x["group"] == r["group"] and x["val_mae"] < r["val_mae"])
    out = {"dataset": "USS dialogue-level satisfaction (mean of annotators' OVERALL rating), split by dialogue 70/15/15",
           "selection": "rank by VAL MAE within each group; TEST scored once; mean +- std over seeds",
           "latency_note": "latency_*_bench measured inside training runs while the CPU was shared (upper bounds); "
                           "latency_*_quiet from latency_bench.py when available",
           "rows": rows}
    (R / "leaderboard_uss.json").write_text(json.dumps(out, indent=1))
    with open(R / "leaderboard_uss.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for g in ["all", "lang:en", "lang:zh"]:
        print(f"\n### {g}\n| # | model | params | train n | VAL MAE | TEST MAE | QWK | Spearman | 3-cl F1 | exact | within1 |")
        print("|---|---|---|---|---|---|---|---|---|---|---|")
        for r in [x for x in rows if x["group"] == g]:
            pm = f"{r['n_params']/1e6:.1f}M" if r["n_params"] and r["n_params"] > 1e5 else (r["n_params"] or "-")
            print(f"| {r['rank_in_group_by_val']} | {r['model']} | {pm} | {r['train_n']} | {r['val_mae']:.3f} | "
                  f"{r['test_mae']:.3f} ± {r['test_mae_std']:.3f} | {r['test_qwk']:.3f} | {r['test_spearman']:.3f} | "
                  f"{r['test_f1_macro_3class']:.3f} | {r['test_exact_acc']:.3f} | {r['test_within1_acc']:.3f} |")


if __name__ == "__main__":
    main()
