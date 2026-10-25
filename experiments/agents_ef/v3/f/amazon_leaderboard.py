"""Amazon EN/FR (product-review stars, AUXILIARY task) leaderboard: re-uses the v2 result files, no retraining.

    python v3/f/amazon_leaderboard.py      -> v3/f/results/leaderboard_amazon.json
Source files: experiments/agents_ef/results/f_v2_enfr/*.json (made by real_data/eval_f_v2.py, 2026-10-23).
Each entry keeps the source path + SHA256 so every number can be traced. Label = stars a customer gave a
PRODUCT, not satisfaction with a support interaction: never merge these numbers with the USS numbers.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "results" / "f_v2_enfr"
rows = []
for p in sorted(SRC.glob("*.json")):
    d = json.loads(p.read_text())
    runs = d["runs"]
    best = min(runs, key=lambda r: r["val"]["all"]["mae"])
    rows.append({
        "model": d["model"], "source_file": str(p.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        "n": d["n"], "seeds": len(runs), "n_params": runs[0]["n_params"],
        "val_mae_mean": sum(r["val"]["all"]["mae"] for r in runs) / len(runs),
        "test_mae_mean": {g: d["test_mean"][g]["mae"] for g in d["test_mean"]},
        "test_mae_std": {g: d["test_std"][g]["mae"] for g in d["test_std"]},
        "test_f1_macro_3class": d["test_mean"]["all"]["f1_macro_3class"],
        "test_spearman": d["test_mean"]["all"].get("spearman"),
        "disk_mb_fp32": best.get("disk_mb_fp32"),
        "latency_ms_p50_cpu_batch1": best.get("latency_ms_p50_cpu_batch1"),
        "peak_rss_mb_train": d.get("peak_rss_mb"),
        "qwk": "NOT AVAILABLE in v2 files (no stored predictions); see amazon_rescore_*.json for the saved checkpoint",
    })
rows.sort(key=lambda r: r["val_mae_mean"])
out = {"dataset": "Amazon Multilingual Reviews EN/FR subset (mteb/amazon_reviews_multi), 1200/400/399",
       "label": "product-review stars 1-5 (AUXILIARY; not support satisfaction)",
       "ranking": "by VAL MAE (selection); TEST shown", "rows": rows}
dst = Path(__file__).resolve().parent / "results" / "leaderboard_amazon.json"
dst.write_text(json.dumps(out, indent=1))
for r in rows:
    print(f"{r['model']:24s} params {r['n_params']:>11,}  TEST MAE {r['test_mae_mean']['all']:.3f}±{r['test_mae_std']['all']:.3f}"
          f"  EN {r['test_mae_mean'].get('en', 0):.3f} FR {r['test_mae_mean'].get('fr', 0):.3f}")
