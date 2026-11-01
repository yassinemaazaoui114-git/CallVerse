"""Check the REAL photo model on real photos (no fake): adapter from Hugging Face, base model as fallback.

Run:  python -m scripts.vision_check --data <built dataset folder> [--split test] [--limit N] [--backend qlora|base]
The dataset folder is built by benchmarks/vision_qlora/build_dataset.py (photos are not in git). Prints one line
per photo and a summary (accuracy on issue_type, damage recall, valid JSON, latency) as JSON. CPU works (slow).
"""
import argparse
import json
import os
import statistics
import time

from callverse.config import load_config
from callverse.vision import model as vm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--split", default="test")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--backend", choices=["qlora", "base"], default=None, help="force one backend (no fallback)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if a.backend:
        load_config()["vision"]["backends"] = [a.backend]
    rows = [json.loads(l) for l in open(os.path.join(a.data, "dataset.jsonl")) if l.strip()]
    rows = [r for r in rows if r["split"] == a.split][: a.limit or None]
    results, t0 = [], time.time()
    for r in rows:
        out = vm.analyze(open(os.path.join(a.data, r["image"]), "rb").read())
        g, p = r["target"], out["assessment"]
        results.append({"id": r["id"], "gold": g["issue_type"], "pred": p["issue_type"], "valid": out["valid_output"],
                        "gold_damage": g["visible_damage"], "pred_damage": p["visible_damage"],
                        "backend": out["backend"], "latency_s": out["latency_s"], "description": p["description"]})
        print(json.dumps(results[-1]), flush=True)
    dmg = [x for x in results if x["gold_damage"] is True]
    summary = {"split": a.split, "n": len(results), "backends": sorted({x["backend"] for x in results}),
               "accuracy": sum(x["gold"] == x["pred"] for x in results) / len(results),
               "damage_recall": sum(x["pred_damage"] is True for x in dmg) / len(dmg) if dmg else None,
               "valid_json": sum(x["valid"] for x in results) / len(results),
               "latency_median_s": statistics.median(x["latency_s"] for x in results),
               "wall_minutes": round((time.time() - t0) / 60, 1)}
    print(json.dumps(summary, indent=1))
    if a.out:
        json.dump({"summary": summary, "rows": results}, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
