"""Tables + figures for the Agent E v3 locked TEST evaluation (called by analyze_v3.py test)."""

import csv
import json
import re
from collections import defaultdict
from pathlib import Path

import numpy as np

from v3.e.analyze_v3 import (FIG, METRICS, RES, WEIGHTS, boot_diff, boot_mean, group_of, holm, matrix,
                             ret_under)
from v3.e.scenarios_v3 import HELDOUT_FAMILIES, TRAIN_FAMILIES

E = Path(__file__).resolve().parent
HEAD = ["return", "sla_pct", "sla_high_pct", "sla_queue_c_pct", "sla_medium_pct", "sla_low_pct", "abandon_pct",
        "lost_pct", "unresolved_end_pct", "mean_wait_min", "p95_wait_min", "cost", "fallback_share",
        "invalid_proposals", "safety_interventions", "high_on_fallback", "budget_ok", "sim_csat"]


def meta_of(spec):
    p = RES / "eval_test" / (spec.replace(":", "__") + ".json")
    return json.loads(p.read_text()) if p.exists() else {}


def report(rows):
    FIG.mkdir(parents=True, exist_ok=True)
    days = [r["day_id"] for r in next(iter(rows.values()))]
    fam_of = {r["day_id"]: r["family"] for r in next(iter(rows.values()))}
    vc = json.loads((RES / "val_choice.json").read_text())
    groups = defaultdict(list)
    for s in rows:
        groups[group_of(s) if not s.startswith("rule:") else s].append(s)
    # tuned rule representatives (chosen on VAL)
    tuned = {"forecast*": f"rule:forecast:{vc['forecast_z_spec']}", "erlang_c*": f"rule:erlang:{vc['erlang_target_spec']}",
             "fluid_mpc*": f"rule:mpc:{vc['mpc_k_spec']}", "fixed": "rule:fixed", "threshold": "rule:threshold",
             "priority": "rule:priority", "random_valid": "rule:random_valid"}
    tuned = {k: v for k, v in tuned.items() if v in rows}
    display = {**{k: [v] for k, v in tuned.items()},
               **{g: sorted(v) for g, v in groups.items() if not g.startswith("rule:")}}
    # ---------------- leaderboard
    board = {}
    for name, specs in display.items():
        ent = {"n_seeds": len(specs), "specs": specs}
        for m in HEAD:
            M = matrix(rows, specs, m, days, WEIGHTS["equal"] if m == "return" else None)
            mean, lo, hi = boot_mean(M, n=1000)
            ent[m] = {"mean": mean, "ci95": [lo, hi], "seed_std": float(M.mean(1).std()) if len(specs) > 1 else 0.0}
        mt = meta_of(specs[0])
        ent["n_params"] = mt.get("n_params", 0)
        ent["ckpt_kb"] = mt.get("ckpt_kb", 0)
        ent["decision_ms_p50"] = float(np.mean([meta_of(s).get("decision_ms_p50", np.nan) for s in specs]))
        ent["decision_ms_p95"] = float(np.mean([meta_of(s).get("decision_ms_p95", np.nan) for s in specs]))
        for part, fams in (("in_dist", TRAIN_FAMILIES), ("held_out", HELDOUT_FAMILIES)):
            dd = [d for d in days if fam_of[d] in fams]
            ent[f"return_{part}"] = boot_mean(matrix(rows, specs, "return", dd, WEIGHTS["equal"]), n=500)[0]
        board[name] = ent
    # ---------------- reference = best tuned rule on VAL return
    val_ret = {"forecast*": vc["val_returns"]["forecast_z"][vc["forecast_z_spec"]],
               "erlang_c*": vc["val_returns"]["erlang_target"][vc["erlang_target_spec"]],
               "fluid_mpc*": vc["val_returns"]["mpc_k"][vc["mpc_k_spec"]]}
    for k in ("fixed", "threshold", "priority", "random_valid"):
        val_ret[k] = vc["val_returns"]["other"].get(tuned.get(k, ""), -1e9)
    ref = max(val_ret, key=val_ret.get)
    comps, primary = {}, []
    for name, specs in display.items():
        if name == ref or name in tuned:
            continue
        c = {}
        for m in ("return", "sla_pct", "lost_pct", "cost", "sla_high_pct", "sla_queue_c_pct"):
            A = matrix(rows, specs, m, days, WEIGHTS["equal"] if m == "return" else None)
            B = matrix(rows, display[ref], m, days, WEIGHTS["equal"] if m == "return" else None)
            c[m] = boot_diff(A, B, n=1000)
        for part, fams in (("in_dist", TRAIN_FAMILIES), ("held_out", HELDOUT_FAMILIES)):
            dd = [d for d in days if fam_of[d] in fams]
            c[f"return_{part}"] = boot_diff(matrix(rows, specs, "return", dd, WEIGHTS["equal"]),
                                            matrix(rows, display[ref], "return", dd, WEIGHTS["equal"]), n=1000)
        comps[name] = c
        primary.append(name)
    adj = holm([comps[n]["return"]["p_boot"] for n in primary]) if primary else []
    for n, p in zip(primary, adj):
        comps[n]["return"]["p_holm"] = p
    # also: all tuned rules vs the reference (are the baselines tied?)
    for name in tuned:
        if name != ref:
            comps[name] = {"return": boot_diff(matrix(rows, display[name], "return", days, WEIGHTS["equal"]),
                                               matrix(rows, display[ref], "return", days, WEIGHTS["equal"]), n=1000)}
    # ---------------- per family return
    per_fam = {name: {f: float(np.mean(matrix(rows, specs, "return", [d for d in days if fam_of[d] == f], WEIGHTS["equal"])))
                      for f in TRAIN_FAMILIES + HELDOUT_FAMILIES} for name, specs in display.items()}
    # ---------------- Pareto (means over TEST) and matched comparisons against the rule curves
    pts = {name: (board[name]["cost"]["mean"], 100 - board[name]["sla_pct"]["mean"], board[name]["lost_pct"]["mean"])
           for name in display}
    curve_pts = {}
    for fam, pat in (("forecast", r"rule:forecast:(.+)"), ("erlang", r"rule:erlang:(.+)"), ("mpc", r"rule:mpc:(.+)")):
        cp = []
        for s, rs in rows.items():
            m = re.match(pat, s)
            if m:
                cp.append((float(np.mean([r["cost"] for r in rs])), 100 - float(np.mean([r["sla_pct"] for r in rs])),
                           float(np.mean([r["lost_pct"] for r in rs])), m.group(1)))
        curve_pts[fam] = sorted(cp)
    allp = {**pts, **{f"{f}:{p[3]}": p[:3] for f, cp in curve_pts.items() for p in cp}}
    nondom = [n for n, a in allp.items() if not any(all(b[i] <= a[i] for i in range(3)) and any(b[i] < a[i] for i in range(3))
                                                    for m, b in allp.items() if m != n)]
    matched = {}
    for name in display:
        if name in tuned:
            continue
        c, fail, lost = pts[name]
        mm = {}
        for fam in ("forecast", "erlang"):
            cp = curve_pts[fam]
            costs = [p[0] for p in cp]
            if cp and costs[0] <= c <= costs[-1]:
                mm[f"sla_fail_minus_{fam}_at_same_cost"] = fail - float(np.interp(c, costs, [p[1] for p in cp]))
                mm[f"lost_minus_{fam}_at_same_cost"] = lost - float(np.interp(c, costs, [p[2] for p in cp]))
            byfail = sorted(cp, key=lambda p: p[1])
            fs = [p[1] for p in byfail]
            if cp and fs[0] <= fail <= fs[-1]:
                mm[f"cost_minus_{fam}_at_same_sla"] = c - float(np.interp(fail, fs, [p[0] for p in byfail]))
        matched[name] = mm
    # ---------------- reward-weight sensitivity: ranking under each preset (returns recomputed exactly from KPIs)
    sens = {}
    for wname, w in WEIGHTS.items():
        sc = {name: float(np.mean(matrix(rows, specs, "return", days, w))) for name, specs in display.items()}
        sens[wname] = {"ranking": sorted(sc, key=sc.get, reverse=True), "scores": sc}
    out = {"reference_policy": ref, "reference_choice": "best tuned rule by VAL return (equal weights)",
           "val_choice": {k: v for k, v in vc.items() if k != "val_returns"}, "leaderboard": board,
           "comparisons_vs_reference": comps, "per_family_return": per_fam, "pareto_points": pts,
           "rule_curves": curve_pts, "pareto_nondominated": nondom, "matched": matched, "weight_sensitivity": sens,
           "n_test_days": len(days), "families": {"in_dist": TRAIN_FAMILIES, "held_out": HELDOUT_FAMILIES}}
    (RES / "test_analysis.json").write_text(json.dumps(out, indent=2, default=float))
    with open(RES / "test_leaderboard.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["policy", "n_seeds", "params"] + [f"{m}_mean" for m in HEAD] + [f"{m}_ci_lo" for m in HEAD]
                   + [f"{m}_ci_hi" for m in HEAD] + ["decision_ms_p50", "decision_ms_p95", "return_in_dist", "return_held_out"])
        for n, e in sorted(board.items(), key=lambda kv: -kv[1]["return"]["mean"]):
            w.writerow([n, e["n_seeds"], e["n_params"]] + [round(e[m]["mean"], 4) for m in HEAD]
                       + [round(e[m]["ci95"][0], 4) for m in HEAD] + [round(e[m]["ci95"][1], 4) for m in HEAD]
                       + [e["decision_ms_p50"], e["decision_ms_p95"], round(e["return_in_dist"], 3), round(e["return_held_out"], 3)])
    figures(out, rows, days, display)
    print("reference:", ref)
    for n, e in sorted(board.items(), key=lambda kv: -kv[1]["return"]["mean"]):
        c = comps.get(n, {}).get("return")
        print(f"{n:52s} ret {e['return']['mean']:8.2f} [{e['return']['ci95'][0]:.2f},{e['return']['ci95'][1]:.2f}] "
              f"SLA {e['sla_pct']['mean']:5.2f} high {e['sla_high_pct']['mean']:5.2f} C {e['sla_queue_c_pct']['mean']:5.2f} "
              f"lost {e['lost_pct']['mean']:5.2f} cost {e['cost']['mean']:6.0f}"
              + (f" | d={c['diff']:+.2f} [{c['ci95'][0]:+.2f},{c['ci95'][1]:+.2f}] dz {c['d_z']:+.2f}"
                 + (f" pHolm {c.get('p_holm', float('nan')):.3f}" if 'p_holm' in c else "") if c else ""))
    return out


def figures(out, rows, days, display):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    board = out["leaderboard"]
    order = sorted(board, key=lambda n: board[n]["return"]["mean"])
    # 1. leaderboard with CIs
    fig, ax = plt.subplots(figsize=(9, 0.35 * len(order) + 1.5))
    m = [board[n]["return"]["mean"] for n in order]
    lo = [board[n]["return"]["mean"] - board[n]["return"]["ci95"][0] for n in order]
    hi = [board[n]["return"]["ci95"][1] - board[n]["return"]["mean"] for n in order]
    ax.barh(order, m, xerr=[lo, hi], color=["#888" if n in ("fixed", "threshold", "priority", "random_valid") or n.endswith("*")
                                            else "#3a7" for n in order])
    ax.set_xlabel("balanced return per day (reference-normalised, equal weights; higher = better)")
    ax.set_title(f"Agent E v3 - locked TEST ({len(days)} simulated days, 13 families) - mean and 95% CI")
    ax.tick_params(axis="y", labelsize=7)
    ax.set_xlim(min(m) - 15, max(m) + 10)
    fig.tight_layout()
    fig.savefig(FIG / "e_leaderboard.png", dpi=120)
    plt.close(fig)
    # 2. Pareto: cost vs SLA failure, cost vs lost
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    for ax, k, lab in ((axes[0], 1, "SLA failures (% of tickets)"), (axes[1], 2, "lost customers (% of tickets)")):
        for fam, cp in out["rule_curves"].items():
            if cp:
                ax.plot([p[0] for p in cp], [p[k] for p in cp], "o-", ms=3, label=f"{fam} sweep")
        for n, p in out["pareto_points"].items():
            if not n.startswith("rule") and not n.endswith("*") and n not in ("fixed", "threshold", "priority", "random_valid"):
                ax.scatter(p[0], p[k], marker="x", s=30)
                ax.annotate(n.replace("guarded:", "G:").replace("rl:", "").replace("_equal_h64x64", "")[:28], (p[0], p[k]),
                            fontsize=6)
        ax.set_xlabel("cost (session-steps per day)")
        ax.set_ylabel(lab)
        ax.set_title(f"TEST: {lab} vs cost (lower-left is better)")
        ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(FIG / "e_pareto.png", dpi=120)
    plt.close(fig)
    # 3. per-family difference to reference
    ref = out["reference_policy"]
    fams = out["families"]["in_dist"] + out["families"]["held_out"]
    names = [n for n in order[::-1] if n != ref][:14]
    M = np.array([[out["per_family_return"][n][f] - out["per_family_return"][ref][f] for f in fams] for n in names])
    fig, ax = plt.subplots(figsize=(12, 0.4 * len(names) + 2))
    lim = np.abs(M).max()
    im = ax.imshow(M, cmap="RdYlGn", vmin=-lim, vmax=lim, aspect="auto")
    ax.set_xticks(range(len(fams)), [f + (" (held-out)" if f in out["families"]["held_out"] else "") for f in fams],
                  rotation=40, ha="right", fontsize=7)
    ax.set_yticks(range(len(names)), names, fontsize=7)
    for i in range(len(names)):
        for j in range(len(fams)):
            ax.text(j, i, f"{M[i, j]:+.1f}", ha="center", va="center", fontsize=6)
    fig.colorbar(im, label=f"return difference vs {ref} (per day)")
    ax.set_title("TEST by scenario family: return difference vs best VAL-tuned rule")
    fig.tight_layout()
    fig.savefig(FIG / "e_per_family.png", dpi=120)
    plt.close(fig)
    # 4. learning curves (matched 150k budget)
    curves = defaultdict(list)
    for d in sorted((E / "runs").glob("*")):
        f = d / "val_log.csv"
        if f.exists() and "_equal_h64x64_150k_" in d.name:
            r = list(csv.DictReader(open(f)))
            curves[d.name.split("_equal")[0]].append(([int(x["step"]) for x in r], [float(x["val_return"]) for x in r]))
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for algo, cs in sorted(curves.items()):
        n = min(len(c[1]) for c in cs)
        Y = np.array([c[1][:n] for c in cs])
        ax.plot(cs[0][0][:n], Y.mean(0), label=f"{algo} (n={len(cs)})")
        ax.fill_between(cs[0][0][:n], Y.mean(0) - Y.std(0), Y.mean(0) + Y.std(0), alpha=0.15)
    vr = json.loads((RES / "val_choice.json").read_text())["val_returns"]
    best_rule = max(max(vr["forecast_z"].values()), max(vr["erlang_target"].values()), max(vr["mpc_k"].values()))
    ax.axhline(best_rule, ls="--", color="k", lw=1, label="best VAL-tuned rule")
    ax.set_xlabel("environment steps (matched 150k budget)")
    ax.set_ylabel("VAL return (48 days)")
    ax.set_title("Agent E v3 learning curves (mean +- 1 SD over seeds; VAL split)")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(FIG / "e_learning_curves.png", dpi=120)
    plt.close(fig)
    # 5. latency vs quality
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for n, e in board.items():
        if e["decision_ms_p50"] == e["decision_ms_p50"]:
            ax.scatter(e["decision_ms_p50"], e["return"]["mean"], s=15)
            ax.annotate(n.replace("guarded:", "G:").replace("rl:", "")[:24], (e["decision_ms_p50"], e["return"]["mean"]), fontsize=6)
    ax.set_xscale("log")
    ax.set_xlabel("decision latency p50 (ms, CPU, 1 thread, log scale)")
    ax.set_ylabel("TEST return")
    ax.set_title("Agent E v3: latency vs quality (TEST)")
    fig.tight_layout()
    fig.savefig(FIG / "e_latency_quality.png", dpi=120)
    plt.close(fig)
