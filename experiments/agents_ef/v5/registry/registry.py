"""V5 experiment registry: one JSON line per experiment (append-only, resumable). Shared by Workers E, F and D.

    from v5.registry.registry import register, finish
    rid = register("E", "dueling_dqn_per_s0", config={...}, seed=0, dataset={"name": "...", "sha256": "..."})
    ... run ...
    finish(rid, status="completed", results={...}, checkpoint="path/best.pt", n_params=8146)
Statuses: running | completed | failed | deferred | stopped. A later line for the same id supersedes earlier ones
(read with latest()). Never edit old lines: append.
"""

import hashlib
import json
import os
import platform
import subprocess
import time
from pathlib import Path

REG = Path(__file__).resolve().parent / "experiments.jsonl"
ROOT = Path(__file__).resolve().parents[2]


def _git_sha() -> str:
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()


def _hw() -> str:
    return f"{platform.platform()} | {os.cpu_count()} CPU | no GPU"


def sha256(path) -> str | None:
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def _append(rec: dict):
    REG.parent.mkdir(parents=True, exist_ok=True)
    with open(REG, "a") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def register(worker: str, exp_id: str, config: dict, seed=None, dataset: dict | None = None, note: str = "") -> str:
    _append({"id": exp_id, "worker": worker, "status": "running", "config": config, "seed": seed,
             "dataset": dataset, "code_sha": _git_sha(), "hardware": _hw(),
             "start_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "note": note})
    return exp_id


def finish(exp_id: str, status: str, results: dict | None = None, checkpoint: str | None = None,
           n_params: int | None = None, reason: str = "", duration_s: float | None = None):
    _append({"id": exp_id, "status": status, "results": results, "checkpoint": checkpoint,
             "checkpoint_sha256": sha256(checkpoint) if checkpoint else None, "n_params": n_params,
             "end_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "duration_s": duration_s,
             "reason": reason})


def latest() -> dict:
    out = {}
    if REG.exists():
        for line in open(REG):
            r = json.loads(line)
            out.setdefault(r["id"], {}).update({k: v for k, v in r.items() if v is not None})
    return out
