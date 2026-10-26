"""Offline demo of the Agent E v4 adapter (no network, no LLM, CPU only).

    python -m v4.e.demo_adapter [--spec "floor@3|guarded:<run_id>"] [--family severe_overload] [--seed 424242]
It plays one simulated day: at every 5-minute step it builds the SNAPSHOT the prototype would send
(snapshot_from_env), asks the adapter for a PROPOSAL, prints a few of them, lets a minimal 'Coordinator' apply the
proposal to the simulator (the adapter itself never acts), and prints the day's KPIs and the audit summary.
Default = configs/recommended.json (the recommended v4 candidate); or --spec / --run [--shield t].
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from v4.e.adapter import AgentEAdapter, snapshot_from_env  # noqa: E402
from v4.e.common import EnvV4  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", default=None, help="policy spec, e.g. 'floor@3|guarded:<run>' (default: recommended.json)")
    ap.add_argument("--run", default=None)
    ap.add_argument("--shield", default="none")
    ap.add_argument("--family", default="severe_overload")
    ap.add_argument("--seed", type=int, default=424242)
    a = ap.parse_args()
    shield = None if a.shield == "none" else float(a.shield)
    ad = AgentEAdapter.load(a.run, shield_target=shield, spec=a.spec)
    env = EnvV4()
    env.reset(seed=a.seed, family=a.family)
    done, vetoes, lat, shown = False, 0, [], 0
    while not done:
        snap = snapshot_from_env(env)
        p = ad.propose(snap)
        lat.append(p["audit"]["latency_ms"])
        vetoes += p["safety_veto"]
        if env.t in (0, 30, 60) or (p["safety_veto"] and shown < 3):
            shown += p["safety_veto"]
            print(json.dumps({k: p[k] for k in ("action_id", "action", "decided_by", "rl_preference", "safety_veto",
                                                "veto_reason", "fallback_reason", "urgent_floor_c")}
                             | {"t_step": snap["t_step"], "alloc": [q["alloc"] for q in snap["queues"]],
                                "waiting": [len(q["waiting"]) for q in snap["queues"]]}))
        _, _, done, _, _ = env.step(p["action_id"])                # the 'Coordinator' executes the proposal
    k = env.kpis()
    print("day KPIs:", {x: round(k[x], 2) if isinstance(k[x], float) else k[x] for x in
                        ("family", "sla_pct", "sla_high_pct", "sla_queue_c_pct", "lost_pct", "cost", "high_on_fallback",
                         "invalid_proposals", "budget_ok")})
    print("audit:", {"run_id": p["audit"]["run_id"], "model_sha256": (p["audit"]["model_sha256"] or "")[:16],
                     "n_params": p["audit"]["n_params"], "safety_vetoes": vetoes,
                     "latency_ms_p50": round(float(np.median(lat)), 3), "latency_ms_p95": round(float(np.percentile(lat, 95)), 3)})


if __name__ == "__main__":
    main()
