"""Write v3/deliverables/CHECKPOINT_MANIFEST_E.json: one entry per finished v3 Agent E run, with SHA256 hashes.

    python -m v3.e.make_ckpt_manifest
Checkpoints stay outside git (.gitignore); this manifest lets anyone check that a checkpoint is the one reported.
"""

import hashlib
import json
import time
from pathlib import Path

E = Path(__file__).resolve().parent
OUT = E.parent / "deliverables" / "CHECKPOINT_MANIFEST_E.json"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    runs = []
    for d in sorted((E / "runs").glob("*")):
        j = d / "run.json"
        if not j.exists():
            continue
        info = json.loads(j.read_text())
        if info.get("status") != "done":            # only finished runs are listed
            continue
        entry = {k: info.get(k) for k in ("run_id", "algo", "seed", "steps", "hidden", "weights", "reward",
                                          "n_params", "best_val_return", "train_wall_s", "peak_rss_mb",
                                          "code_revision")}
        for name in ("best.pt", "last.pt"):
            p = d / name
            entry[name] = {"bytes": p.stat().st_size, "sha256": sha256(p)} if p.exists() else None
        runs.append(entry)
    OUT.write_text(json.dumps({"created": time.strftime("%Y-%m-%dT%H:%M:%S"), "location": str(E / "runs"),
                               "note": "checkpoints are git-ignored; verify with sha256sum", "runs": runs}, indent=1))
    print(f"{len(runs)} runs -> {OUT}")


if __name__ == "__main__":
    main()
