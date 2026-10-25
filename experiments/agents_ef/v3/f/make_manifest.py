"""checkpoints_manifest.json: every checkpoint folder kept in <f_v3>/ckpt with SHA256 values, plus the SELECTED one.

    python v3/f/make_manifest.py --ckpt-root <f_v3/ckpt> --selected <tag>
"""
import argparse
import hashlib
import json
from pathlib import Path

H = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--ckpt-root", required=True)
ap.add_argument("--selected", required=True, help="tag of the selected model (results/uss/<tag>.json)")
ap.add_argument("--reason", default="")
a = ap.parse_args()
items = []
for d in sorted(Path(a.ckpt_root).iterdir()):
    if not (d / "meta.json").exists():
        continue
    meta = json.loads((d / "meta.json").read_text())
    files = {f.name: {"sha256": hashlib.sha256(f.read_bytes()).hexdigest(), "mb": round(f.stat().st_size / 1e6, 1)}
             for f in sorted(d.iterdir()) if f.is_file()}
    items.append({"folder": d.name, "path": str(d), "base_model": meta["base_model"], "revision": meta.get("revision"),
                  "seed": meta["seed"], "val_mae": meta["val_mae"], "layers": meta.get("layers"),
                  "max_length": meta.get("max_length"), "files": files})
res = json.loads((H / "results" / "uss" / f"{a.selected}.json").read_text())
sel = next(i for i in items if i["folder"] == f"{a.selected}_s{res['best_seed_by_val']}")
out = {"note": "checkpoints live OUTSIDE git (sandbox scratchpad, not durable); reproduce with RUN_AND_RESUME_F.md",
       "selected": {**sel, "tag": a.selected, "reason": a.reason}, "checkpoints": items}
(H / "checkpoints_manifest.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out["selected"], indent=1))
