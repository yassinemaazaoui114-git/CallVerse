"""Agent E v3 analysis: VAL selection, TEST leaderboard, paired statistics, Pareto, sensitivity, figures.

    python -m v3.e.analyze_v3 val      -> results/val_choice.json  (rule parameters chosen on VAL only)
    python -m v3.e.analyze_v3 test     -> results/test_*.json|csv + figures/  (uses the locked TEST rows)
Statistics: rows are paired by day_id (identical exogenous tapes). Learned policies have several training seeds:
policy mean = mean over seeds of the per-seed day-mean; CI = two-level bootstrap (resample seeds, then days;
the SAME resampled days for both policies of a comparison = paired). Effect size d_z = mean paired difference /
SD of the per-day differences (seed-averaged). Primary comparisons are Holm-corrected (bootstrap p-values).
"""

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
E = Path(__file__).resolve().parent
RES, FIG = E / "results", E / "figures"
REF = {"F": 1.9469791666666666, "L": 1.6559895833333333, "C": 16.0}
WEIGHTS = {"equal": (1, 1, 1), "sla_heavy": (2, 1, 1), "abandon_heavy": (1, 2, 1), "cost_heavy": (1, 1, 2)}
METRICS = ["return", "sla_pct", "sla_high_pct", "sla_medium_pct", "sla_low_pct", "sla_queue_c_pct", "abandon_pct",
           "lost_pct", "unresolved_end_pct", "mean_wait_min", "p95_wait_min", "cost", "fallback_share",
           "high_on_fallback", "invalid_proposals", "safety_interventions", "sim_csat", "budget_ok"]


def load_rows(split):
    out = {}
    for f in sorted((RES / f"eval_{split}").glob("*.csv")):
        rows = list(csv.DictReader(open(f)))
        for r in rows:
            for k, v in r.items():
                if k not in ("policy", "day_id", "family"):
                    r[k] = float(v) if v not in ("True", "False") else float(v == "True")
        out[rows[0]["policy"]] = rows
    return out


def ret_under(rows, w):
    """Return recomputed from KPIs under weights w (exact: the env reward is a function of these KPIs)."""
    ws, wa, wc = w
    out = []
    for r in rows:
        n = r["arrived"]
        out.append(-(ws * (100 - r["sla_pct"]) / 100 * n / REF["F"] + wa * r["lost_pct"] / 100 * n / REF["L"]
                     + wc * r["cost"] / REF["C"]))
    return np.array(out)


def group_of(spec):
    """rl:<algo>_<w>_h.._150k_s3[tag] -> 'rl:<algo>_<w>_h.._150k[tag]' (seeds pooled)."""
    return re.sub(r"_s\d+", "", spec)


def matrix(rows_by_policy, specs, metric, days, w=None):
    """[seeds, days] matrix of a metric for a group of policy specs (one row per seed)."""
    m = []
    for s in specs:
        by = {r["day_id"]: r for r in rows_by_policy[s]}
        rr = [by[d] for d in days]
        m.append(ret_under(rr, w) if (metric == "return" and w) else np.array([r[metric] for r in rr]))
    return np.array(m)


def boot_mean(M, n=2000, seed=0):
    rng = np.random.default_rng(seed)
    s, d = M.shape
    b = np.array([M[np.ix_(rng.integers(0, s, s), rng.integers(0, d, d))].mean() for _ in range(n)])
    return float(M.mean()), float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))


def boot_diff(A, B, n=2000, seed=0):
    """Paired difference A - B. A: [sa, d], B: [sb, d]. Same resampled days for both; seeds resampled per group."""
    rng = np.random.default_rng(seed)
    sa, d = A.shape
    sb = B.shape[0]
    diffs = np.empty(n)
    for i in range(n):
        di = rng.integers(0, d, d)
        diffs[i] = A[rng.integers(0, sa, sa)][:, di].mean() - B[rng.integers(0, sb, sb)][:, di].mean()
    m = float(A.mean() - B.mean())
    p = float(2 * min((diffs <= 0).mean(), (diffs >= 0).mean()))
    per_day = A.mean(0) - B.mean(0)
    dz = float(per_day.mean() / per_day.std(ddof=1)) if per_day.std() > 0 else 0.0
    return {"diff": m, "ci95": [float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))], "p_boot": max(p, 1 / n),
            "d_z": dz, "win_rate": float((per_day > 0).mean())}


def holm(ps):
    order = np.argsort(ps)
    adj = np.empty(len(ps))
    run = 0.0
    for k, i in enumerate(order):
        run = max(run, (len(ps) - k) * ps[i])
        adj[i] = min(1.0, run)
    return adj.tolist()


def val_choice():
    rows = load_rows("val")
    choice, table = {}, {}
    for fam, pat in (("forecast_z", r"rule:forecast:(.+)"), ("erlang_target", r"rule:erlang:(.+)"), ("mpc_k", r"rule:mpc:(.+)")):
        cands = {re.match(pat, s).group(1): float(np.mean([r["return"] for r in rs])) for s, rs in rows.items() if re.match(pat, s)}
        if cands:
            best = max(cands, key=cands.get)
            choice[fam] = float(best)
            choice[fam + "_spec"] = best            # exact string used in the policy spec
            table[fam] = cands
    others = {s: float(np.mean([r["return"] for r in rs])) for s, rs in rows.items() if not s.startswith("rule:forecast")
              and not s.startswith("rule:erlang") and not s.startswith("rule:mpc")}
    choice["val_returns"] = {**{k: v for k, v in table.items()}, "other": others}
    (RES / "val_choice.json").write_text(json.dumps(choice, indent=2))
    print(json.dumps({k: v for k, v in choice.items() if k != "val_returns"}, indent=1))
    return choice


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "test"
    if mode == "val":
        val_choice()
        return
    from v3.e.analyze_v3_report import report        # figures + tables (separate module, keeps this file short)
    report(load_rows("test"))


if __name__ == "__main__":
    main()
