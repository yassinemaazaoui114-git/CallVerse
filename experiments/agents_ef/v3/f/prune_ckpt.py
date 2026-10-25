"""Keep only the best-by-VAL seed checkpoint of one fine-tuned model (disk budget); delete the other seeds.

    python v3/f/prune_ckpt.py --result v3/f/results/uss/<tag>.json --ckpt <f_v3/ckpt>
Only deletes folders named <tag>_s<seed> inside --ckpt that this benchmark created.
"""
import argparse
import json
import shutil
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--result", required=True)
ap.add_argument("--ckpt", required=True)
a = ap.parse_args()
if not Path(a.result).exists():
    raise SystemExit(f"no result {a.result}: nothing pruned")
res = json.loads(Path(a.result).read_text())
best = res["best_seed_by_val"]
for r in res["runs"]:
    d = Path(a.ckpt) / f"{res['model']}_s{r['seed']}"
    if r["seed"] != best and d.exists() and (d / "meta.json").exists():
        shutil.rmtree(d)
        print("deleted non-best", d)
print("kept", Path(a.ckpt) / f"{res['model']}_s{best}")
