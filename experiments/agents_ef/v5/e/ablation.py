"""E3-E8 ablation tables on DEV / DEVSHIFT: every arm vs its matched control on the SAME training seeds.

    python -m v5.e.ablation [--write]        -> prints tables; --write saves results/ablation.json
    python -m v5.e.ablation queue <split>    -> prints the evaluation specs still missing (for evaluate_v5)
Control for Dueling DQN arms = V3 dueling_dqn_equal_h64x64_150k_s<k> (the v5 trainer reproduces it exactly);
for Dueling DDQN arms = V3 dueling_double_dqn_equal_h64x64_150k_s<k>. Wrappers: pure greedy RL ("rl:") and the
static floor ("floor@3|rl:"). Differences = paired two-level bootstrap (seeds and days resampled; same days).
"""

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from v5.e.analyze_v5 import E5, compare, day_ids, fmt_ci, load_rows, summary  # noqa: E402
from v5.e.common5 import RUNS  # noqa: E402

DQN_C = "dueling_dqn_equal_h64x64_150k_s{}"
DDQN_C = "dueling_double_dqn_equal_h64x64_150k_s{}"
ARMS = {   # name: (run pattern, control pattern)
    "PER": ("dueling_dqn_h64x64_150k_per_s{}", DQN_C),
    "N3": ("dueling_dqn_h64x64_150k_n3_s{}", DQN_C),
    "N5": ("dueling_dqn_h64x64_150k_n5_s{}", DQN_C),
    "DR": ("dueling_dqn_h64x64_150k_dr_s{}", DQN_C),
    "FLIP": ("dueling_dqn_h64x64_150k_flip0.0625_s{}", DQN_C),
}
WRAPS = {"pure": "rl:{}", "floor3": "floor@3|rl:{}"}


def add_arm(name, pattern, control):
    ARMS[name] = (pattern, control)


def done_seeds(pattern, upto=10):
    return [s for s in range(upto) if (RUNS / pattern.format(s) / "run.json").exists()
            and json.loads((RUNS / pattern.format(s) / "run.json").read_text()).get("status") == "done"]


def missing(split):
    out = []
    for name, (pat, ctl) in ARMS.items():
        for s in done_seeds(pat):
            for w in (WRAPS.values() if split == "dev" else ["rl:{}"]):
                out += [w.format(pat.format(s)), w.format(ctl.format(s))]
    rows = load_rows(split)
    return [s for s in dict.fromkeys(out) if s not in rows]


def table(split="dev", wraps=("pure", "floor3")):
    rows = load_rows(split)
    days = day_ids(split)
    res = {}
    for name, (pat, ctl) in ARMS.items():
        seeds = done_seeds(pat)
        for wn in wraps:
            w = WRAPS[wn]
            A = [w.format(pat.format(s)) for s in seeds]
            B = [w.format(ctl.format(s)) for s in seeds]
            if not seeds or not all(x in rows for x in A + B):
                continue
            c = compare(rows, A, B, days, metrics=("return", "sla_queue_c_pct", "sla_high_pct", "lost_pct",
                                                   "abandon_pct", "cost"), n_boot=1000)
            sa, sb = summary(rows, A, days, n_boot=200), summary(rows, B, days, n_boot=200)
            flips = lambda S: float(np.mean([r["n_flip"] for s in S for r in rows[s]])) if "n_flip" in rows[S[0]][0] else None
            ent = {"seeds": seeds, "arm": sa, "control": sb, "diff": c, "flips_arm": flips(A), "flips_control": flips(B)}
            res[f"{name}|{wn}"] = ent
            print(f"{split:8s} {name:10s} {wn:6s} seeds {seeds} arm {sa['return']['mean']:8.2f} (sd {sa['seed_sd']:4.1f}) "
                  f"ctl {sb['return']['mean']:8.2f} (sd {sb['seed_sd']:4.1f}) dRet {fmt_ci(c['return'])} "
                  f"dC {fmt_ci(c['sla_queue_c_pct'])} dHIGH {fmt_ci(c['sla_high_pct'], 3)} dLost {fmt_ci(c['lost_pct'])} "
                  f"dCVaR10 {fmt_ci(c['cvar10'])} seedRet {[round(x, 1) for x in sa['seed_returns']]}")
    return res


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "queue":
        print("\n".join(missing(sys.argv[2])))
    else:
        out = {"dev": table("dev"), "devshift": table("devshift", wraps=("pure",))}
        if "--write" in sys.argv:
            (E5 / "results" / "ablation.json").write_text(json.dumps(out, indent=1))
