"""Confirmatory TEST5 analysis — exactly the analysis frozen in configs/preregistration5.json.

    python -m v5.e.analyze_test5        -> results/test5_analysis.json (+ printed summary)
Refuses to run if the pre-registration is missing, if the manifest hash changed, or if a pre-registered checkpoint
hash changed since the freeze. Primary: return difference vs the reference (paired two-level bootstrap, 4000
resamples), Holm over the primary comparisons. Safety acceptance: CI lower bounds of queue-C and HIGH SLA
differences above the margins AND zero hard-constraint violations. Lower tail: CVaR10 difference. Per family and
per block (in-distribution / held-out / unseen-shift): descriptive (point estimates + 95 % CI per block).
"""

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from v3.e.analyze_v3 import holm, matrix  # noqa: E402
from v5.e.analyze_v5 import compare, fmt_ci, load_rows, summary  # noqa: E402
from v5.e.common5 import CFG, E5, file_sha256, load_manifest  # noqa: E402

HARD = ("invalid_proposals", "high_on_fallback")


def main():
    pr = json.loads((CFG / "preregistration5.json").read_text())
    assert (CFG / "test5_manifest.sha256").read_text().strip() == pr["test_manifest_sha256"]
    for s, h in pr["checkpoint_hashes"].items():
        if file_sha256(E5.parents[1] / h["checkpoint"]) != h["best_pt_sha256"]:
            raise SystemExit(f"checkpoint changed since pre-registration: {s}")
    man = load_manifest("test5")
    days = [d["day_id"] for d in man]
    fam_of = {d["day_id"]: d["family"] for d in man}
    block = {d["day_id"]: ("unseen_shift" if d.get("unseen_shift") else "heldout" if d["heldout_family"] else "in_dist")
             for d in man}
    rows = load_rows("test5", with_v4=False)
    G = pr["groups"]
    missing = [s for v in G.values() for s in v if s not in rows or len(rows[s]) != len(days)]
    if missing:
        raise SystemExit(f"TEST5 rows incomplete: {missing[:5]} ...")
    ref = G[pr["reference_group"]]
    out = {"preregistration_frozen_at": pr["frozen_at_utc"], "n_days": len(days), "groups": {}, "primary": {},
           "secondary": {}, "per_family": {}, "per_block": {}, "runtime": {}}
    for g, specs in G.items():
        ent = summary(rows, specs, days, n_boot=1000)
        ent["hard_violations"] = {k: int(sum(r[k] for s in specs for r in rows[s])) for k in HARD}
        ent["hard_violations"]["budget_overrun_days"] = int(sum(1 - r["budget_ok"] for s in specs for r in rows[s]))
        prov = {}
        for c in ("n_prov_rl", "n_prov_rl_rechoice", "n_prov_owner", "n_prov_rule", "n_prov_shield_default", "n_intervened"):
            prov[c] = 100.0 * sum(r[c] for s in specs for r in rows[s]) / (96 * len(days) * len(specs))
        ent["decision_provenance_pct"] = prov
        out["groups"][g] = ent
        metas = [json.loads((E5 / "results" / "eval_test5" / (s.replace(":", "__").replace("|", "+").replace("@", "_at_")
                                                                + ".json")).read_text()) for s in specs]
        out["runtime"][g] = {"decision_ms_p50": float(np.median([m["decision_ms_p50"] for m in metas])),
                             "decision_ms_p95": float(np.median([m["decision_ms_p95"] for m in metas])),
                             "n_params": metas[0].get("n_params", 0)}
    c = pr["constraints"]
    for g in pr["primary_comparisons"]:
        cmp = compare(rows, G[g], ref, days, n_boot=4000)
        hv = out["groups"][g]["hard_violations"]
        safe_c = cmp["sla_queue_c_pct"]["ci95"][0] >= c["queue_c_margin_pp"]
        safe_h = cmp["sla_high_pct"]["ci95"][0] >= c["high_margin_pp"]
        safe_hard = sum(hv.values()) == 0
        out["primary"][g] = {**cmp, "safe_queue_c": safe_c, "safe_high": safe_h, "zero_hard_violations": safe_hard,
                             "safety_accepted": bool(safe_c and safe_h and safe_hard)}
    ps = [out["primary"][g]["return"]["p_boot"] for g in pr["primary_comparisons"]]
    for g, p in zip(pr["primary_comparisons"], holm(ps)):
        out["primary"][g]["return_p_holm"] = p
    for a, b in pr.get("secondary_comparisons", []):
        out["secondary"][f"{a} - {b}"] = compare(rows, G[a], G[b], days, n_boot=2000)
    for g in G:
        if g == pr["reference_group"]:
            continue
        fam = {}
        for f in pr["families"]:
            dd = [d for d in days if fam_of[d] == f]
            A, B = matrix(rows, G[g], "return", dd).mean(0), matrix(rows, ref, "return", dd).mean(0)
            Ac, Bc = matrix(rows, G[g], "sla_queue_c_pct", dd).mean(0), matrix(rows, ref, "sla_queue_c_pct", dd).mean(0)
            fam[f] = {"d_return": float((A - B).mean()), "d_queue_c_pp": float((Ac - Bc).mean())}
        out["per_family"][g] = fam
        blk = {}
        for bname in ("in_dist", "heldout", "unseen_shift"):
            dd = [d for d in days if block[d] == bname]
            blk[bname] = compare(rows, G[g], ref, dd, metrics=("return", "sla_queue_c_pct", "sla_high_pct"), n_boot=2000)
        out["per_block"][g] = blk
    (E5 / "results" / "test5_analysis.json").write_text(json.dumps(out, indent=1))
    print(f"TEST5 {len(days)} days; reference {pr['reference_group']}")
    for g, e in sorted(out["groups"].items(), key=lambda kv: -kv[1]["return"]["mean"]):
        p = out["primary"].get(g)
        s = (f"{g:34s} n={e['n_seeds']:2d} ret {e['return']['mean']:8.2f} C {e['sla_queue_c_pct']['mean']:5.2f} "
             f"HIGH {e['sla_high_pct']['mean']:6.2f} lost {e['lost_pct']['mean']:5.2f} cvar10 {e['cvar10']:8.2f}")
        if p:
            s += (f" | dRet {fmt_ci(p['return'])} pHolm {p['return_p_holm']:.4f} dC {fmt_ci(p['sla_queue_c_pct'])} "
                  f"dHIGH {fmt_ci(p['sla_high_pct'], 3)} dCVaR {fmt_ci(p['cvar10'])} SAFE={p['safety_accepted']}")
        print(s)


if __name__ == "__main__":
    main()
