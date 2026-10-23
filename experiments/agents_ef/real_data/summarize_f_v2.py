"""Table of Agent F v2 results: python -m real_data.summarize_f_v2 results/f_v2_enfr [more folders...]
Ranks models by VAL MAE (selection) and shows TEST overall / EN / FR (+ PT if present), size, speed, memory."""

import json
import sys
from pathlib import Path

import numpy as np


def fmt(m, s, k):
    return f"{m[k]:.3f} ± {s[k]:.3f}" if s[k] > 0 else f"{m[k]:.3f}"


def main(folders):
    rows = []
    for folder in folders:
        for f in sorted(Path(folder).glob("*.json")):
            d = json.loads(f.read_text())
            if "test_mean" not in d or "all" not in d["test_mean"]:
                continue
            r0 = d["runs"][0]
            val_mae = float(np.mean([r["val"]["all"]["mae"] for r in d["runs"]]))
            rows.append((val_mae, f.stem, folder, d, r0))
    rows.sort()
    langs = sorted({g for _, _, _, d, _ in rows for g in d["test_mean"] if g != "all"})
    head = ["model", "data", "seeds", "VAL MAE", "TEST MAE all", *[f"MAE {g}" for g in langs], "F1-3 all",
            *[f"F1-3 {g}" for g in langs], "Spearman", "params", "disk MB", "ms/text CPU", "peak RAM MB", "train s/seed",
            "test OOV"]
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    for val_mae, name, folder, d, r0 in rows:
        m, s = d["test_mean"], d["test_std"]
        cells = [name, Path(folder).name, str(len(d["runs"])), f"{val_mae:.3f}", fmt(m["all"], s["all"], "mae"),
                 *[fmt(m[g], s[g], "mae") if g in m else "-" for g in langs],
                 f"{m['all']['f1_macro_3class']:.3f}", *[f"{m[g]['f1_macro_3class']:.3f}" if g in m else "-" for g in langs],
                 f"{m['all']['spearman']:.3f}" if not np.isnan(m['all']['spearman']) else "-",
                 f"{r0['n_params'] / 1e6:.1f}M" if r0["n_params"] > 1e5 else str(r0["n_params"]),
                 str(r0.get("disk_mb_fp32", "-")), str(r0.get("latency_ms_p50_cpu_batch1", "-")), str(d["peak_rss_mb"]),
                 f"{np.mean([r['train_s'] for r in d['runs']]):.0f}", f"{r0.get('test_oov_token_rate', 0):.4f}"]
        print("| " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main(sys.argv[1:] or ["results/f_v2_enfr"])
