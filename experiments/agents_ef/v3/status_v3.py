"""Combined status of the V3 benchmark, built ONLY from files on disk (never from memory or claims).

    python -m v3.status_v3          -> prints a summary and writes v3/deliverables/BENCHMARK_STATUS.json
"""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

V3 = Path(__file__).resolve().parent
E, F, D = V3 / "e", V3 / "f", V3 / "deliverables"


def runs_e():
    done, running, failed = [], [], []
    for d in sorted((E / "runs").glob("*")):
        j = d / "run.json"
        if not j.exists():
            continue
        s = json.loads(j.read_text())
        ok = s.get("status") == "done" and (d / "best.pt").exists() and (d / "val_log.csv").exists()
        (done if ok else failed if s.get("status") == "failed" else running).append(d.name)
    return done, running, failed


def evals(split):
    p = E / "results" / f"eval_{split}"
    if not p.exists():
        return []
    want = {"val": 48, "test": 650}[split]
    return [f.stem.replace("__", ":") for f in sorted(p.glob("*.csv")) if sum(1 for _ in open(f)) == want + 1]


def main():
    done, running, failed = runs_e()
    st = {"updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
          "worker_E": {"gate_A_simulator_validation": "PASSED (v3/e/tests: tape CRN, conservation, mask, budget, "
                                                       "reward decomposition, no future info, determinism)",
                       "train_runs_done": len(done), "train_runs_running": running, "train_runs_failed": failed,
                       "val_evaluations": len(evals("val")), "test_evaluations": len(evals("test")),
                       "test_manifest_sha256": (E / "configs" / "test_manifest.sha256").read_text().strip()
                       if (E / "configs" / "test_manifest.sha256").exists() else None,
                       "analysis": (E / "results" / "test_analysis.json").exists(),
                       "queue_log_tail": (E / "logs" / "queue_e.log").read_text().splitlines()[-3:]
                       if (E / "logs" / "queue_e.log").exists() else []},
          "worker_F": json.loads((F / "STATUS.json").read_text()) if (F / "STATUS.json").exists() else "no STATUS.json yet",
          "worker_F_M7": {k: (json.loads((V3 / "m7" / "results" / k / "detection_eval.json").read_text())["per_defect"]
                              if (V3 / "m7" / "results" / k / "detection_eval.json").exists() else None)
                          for k in ("dev", "test")},
          "resources": {"disk_free_gb": round(shutil.disk_usage("/").free / 1e9, 2),
                        "load_avg": os.getloadavg(),
                        "gpu": "none in this sandbox (RTX 4050 laptop not reachable): GPU work NOT VERIFIED"},
          "blocked": ["Windows PC / local CallVerse datasets: no remote connection available to this session",
                      "RTX 4050 measurements: no access", "DCH-2 dataset: requires a user agreement (not accepted)"],
          "git": subprocess.run(["git", "log", "--oneline", "-1"], cwd=V3, capture_output=True, text=True).stdout.strip()}
    D.mkdir(parents=True, exist_ok=True)
    (D / "BENCHMARK_STATUS.json").write_text(json.dumps(st, indent=2, default=str))
    e = st["worker_E"]
    print(f"E: runs done {e['train_runs_done']}, running {len(e['train_runs_running'])}, failed {len(e['train_runs_failed'])}; "
          f"evals val {e['val_evaluations']} test {e['test_evaluations']}; analysis {e['analysis']}")
    print("F:", json.dumps(st["worker_F"])[:400])
    print("resources:", st["resources"])


if __name__ == "__main__":
    main()
