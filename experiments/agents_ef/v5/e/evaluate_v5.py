"""Evaluate Agent E v5 policies on a manifest -> one per-day KPI CSV per policy (resumable, atomic writes).

    python -m v5.e.evaluate_v5 --split dev --policies rule:mpc:0.5 "floor@3|rl:<run>" ... --workers 2
Splits: dev / val (V4 / V3 manifests, hash-checked), devshift / test5 (v5 manifests, hash-checked).
test5 refuses any policy that is not in the frozen configs/preregistration5.json (no peeking, V4 pattern).
Columns = V4 evaluator columns (same KPI definitions: v3/e/evaluate_v3.KPI, unchanged v3 equal-weight return)
+ decision provenance counts per day (see policies5.py): n_prov_rl, n_prov_rl_rechoice, n_prov_owner, n_prov_rule,
n_prov_shield_default, n_intervened (executed action != the same controller without shield), n_removed (steps where
the shield removed >= 1 valid action), n_flip (activate<->deactivate reversals within 2 steps).
--agree-mpc adds n_agree_mpc = steps where the executed action equals what Fluid MPC (k=0.5) would do in the same
state (E2 "MPC in disguise" check; costs ~2 ms per step, so it is only used on DEV).
"""

import argparse
import csv
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
from v3.e.evaluate_v3 import KPI  # noqa: E402
from v4.e.common import QC  # noqa: E402
from v5.e.common5 import CFG, E5, EnvV5, load_manifest  # noqa: E402

PROV = ["rl", "rl_rechoice", "owner", "rule", "shield_default"]


def fname(spec):
    return spec.replace(":", "__").replace("|", "+").replace("@", "_at_")


def run_day(env, pol, d, mpc=None):
    from env.callcenter_env import A_ACT, A_DEACT, A_FB_OFF, A_FB_ON, A_KEEP, MOVES
    env.pending_shift = d.get("shift")
    obs, info = env.reset(seed=d["seed"], family=d["family"] if "shift" not in d else None)
    pol.reset_day()
    cnt = {k: 0 for k in ["n_keep", "n_move", "n_move_into_c", "n_move_out_c", "n_fb_on", "n_fb_off", "n_act",
                          "n_deact", "n_intervened", "n_removed", "n_flip"] + [f"n_prov_{p}" for p in PROV]}
    done, R, c_alloc, alloc, lat, last_cap = False, 0.0, [], [], [], (None, -99)
    while not done:
        mask = info["action_mask"]
        t1 = time.perf_counter()
        pol.set_full(mask)
        a = int(pol(env, obs, mask))
        lat.append(time.perf_counter() - t1)
        if mpc is not None:
            cnt["n_agree_mpc"] = cnt.get("n_agree_mpc", 0) + int(int(mpc.act(env, obs, mask)) == a)
        cnt[f"n_prov_{pol.prov}"] += 1
        cnt["n_intervened"] += int(bool(getattr(pol, "intervened", False)))
        cnt["n_removed"] += int(bool(getattr(pol, "removed", False)))
        if a == A_KEEP:
            cnt["n_keep"] += 1
        elif 1 <= a <= 12:
            cnt["n_move"] += 1
            i, j = MOVES[a - 1]
            cnt["n_move_into_c"] += int(j == QC)
            cnt["n_move_out_c"] += int(i == QC)
        else:
            cnt[{A_FB_ON: "n_fb_on", A_FB_OFF: "n_fb_off", A_ACT: "n_act", A_DEACT: "n_deact"}[a]] += 1
        if a in (A_ACT, A_DEACT):
            if last_cap[0] is not None and last_cap[0] != a and env.t - last_cap[1] <= 2:
                cnt["n_flip"] += 1
            last_cap = (a, env.t)
        obs, r, done, _, info = env.step(a)
        R += r
        c_alloc.append(int(env.alloc[QC]))
        alloc.append(int(env.alloc.sum()))
    kp = env.kpis()
    row = {"day_id": d["day_id"], "family": d["family"], "seed": d["seed"], "return": R, **{x: kp[x] for x in KPI},
           "c_fail": env.c_fail_day, "c_arrived": int((env.tape["q"] == QC).sum()),
           "c_alloc_mean": float(np.mean(c_alloc)), "alloc_mean": float(np.mean(alloc)), **cnt}
    return row, lat


def check_prereg(split, spec):
    if split != "test5":
        return
    pr = CFG / "preregistration5.json"
    if not pr.exists():
        raise SystemExit("test5 is locked until configs/preregistration5.json exists")
    if spec not in json.loads(pr.read_text())["policies_all"]:
        raise SystemExit(f"{spec} is not in the pre-registered TEST5 comparison set")


def eval_policy(args):
    spec, split, agree = args
    import torch
    torch.set_num_threads(1)
    from v5.e.policies5 import make_policy
    check_prereg(split, spec)
    out_dir = E5 / "results" / f"eval_{split}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / (fname(spec) + ".csv")
    days = load_manifest(split)
    if out.exists() and sum(1 for _ in open(out)) == len(days) + 1:
        return spec, "skip"
    pol = make_policy(spec)
    env = EnvV5()
    mpc = None
    if agree:
        from v3.e.baselines_v3 import FluidMPC
        mpc = FluidMPC(6, 0.5)
    rows, lat_all, t0 = [], [], time.perf_counter()
    for k, d in enumerate(days):
        row, lat = run_day(env, pol, d, mpc)
        rows.append({"policy": spec, **row})
        if k < 5:
            lat_all += lat
    tmp = out.with_suffix(".tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    tmp.replace(out)
    meta = {**pol.meta, "policy": spec, "split": split, "n_days": len(rows), "eval_s": round(time.perf_counter() - t0, 1),
            "decision_ms_p50": round(1e3 * float(np.median(lat_all)), 4),
            "decision_ms_p95": round(1e3 * float(np.percentile(lat_all, 95)), 4)}
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    return spec, f"done {meta['eval_s']}s ret {np.mean([r['return'] for r in rows]):.2f}"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev", choices=["dev", "val", "devshift", "test5"])
    ap.add_argument("--policies", nargs="*", default=[])
    ap.add_argument("--policy-file", default=None)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--agree-mpc", action="store_true")
    a = ap.parse_args(argv)
    specs = list(a.policies)
    if a.policy_file:
        specs += [l.strip() for l in open(a.policy_file) if l.strip() and not l.startswith("#")]
    jobs = [(p, a.split, a.agree_mpc) for p in specs]
    if a.workers > 1:
        with ProcessPoolExecutor(a.workers) as ex:
            for spec, st in ex.map(eval_policy, jobs):
                print(spec, st, flush=True)
    else:
        for j in jobs:
            print(*eval_policy(j), flush=True)


if __name__ == "__main__":
    main()
