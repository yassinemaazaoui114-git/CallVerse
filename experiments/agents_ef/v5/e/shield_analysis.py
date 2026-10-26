"""E2 - safety shield analysis on DEV (v5 evaluator rows with decision provenance + MPC agreement).

    python -m v5.e.shield_analysis      -> results/e2_shield.json + printed table
For each controller (with and without shield; RL and non-RL inners) it reports, per decision step (96 per day):
  removal rate      share of steps where the shield removed >= 1 valid action (shield "active")
  intervention rate share of steps where the EXECUTED action differs from what the same controller would have
                    executed without the shield (counterfactual call, same state)
  replacement rate  share of steps where a non-RL default replaced the action (rules only: shield_default)
  RL-own share      share of steps where the executed action is the RL's own greedy choice over the FULL mask
  RL-rechoice share share of steps where the RL chose inside the shielded mask (its first choice was removed)
  owner share       share of steps decided by the classical owner rule (guarded hybrids)
  MPC agreement     share of steps where the executed action equals Fluid MPC's action in the same state
                    (MPC-in-disguise check: MPC itself = 100 %)
and the paired effect of adding the shield (same seeds, same days): return, queue-C SLA, HIGH SLA, lost.
HARD constraints (enforced by masks; counted exactly, must be 0): invalid proposals reaching execution, HIGH tickets
on fallback, budget overrun days. ESTIMATED risk (statistical outcomes, no guarantee): queue-C SLA, HIGH SLA, lost.
"""

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from v5.e.analyze_v5 import E5, compare, day_ids, fmt_ci, load_rows, summary  # noqa: E402

STEPS = 96
DDQN = "dueling_double_dqn_equal_h64x64_150k"
DQN = "dueling_dqn_equal_h64x64_150k"
S10, S5 = range(10), range(5)

PAIRS = [   # (label, shielded specs, unshielded specs)
    ("pure Dueling DQN (V3)  + floor@3", [f"floor@3|rl:{DQN}_s{i}" for i in S5], [f"rl:{DQN}_s{i}" for i in S5]),
    ("pure Dueling DDQN (V3) + floor@3", [f"floor@3|rl:{DDQN}_s{i}" for i in S10], [f"rl:{DDQN}_s{i}" for i in S10]),
    ("pure Dueling DDQN (V3) + shield@0.2", [f"shield@0.2|rl:{DDQN}_s{i}" for i in S5], [f"rl:{DDQN}_s{i}" for i in S5]),
    ("V3 guarded (DDQN)      + floor@3", [f"floor@3|guarded:{DDQN}_s{i}" for i in S10], [f"guarded:{DDQN}_s{i}" for i in S10]),
    ("V3 guarded (DDQN)      + shield@0.2", [f"shield@0.2|guarded:{DDQN}_s{i}" for i in S5], [f"guarded:{DDQN}_s{i}" for i in S5]),
    ("MPC k=0.5              + floor@3", ["floor@3|rule:mpc:0.5"], ["rule:mpc:0.5"]),
    ("MPC k=0.5              + shield@0.2", ["shield@0.2|rule:mpc:0.5"], ["rule:mpc:0.5"]),
    ("Forecast z=0.25        + floor@3", ["floor@3|rule:forecast:0.25"], ["rule:forecast:0.25"]),
    ("Forecast z=0.25        + shield@0.2", ["shield@0.2|rule:forecast:0.25"], ["rule:forecast:0.25"]),
]


def rates(rows, specs):
    out = {}
    tot = sum(len(rows[s]) for s in specs) * STEPS
    for k, col in (("removal", "n_removed"), ("intervention", "n_intervened"), ("replacement", "n_prov_shield_default"),
                   ("rl_own", "n_prov_rl"), ("rl_rechoice", "n_prov_rl_rechoice"), ("owner", "n_prov_owner"),
                   ("rule", "n_prov_rule"), ("mpc_agree", "n_agree_mpc"), ("flips_per_day", "n_flip")):
        if col not in rows[specs[0]][0]:
            out[k] = None
            continue
        v = sum(r[col] for s in specs for r in rows[s])
        out[k] = v / (tot / STEPS) if k == "flips_per_day" else 100.0 * v / tot
    out["hard_violations"] = {"invalid_proposals": int(sum(r["invalid_proposals"] for s in specs for r in rows[s])),
                              "high_on_fallback": int(sum(r["high_on_fallback"] for s in specs for r in rows[s])),
                              "budget_overrun_days": int(sum(1 - r["budget_ok"] for s in specs for r in rows[s]))}
    return out


def main():
    rows = load_rows("dev", with_v4=False)
    days = day_ids("dev")
    res = []
    for label, sh, un in PAIRS:
        if not all(s in rows for s in sh + un):
            print("missing rows for", label)
            continue
        ent = {"label": label, "shielded": sh, "unshielded": un, "rates_shielded": rates(rows, sh),
               "rates_unshielded": rates(rows, un), "summary_shielded": summary(rows, sh, days, n_boot=300),
               "summary_unshielded": summary(rows, un, days, n_boot=300),
               "effect_of_shield": compare(rows, sh, un, days, n_boot=1000)}
        res.append(ent)
        r, e = ent["rates_shielded"], ent["effect_of_shield"]
        f = lambda x: "  -  " if x is None else f"{x:5.1f}"
        print(f"{label:38s} removal {f(r['removal'])} interv {f(r['intervention'])} repl {f(r['replacement'])} "
              f"rl_own {f(r['rl_own'])} rechoice {f(r['rl_rechoice'])} owner {f(r['owner'])} mpc_agree {f(r['mpc_agree'])}"
              f" (unshielded mpc_agree {f(ent['rates_unshielded']['mpc_agree'])}) | dRet {fmt_ci(e['return'])} "
              f"dC {fmt_ci(e['sla_queue_c_pct'])} dHIGH {fmt_ci(e['sla_high_pct'], 3)} hard {r['hard_violations']}")
    (E5 / "results" / "e2_shield.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
