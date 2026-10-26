"""Evaluate Agent E v4 policies on a manifest -> per-day KPI CSV per policy (resumable, atomic).

    python -m v4.e.evaluate_v4 --split dev --policies rule:mpc:0.5 "shield@0.2|rl:<run>" ... --workers 2
    python -m v4.e.evaluate_v4 --split val --policies rl:<run> --trace      # + per-step trajectories (diagnosis)
Splits: dev, test4 (v4 manifests, hash-checked) and val (frozen V3 VAL). The V3 TEST is NOT available here on
purpose. test4 refuses to run unless configs/preregistration.json exists and lists the policy (no peeking).
The return column is the UNCHANGED v3 equal-weight reward (EnvV4 adds bookkeeping only; lam_c = 0 here).
Extra per-day columns explain behaviour: queue-C allocation, action counts, shield activity.
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
from v4.e.common import E4, QC, EnvV4, load_manifest  # noqa: E402
from v3.e.evaluate_v3 import KPI  # noqa: E402

EXTRA = ["c_fail", "c_arrived", "c_alloc_mean", "alloc_mean", "n_keep", "n_move", "n_move_into_c", "n_move_out_c",
         "n_fb_on", "n_fb_off", "n_act", "n_deact", "shield_active", "shield_vetoes", "shield_forced", "rl_overrides"]


def fname(spec):
    return spec.replace(":", "__").replace("|", "+").replace("@", "_at_")


def run_day(env, pol, d, trace=False):
    from env.callcenter_env import A_ACT, A_DEACT, A_FB_OFF, A_FB_ON, A_KEEP, MOVES
    obs, info = env.reset(seed=d["seed"], family=d["family"])
    for k in pol.stats:
        pol.stats[k] = 0
    done, R, steps, cnt, c_alloc, alloc = False, 0.0, [], dict.fromkeys(EXTRA[4:12], 0), [], []
    lat = []
    while not done:
        t1 = time.perf_counter()
        a = int(pol(env, obs, info["action_mask"]))
        lat.append(time.perf_counter() - t1)
        if a == A_KEEP:
            cnt["n_keep"] += 1
        elif 1 <= a <= 12:
            cnt["n_move"] += 1
            i, j = MOVES[a - 1]
            cnt["n_move_into_c"] += int(j == QC)
            cnt["n_move_out_c"] += int(i == QC)
        else:
            cnt[{A_FB_ON: "n_fb_on", A_FB_OFF: "n_fb_off", A_ACT: "n_act", A_DEACT: "n_deact"}[a]] += 1
        pre = dict(t=env.t, a=a, backlog=[len(w) for w in env.queue], fb=int(env.fallback),
                   c_high_wait=int((env.tape["rank"][np.array(env.queue[QC], int)] == 2).sum()) if env.queue[QC] else 0,
                   floor_c=getattr(pol, "last_shield", {}).get("floor_c", -1))
        obs, r, done, _, info = env.step(a)
        R += r
        c_alloc.append(int(env.alloc[QC]))
        alloc.append(int(env.alloc.sum()))
        if trace:
            pre.update(alloc=env.alloc.tolist(), r=round(r, 5), qfail=info["queue_fail"].tolist(),
                       parts={k: round(float(v), 5) for k, v in info["reward_parts"].items()})
            steps.append(pre)
    kp = env.kpis()
    row = {"day_id": d["day_id"], "family": d["family"], "seed": d["seed"], "return": R, **{x: kp[x] for x in KPI},
           "c_fail": env.c_fail_day, "c_arrived": int((env.tape["q"] == QC).sum()),
           "c_alloc_mean": float(np.mean(c_alloc)), "alloc_mean": float(np.mean(alloc)), **cnt,
           "shield_active": pol.stats.get("shield_active", 0), "shield_vetoes": pol.stats.get("shield_vetoes", 0),
           "shield_forced": pol.stats.get("shield_forced", 0), "rl_overrides": pol.stats.get("rl_overrides", 0)}
    return row, steps, lat


def check_prereg(split, spec):
    if split != "test4":
        return
    pr = E4 / "configs" / "preregistration.json"
    if not pr.exists():
        raise SystemExit("test4 is locked until configs/preregistration.json exists")
    allowed = json.loads(pr.read_text())["policies_all"]
    if spec not in allowed:
        raise SystemExit(f"{spec} is not in the pre-registered comparison set")


def eval_policy(args):
    spec, split, trace = args
    import torch
    torch.set_num_threads(1)
    from v4.e.policies import make_policy
    check_prereg(split, spec)
    out_dir = E4 / "results" / f"eval_{split}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / (fname(spec) + ".csv")
    days = load_manifest(split)
    if out.exists() and sum(1 for _ in open(out)) == len(days) + 1 and (not trace or out.with_suffix(".trace.jsonl").exists()):
        return spec, "skip"
    pol = make_policy(spec)
    env = EnvV4()
    rows, lat_all, t0 = [], [], time.perf_counter()
    tr = open(out.with_suffix(".trace.jsonl.tmp"), "w") if trace else None
    for k, d in enumerate(days):
        row, steps, lat = run_day(env, pol, d, trace)
        rows.append({"policy": spec, **row})
        if k < 5:
            lat_all += lat
        if tr:
            tr.write(json.dumps({"day_id": d["day_id"], "family": d["family"], "steps": steps}) + "\n")
    if tr:
        tr.close()
        out.with_suffix(".trace.jsonl.tmp").replace(out.with_suffix(".trace.jsonl"))
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
    ap.add_argument("--split", default="dev", choices=["dev", "test4", "val"])
    ap.add_argument("--policies", nargs="*", default=[])
    ap.add_argument("--policy-file", default=None, help="one policy spec per line (avoids shell quoting of '|')")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--trace", action="store_true")
    a = ap.parse_args(argv)
    specs = list(a.policies)
    if a.policy_file:
        specs += [l.strip() for l in open(a.policy_file) if l.strip() and not l.startswith("#")]
    jobs = [(p, a.split, a.trace) for p in specs]
    if a.workers > 1:
        with ProcessPoolExecutor(a.workers) as ex:
            for spec, st in ex.map(eval_policy, jobs):
                print(spec, st, flush=True)
    else:
        for j in jobs:
            print(*eval_policy(j), flush=True)


if __name__ == "__main__":
    main()
