"""Agent E v4 analysis: leaderboards and paired comparisons on DEV (exploratory) or TEST4 (confirmatory).

    python -m v4.e.analyze_v4 dev  [--groups g1 g2 ...]      exploratory: prints board + comparisons vs MPC
    python -m v4.e.analyze_v4 test4                          confirmatory: exactly the pre-registered analysis
Statistics reuse the frozen V3 helpers (v3/e/analyze_v3.py): matrix(), boot_mean(), boot_diff() = two-level paired
bootstrap (resample seeds within each group, the SAME resampled days for both groups), holm().
Groups: a learned policy's seeds are pooled ("_s<k>" removed from the spec); rules are single-member groups.
"""

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
from v3.e.analyze_v3 import boot_diff, boot_mean, holm, matrix  # noqa: E402
from v4.e.common import E4  # noqa: E402

KEYS = ["return", "sla_pct", "sla_high_pct", "sla_queue_c_pct", "lost_pct", "cost", "p95_wait_min", "fallback_share",
        "high_on_fallback", "invalid_proposals", "c_alloc_mean", "shield_vetoes"]


def load_rows(split):
    out = {}
    for f in sorted((E4 / "results" / f"eval_{split}").glob("*.csv")):
        rows = list(csv.DictReader(open(f)))
        if not rows:
            continue
        for r in rows:
            for k, v in r.items():
                if k not in ("policy", "day_id", "family"):
                    r[k] = float(v) if v not in ("True", "False") else float(v == "True")
        out[rows[0]["policy"]] = rows
    return out


def group_of(spec):
    return spec if spec.startswith("rule:") else re.sub(r"_s\d+(?=$|_)", "", spec)


def groups(rows):
    g = defaultdict(list)
    for s in rows:
        g[group_of(s)].append(s)
    return {k: sorted(v) for k, v in g.items()}


def board(rows, gmap, days, n_boot=1000):
    out = {}
    for name, specs in gmap.items():
        ent = {"n_seeds": len(specs)}
        for m in KEYS:
            if m not in rows[specs[0]][0]:
                continue
            M = matrix(rows, specs, m, days)
            mean, lo, hi = boot_mean(M, n=n_boot)
            ent[m] = {"mean": mean, "ci95": [lo, hi]}
        ent["seed_returns"] = [float(np.mean([r["return"] for r in rows[s] if r["day_id"] in set(days)])) for s in specs]
        out[name] = ent
    return out


def compare(rows, gmap, a, b, days, metrics=("return", "sla_queue_c_pct", "sla_high_pct", "lost_pct", "cost", "sla_pct"), n_boot=2000):
    return {m: boot_diff(matrix(rows, gmap[a], m, days), matrix(rows, gmap[b], m, days), n=n_boot) for m in metrics}


def print_board(bd, ref=None, comps=None):
    for n, e in sorted(bd.items(), key=lambda kv: -kv[1]["return"]["mean"]):
        c = (comps or {}).get(n)
        s = (f"{n[:70]:70s} n={e['n_seeds']:2d} ret {e['return']['mean']:8.2f} SLA {e['sla_pct']['mean']:5.2f} "
             f"HIGH {e['sla_high_pct']['mean']:6.2f} C {e['sla_queue_c_pct']['mean']:5.2f} lost {e['lost_pct']['mean']:5.2f} "
             f"cost {e['cost']['mean']:6.0f}")
        if "c_alloc_mean" in e:
            s += f" cA {e['c_alloc_mean']['mean']:.2f}"
        if c:
            s += (f" | dRet {c['return']['diff']:+.2f} [{c['return']['ci95'][0]:+.2f},{c['return']['ci95'][1]:+.2f}]"
                  f" dC {c['sla_queue_c_pct']['diff']:+.2f} [{c['sla_queue_c_pct']['ci95'][0]:+.2f},{c['sla_queue_c_pct']['ci95'][1]:+.2f}]"
                  f" dHIGH {c['sla_high_pct']['diff']:+.2f}")
        print(s)


def dev(only=None, ref="rule:mpc:0.5"):
    rows = load_rows("dev")
    gmap = groups(rows)
    if only:
        gmap = {k: v for k, v in gmap.items() if any(re.search(o, k) for o in only) or k == ref}
    days = [r["day_id"] for r in rows[ref]]
    bd = board(rows, gmap, days, n_boot=300)
    comps = {n: compare(rows, gmap, n, ref, days, n_boot=500) for n in gmap if n != ref}
    print_board(bd, ref, comps)
    out = E4 / "results" / "dev_analysis.json"
    prev = json.loads(out.read_text()) if out.exists() else {}
    prev.update({n: {"board": bd[n], "vs_mpc": comps.get(n)} for n in bd})
    out.write_text(json.dumps(prev, indent=1, default=float))
    return bd, comps


def test4():
    pr = json.loads((E4 / "configs" / "preregistration.json").read_text())
    rows = load_rows("test4")
    gmap = {g: specs for g, specs in pr["groups"].items()}
    missing = [s for v in gmap.values() for s in v if s not in rows]
    if missing:
        raise SystemExit(f"missing TEST4 rows: {missing}")
    days = [r["day_id"] for r in rows[pr["reference"]]]
    assert len(days) == pr["n_days"], "TEST4 incomplete"
    bd = board(rows, gmap, days, n_boot=2000)
    ref = pr["reference_group"]
    res = {"board": bd, "comparisons": {}, "constraint_checks": {}, "per_family": {}}
    prim = []
    for g in pr["primary_comparisons"]:
        c = compare(rows, gmap, g, ref, days, n_boot=4000)
        res["comparisons"][g] = c
        prim.append(c["return"]["p_boot"])
    for g, p in zip(pr["primary_comparisons"], holm(prim)):
        res["comparisons"][g]["return"]["p_holm"] = p
    for g in pr.get("secondary_comparisons", []):
        a, b = g
        res["comparisons"][f"{a} vs {b}"] = compare(rows, gmap, a, b, days, n_boot=4000)
    cons = pr["constraints"]
    for g in gmap:
        if g == ref:
            continue
        c = res["comparisons"].get(g) or compare(rows, gmap, g, ref, days, n_boot=4000)
        lo_c = c["sla_queue_c_pct"]["ci95"][0]
        lo_h = c["sla_high_pct"]["ci95"][0]
        viol = {m: float(np.sum(matrix(rows, gmap[g], m, days))) for m in ("high_on_fallback", "invalid_proposals")}
        viol["budget_not_ok_days"] = float(np.sum(1 - matrix(rows, gmap[g], "budget_ok", days)))
        res["constraint_checks"][g] = {
            "queue_c_noninferior": bool(lo_c > -cons["queue_c_margin_pp"]), "queue_c_ci_low": lo_c,
            "high_noninferior": bool(lo_h > -cons["high_margin_pp"]), "high_ci_low": lo_h,
            "safety_violations": viol, "zero_safety_violations": all(v == 0 for v in viol.values())}
    fam_of = {r["day_id"]: r["family"] for r in rows[pr["reference"]]}
    for g in gmap:
        res["per_family"][g] = {f: float(np.mean(matrix(rows, gmap[g], "return", [d for d in days if fam_of[d] == f])))
                                for f in sorted(set(fam_of.values()))}
    for part, held in (("in_dist", False), ("held_out", True)):
        dd = [d for d in days if (fam_of[d] in pr["heldout_families"]) == held]
        res[f"return_{part}_vs_ref"] = {g: boot_diff(matrix(rows, gmap[g], "return", dd), matrix(rows, gmap[ref], "return", dd), n=2000)
                                        for g in gmap if g != ref}
    (E4 / "results" / "test4_analysis.json").write_text(json.dumps(res, indent=1, default=float))
    print_board(bd, ref, res["comparisons"])
    print(json.dumps(res["constraint_checks"], indent=1, default=float))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("split", choices=["dev", "test4"])
    ap.add_argument("--groups", nargs="*")
    a = ap.parse_args()
    dev(a.groups) if a.split == "dev" else test4()
