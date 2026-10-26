"""Agent E v5 analysis helpers + command-line reports (DEV / DEVSHIFT exploratory, TEST5 confirmatory).

    python -m v5.e.analyze_v5 board dev [--filter substr ...]      leaderboard + paired comparisons vs MPC
    python -m v5.e.analyze_v5 e1                                     E1 baseline audit -> results/e1_baselines.json
Statistics reuse the frozen V3/V4 helpers: matrix(), boot_mean(), boot_diff() (two-level paired bootstrap:
resample training seeds within each group, the SAME resampled days for both groups), holm().
New here: CVaR10 = mean of the worst 10 % of days of the seed-averaged daily return (lower tail), with a paired
two-level bootstrap of the CVaR difference.
DEV rows: v5/e/results/eval_dev (v5 evaluator) merged with v4/e/results/eval_dev (identical evaluator, verified:
0 mismatching cells on 3 policies x 104 days); v5 rows win if both exist.
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
from v3.e.analyze_v3 import boot_diff, boot_mean, holm, matrix  # noqa: E402
from v5.e.common5 import E5, load_manifest  # noqa: E402

V4RES = HERE / "v4" / "e" / "results"
NUM_SKIP = ("policy", "day_id", "family")


def _read(f):
    rows = list(csv.DictReader(open(f)))
    for r in rows:
        for k, v in r.items():
            if k not in NUM_SKIP:
                r[k] = float(v) if v not in ("True", "False") else float(v == "True")
    return rows


def load_rows(split, with_v4=True):
    out = {}
    dirs = ([V4RES / f"eval_{split}"] if with_v4 and split in ("dev", "val") else []) + [E5 / "results" / f"eval_{split}"]
    for d in dirs:
        if d.exists():
            for f in sorted(d.glob("*.csv")):
                rows = _read(f)
                if rows:
                    out[rows[0]["policy"]] = rows
    return out


def group_of(spec):
    return spec if spec.startswith("rule:") or "|rule:" in spec else re.sub(r"_s\d+(?=$|_)", "", spec)


def groups(rows, specs=None):
    g = defaultdict(list)
    for s in (specs or rows):
        g[group_of(s)].append(s)
    return {k: sorted(v, key=lambda x: int(re.search(r"_s(\d+)", x).group(1)) if re.search(r"_s(\d+)", x) else 0)
            for k, v in g.items()}


def cvar(v, q=0.10):
    v = np.sort(np.asarray(v))
    k = max(1, int(np.ceil(q * len(v))))
    return float(v[:k].mean())


def boot_cvar_diff(A, B, n=2000, seed=0, q=0.10):
    rng = np.random.default_rng(seed)
    sa, d = A.shape
    sb = B.shape[0]
    out = np.empty(n)
    for i in range(n):
        di = rng.integers(0, d, d)
        out[i] = cvar(A[rng.integers(0, sa, sa)][:, di].mean(0), q) - cvar(B[rng.integers(0, sb, sb)][:, di].mean(0), q)
    return {"diff": cvar(A.mean(0), q) - cvar(B.mean(0), q), "ci95": [float(np.percentile(out, 2.5)),
                                                                      float(np.percentile(out, 97.5))]}


def summary(rows, specs, days, metrics=("return", "sla_pct", "sla_high_pct", "sla_queue_c_pct", "lost_pct", "cost"),
            n_boot=1000):
    ent = {"n_seeds": len(specs), "specs": specs}
    for m in metrics:
        M = matrix(rows, specs, m, days)
        mean, lo, hi = boot_mean(M, n=n_boot)
        ent[m] = {"mean": mean, "ci95": [lo, hi]}
    R = matrix(rows, specs, "return", days)
    ent["cvar10"] = cvar(R.mean(0))
    ent["seed_returns"] = [float(x) for x in R.mean(1)]
    ent["seed_sd"] = float(np.std(R.mean(1), ddof=1)) if len(specs) > 1 else 0.0
    return ent


def compare(rows, A, B, days, metrics=("return", "sla_queue_c_pct", "sla_high_pct", "lost_pct", "cost", "sla_pct"),
            n_boot=2000, tail=True):
    out = {m: boot_diff(matrix(rows, A, m, days), matrix(rows, B, m, days), n=n_boot) for m in metrics}
    if tail:
        out["cvar10"] = boot_cvar_diff(matrix(rows, A, "return", days), matrix(rows, B, "return", days), n=n_boot)
    return out


def fmt_ci(c, nd=2):
    return f"{c['diff']:+.{nd}f} [{c['ci95'][0]:+.{nd}f},{c['ci95'][1]:+.{nd}f}]"


def day_ids(split):
    return [d["day_id"] for d in load_manifest(split)]


# ---------------------------------------------------------------------------------------------- E1
E1_SET = {
    "Dueling DQN (V3, pure RL)": [f"rl:dueling_dqn_equal_h64x64_150k_s{i}" for i in range(5)],
    "Dueling DDQN (V3, pure RL)": [f"rl:dueling_double_dqn_equal_h64x64_150k_s{i}" for i in range(10)],
    "Fluid MPC k=0.5": ["rule:mpc:0.5"],
    "V3 guarded hybrid (Forecast owns capacity, DDQN allocates)": [f"guarded:dueling_double_dqn_equal_h64x64_150k_s{i}" for i in range(10)],
    "floor@3 + MPC": ["floor@3|rule:mpc:0.5"],
    "floor@3 + V3 guarded (DDQN)": [f"floor@3|guarded:dueling_double_dqn_equal_h64x64_150k_s{i}" for i in range(10)],
    "floor@3 + pure Dueling DDQN": [f"floor@3|rl:dueling_double_dqn_equal_h64x64_150k_s{i}" for i in range(10)],
    "floor@3 + pure Dueling DQN": [f"floor@3|rl:dueling_dqn_equal_h64x64_150k_s{i}" for i in range(5)],
    "Forecast z=0.25": ["rule:forecast:0.25"],
    "Erlang-C 0.4": ["rule:erlang:0.4"],
}


def e1():
    from v5.e.common5 import load_manifest as lm
    man = lm("dev")
    want = [(d["day_id"], d["seed"]) for d in man]
    rows = load_rows("dev")
    audit, res = {}, {}
    for name, specs in E1_SET.items():
        for s in specs:
            if s not in rows:
                raise SystemExit(f"missing DEV rows: {s}")
            got = [(r["day_id"], int(r["seed"])) for r in rows[s]]
            src = "v5" if (E5 / "results" / "eval_dev" / (s.replace(":", "__").replace("|", "+").replace("@", "_at_") + ".csv")).exists() else "v4"
            audit[s] = {"rows": len(got), "same_days_and_seeds_as_manifest": got == want, "source": src}
    days = [d for d, _ in want]
    ref = E1_SET["Fluid MPC k=0.5"]
    for name, specs in E1_SET.items():
        ent = summary(rows, specs, days)
        if specs != ref:
            ent["vs_mpc"] = compare(rows, specs, ref, days)
        res[name] = ent
    out = {"manifest": "v4/e/configs/dev_manifest.json", "manifest_sha256":
           (HERE / "v4/e/configs/dev_manifest.sha256").read_text().strip(), "n_days": len(days), "audit": audit,
           "all_rows_match_manifest": all(a["same_days_and_seeds_as_manifest"] for a in audit.values()), "groups": res}
    (E5 / "results" / "e1_baselines.json").write_text(json.dumps(out, indent=1))
    print("all rows match manifest:", out["all_rows_match_manifest"], "| sources:",
          {k: sum(1 for a in audit.values() if a["source"] == k) for k in ("v4", "v5")})
    for name, e in res.items():
        vs = e.get("vs_mpc")
        print(f"{name[:58]:58s} n={e['n_seeds']:2d} ret {e['return']['mean']:8.2f} sd {e['seed_sd']:5.2f} "
              f"C {e['sla_queue_c_pct']['mean']:5.2f} HIGH {e['sla_high_pct']['mean']:6.2f} cvar10 {e['cvar10']:8.2f}"
              + (f" | dRet {fmt_ci(vs['return'])} dC {fmt_ci(vs['sla_queue_c_pct'])} dHIGH {fmt_ci(vs['sla_high_pct'])}"
                 if vs else ""))


def board_cmd(split, filters, ref="rule:mpc:0.5"):
    rows = load_rows(split)
    specs = [s for s in rows if not filters or any(f in s for f in filters) or s == ref]
    gm = groups(rows, specs)
    days = day_ids(split)
    res = {}
    for g, sp in gm.items():
        ent = summary(rows, sp, days, n_boot=300)
        if g != ref and ref in rows:
            c = compare(rows, sp, [ref], days, n_boot=800)
            ent["vs_ref"] = c
        res[g] = ent
    for g, e in sorted(res.items(), key=lambda kv: -kv[1]["return"]["mean"]):
        vs = e.get("vs_ref")
        print(f"{g[:75]:75s} n={e['n_seeds']:2d} ret {e['return']['mean']:8.2f} sd {e['seed_sd']:5.2f} "
              f"C {e['sla_queue_c_pct']['mean']:5.2f} HIGH {e['sla_high_pct']['mean']:6.2f} lost {e['lost_pct']['mean']:5.2f} "
              f"cvar {e['cvar10']:8.2f}" + (f" | dRet {fmt_ci(vs['return'])} dC {fmt_ci(vs['sla_queue_c_pct'])}" if vs else ""))
    return res


if __name__ == "__main__":
    if sys.argv[1] == "e1":
        e1()
    elif sys.argv[1] == "board":
        board_cmd(sys.argv[2], sys.argv[3:])
