"""E1 - why is RL not reliably better than MPC?  Diagnosis from saved checkpoints + new rollouts (VAL / DEV only).

    python -m v4.e.diagnose_v4 traces      # (1) per-step trajectories on V3 VAL (48 days) for the diagnosed policies
    python -m v4.e.diagnose_v4 analyse     # (2) figures/ + results/diagnosis.json from traces, DEV rows, run logs
    python -m v4.e.diagnose_v4 tfrac       # (3) time-of-day ablation of the RL input on VAL
    python -m v4.e.diagnose_v4 qgap        # (4) Q-value gaps: how strongly does the net prefer its choice?
V3 TEST rows are read ONLY in 'analyse' for a DESCRIPTIVE per-queue table, labelled as such; nothing is tuned on them.
"""

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
from v4.e.common import E4, QC, EnvV4, load_agent, load_manifest, masked_argmax, q_values  # noqa: E402
from v4.e.evaluate_v4 import eval_policy, fname  # noqa: E402

FIG, RES = E4 / "figures", E4 / "results"
DDQN = [f"dueling_double_dqn_equal_h64x64_150k_s{i}" for i in range(5)]
DUEL = [f"dueling_dqn_equal_h64x64_150k_s{i}" for i in range(5)]
RULES = ["rule:mpc:0.5", "rule:forecast:0.25", "rule:erlang:0.4"]
TRACED = RULES + [f"rl:{r}" for r in DDQN + DUEL] + [f"guarded:{r}" for r in DDQN[:3]]
Q_NAMES = ["A", "B", "C", "D"]
TF_IDX, BUDGET_IDX = 28, 27            # obs index of t / steps_per_day, and of remaining budget share


def read_trace(spec, split="val"):
    p = RES / f"eval_{split}" / (fname(spec) + ".trace.jsonl")
    return [json.loads(l) for l in open(p)]


def read_rows(spec, split):
    p = RES / f"eval_{split}" / (fname(spec) + ".csv")
    rows = list(csv.DictReader(open(p)))
    for r in rows:
        for k, v in r.items():
            if k not in ("policy", "day_id", "family"):
                r[k] = float(v) if v not in ("True", "False") else float(v == "True")
    return rows


def traces():
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(2) as ex:
        for spec, st in ex.map(eval_policy, [(s, "val", True) for s in TRACED]):
            print(spec, st, flush=True)


def group(spec):
    if spec.startswith("rule:"):
        return spec
    import re
    return re.sub(r"_s\d+", "", spec)


def analyse():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    FIG.mkdir(exist_ok=True)
    out = {}
    # ---------- (a) action distribution + (b) time-of-day profiles (VAL traces)
    from env.callcenter_env import A_ACT, A_DEACT, A_FB_OFF, A_FB_ON, A_KEEP, MOVES
    prof = defaultdict(lambda: defaultdict(list))
    actd = defaultdict(lambda: defaultdict(float))
    qfail = defaultdict(lambda: np.zeros(4))
    parts = defaultdict(lambda: defaultdict(float))
    ndays = defaultdict(int)
    for spec in TRACED:
        g = group(spec)
        for day in read_trace(spec):
            ndays[g] += 1
            T = len(day["steps"])
            ca, tot, cb, ch = np.zeros(T), np.zeros(T), np.zeros(T), np.zeros(T)
            for k, s in enumerate(day["steps"]):
                a = s["a"]
                kind = ("keep" if a == A_KEEP else "move_into_C" if 1 <= a <= 12 and MOVES[a - 1][1] == QC else
                        "move_out_of_C" if 1 <= a <= 12 and MOVES[a - 1][0] == QC else "move_other" if 1 <= a <= 12
                        else {A_FB_ON: "fallback_on", A_FB_OFF: "fallback_off", A_ACT: "activate", A_DEACT: "deactivate"}[a])
                actd[g][kind] += 1
                ca[k], tot[k], cb[k], ch[k] = s["alloc"][QC], sum(s["alloc"]), s["backlog"][QC], s["c_high_wait"]
                qfail[g] += np.array(s["qfail"])
                for pk in ("sla_fail", "abandon", "cost"):
                    parts[g][pk] += s["parts"][pk]
                parts[g]["fallback_steps"] += s["fb"]
            prof[g]["c_alloc"].append(ca)
            prof[g]["total"].append(tot)
            prof[g]["c_backlog"].append(cb)
            prof[g]["c_high_waiting"].append(ch)
    groups = list(prof)
    act_share = {g: {k: v / sum(actd[g].values()) for k, v in sorted(actd[g].items())} for g in groups}
    F = 1.9469791666666666
    per_queue = {g: {"fail_per_day": dict(zip(Q_NAMES, (qfail[g] / ndays[g]).round(2).tolist())),
                     "reward_from_failures_per_queue": dict(zip(Q_NAMES, (-qfail[g] / ndays[g] / F).round(2).tolist())),
                     "reward_parts_per_day": {k: round(-v / ndays[g], 2) for k, v in parts[g].items() if k != "fallback_steps"},
                     "fallback_steps_per_day": round(parts[g]["fallback_steps"] / ndays[g], 2)} for g in groups}
    out["val_action_share"] = act_share
    out["val_per_queue"] = per_queue
    out["val_profiles_mean"] = {g: {k: np.mean(v, 0).round(3).tolist() for k, v in prof[g].items()} for g in groups}
    show = ["rule:mpc:0.5", "rule:forecast:0.25", "rule:erlang:0.4", "rl:dueling_double_dqn_equal_h64x64_150k",
            "rl:dueling_dqn_equal_h64x64_150k", "guarded:dueling_double_dqn_equal_h64x64_150k"]
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    hours = (np.arange(96) + 0.5) * 5 / 60
    for ax, key, lab in zip(axes.flat, ["c_alloc", "total", "c_backlog", "c_high_waiting"],
                            ["sessions on queue C", "active sessions (all queues)", "queue-C tickets waiting",
                             "HIGH tickets waiting in C"]):
        for g in show:
            ax.plot(hours, np.mean(prof[g][key], 0), label=g.replace("_equal_h64x64_150k", ""))
        ax.set_xlabel("hour of the 8-hour day")
        ax.set_ylabel(lab)
        ax.set_title(f"V3 VAL (48 days): {lab}, mean over days (RL: 5 seeds)")
    axes[0, 0].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(FIG / "e1_time_of_day_profiles.png", dpi=110)
    plt.close(fig)
    # action shares figure
    kinds = ["keep", "move_into_C", "move_out_of_C", "move_other", "activate", "deactivate", "fallback_on", "fallback_off"]
    fig, ax = plt.subplots(figsize=(11, 4.5))
    w = 0.8 / len(show)
    for i, g in enumerate(show):
        ax.bar(np.arange(len(kinds)) + i * w, [100 * act_share[g].get(k, 0) for k in kinds], w,
               label=g.replace("_equal_h64x64_150k", ""))
    ax.set_xticks(np.arange(len(kinds)) + 0.4, kinds)
    ax.set_ylabel("% of decisions")
    ax.set_yscale("log")
    ax.set_title("V3 VAL: what each policy does (share of the 96 decisions/day; log scale)")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(FIG / "e1_action_distribution.png", dpi=110)
    plt.close(fig)
    # ---------- (c) DEV: per-family, per-rho, queue-C metrics
    dev = {}
    for f in sorted((RES / "eval_dev").glob("*.csv")):
        rows = list(csv.DictReader(open(f)))
        dev[rows[0]["policy"]] = read_rows(rows[0]["policy"], "dev")
    gdev = defaultdict(list)
    for s in dev:
        gdev[group(s)].append(s)
    keys = ["return", "sla_pct", "sla_high_pct", "sla_queue_c_pct", "lost_pct", "cost", "c_alloc_mean", "alloc_mean",
            "fallback_share", "n_move_into_c", "n_move_out_c", "n_act", "n_deact"]
    dev_board = {}
    for g, specs in gdev.items():
        M = {k: np.mean([[r[k] for r in dev[s]] for s in specs]) for k in keys}
        dev_board[g] = {"n_seeds": len(specs), **{k: round(float(v), 3) for k, v in M.items()},
                        "seed_returns": [round(float(np.mean([r["return"] for r in dev[s]])), 2) for s in specs]}
    out["dev_board"] = dev_board
    mpc = {r["day_id"]: r for r in dev["rule:mpc:0.5"]}
    fams = sorted({r["family"] for r in dev["rule:mpc:0.5"]}, key=lambda f: [r["family"] for r in dev["rule:mpc:0.5"]].index(f))
    rho_b = lambda r: "rho<0.85" if r < 0.85 else ("0.85-1.05" if r <= 1.05 else ">1.05")
    fam_diff, rho_diff = {}, {}
    for g in ["rl:dueling_double_dqn_equal_h64x64_150k", "rl:dueling_dqn_equal_h64x64_150k",
              "guarded:dueling_double_dqn_equal_h64x64_150k", "rule:forecast:0.25", "rule:erlang:0.4"]:
        if g not in gdev:
            continue
        fd, rd = defaultdict(list), defaultdict(list)
        for s in gdev[g]:
            for r in dev[s]:
                m = mpc[r["day_id"]]
                fd[r["family"]].append((r["return"] - m["return"], r["sla_queue_c_pct"] - m["sla_queue_c_pct"]))
                rd[rho_b(m["rho"])].append((r["return"] - m["return"], r["sla_queue_c_pct"] - m["sla_queue_c_pct"]))
        fam_diff[g] = {f: np.mean(fd[f], 0).round(2).tolist() for f in fams}
        rho_diff[g] = {b: np.mean(v, 0).round(2).tolist() + [len(v)] for b, v in rd.items()}
    out["dev_family_diff_vs_mpc"] = fam_diff
    out["dev_rho_diff_vs_mpc"] = rho_diff
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8))
    for ax, idx, lab in ((axes[0], 0, "return difference vs MPC (per day)"), (axes[1], 1, "queue-C SLA difference vs MPC (pp)")):
        names = list(fam_diff)
        M = np.array([[fam_diff[n][f][idx] for f in fams] for n in names])
        lim = np.abs(M).max()
        ax.imshow(M, cmap="RdYlGn", vmin=-lim, vmax=lim, aspect="auto")
        ax.set_xticks(range(len(fams)), fams, rotation=45, ha="right", fontsize=7)
        ax.set_yticks(range(len(names)), [n.replace("_equal_h64x64_150k", "") for n in names], fontsize=7)
        for i in range(len(names)):
            for j in range(len(fams)):
                ax.text(j, i, f"{M[i, j]:+.1f}", ha="center", va="center", fontsize=6)
        ax.set_title(f"DEV (104 days): {lab}")
    fig.tight_layout()
    fig.savefig(FIG / "e1_dev_family_diff.png", dpi=110)
    plt.close(fig)
    # ---------- (d) training stability: VAL curves across seeds (V3 run logs)
    stab = {}
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for algo, col in (("dueling_double_dqn", "C0"), ("dueling_dqn", "C1"), ("dqn", "C2"), ("double_dqn", "C3")):
        curves = []
        for d in sorted((HERE / "v3/e/runs").glob(f"{algo}_equal_h64x64_150k_s?")):
            r = list(csv.DictReader(open(d / "val_log.csv")))
            curves.append([float(x["val_return"]) for x in r])
            ax.plot([int(x["step"]) for x in r], curves[-1], color=col, alpha=0.35, lw=0.8)
        C = np.array(curves)
        stab[algo] = {"n_seeds": len(C), "final_mean": round(float(C[:, -1].mean()), 2), "final_sd": round(float(C[:, -1].std()), 2),
                      "best_mean": round(float(C.max(1).mean()), 2), "best_minus_final": round(float((C.max(1) - C[:, -1]).mean()), 2),
                      "mean_abs_change_between_evals_last5": round(float(np.abs(np.diff(C[:, -5:], axis=1)).mean()), 2),
                      "argbest_eval_index": C.argmax(1).tolist()}
        ax.plot([], [], color=col, label=f"{algo} (n={len(C)})")
    ax.axhline(-178.3, ls="--", color="k", lw=1, label="MPC k=0.5 on VAL (-178.3)")
    ax.set_xlabel("environment steps")
    ax.set_ylabel("VAL return (48 days)")
    ax.set_ylim(-260, -170)
    ax.set_title("V3 learning curves, every seed (VAL): oscillation between evaluations")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(FIG / "e1_training_stability.png", dpi=110)
    plt.close(fig)
    out["training_stability"] = stab
    # ---------- (e) DESCRIPTIVE V3-TEST per-queue view (read-only, no tuning)
    desc = {}
    for spec in ["rule:mpc:0.5", "guarded:dueling_double_dqn_equal_h64x64_150k_s0", "rl:dueling_double_dqn_equal_h64x64_150k_s0"]:
        p = HERE / "v3/e/results/eval_test" / (spec.replace(":", "__") + ".csv")
        rows = list(csv.DictReader(open(p)))
        desc[spec] = {k: round(float(np.mean([float(r[k]) for r in rows])), 3) for k in ("sla_queue_c_pct", "sla_high_pct", "cost", "lost_pct")}
    out["v3_test_descriptive_only"] = desc
    (RES / "diagnosis.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ("val_per_queue", "training_stability")}, indent=1)[:6000])


def tfrac():
    """Replace the time-of-day input (obs[28]) and the remaining-budget input (obs[27], also a clock) and measure
    the change in return and in decisions. If RL relied on 'what time it is' instead of the queue state, it would
    have memorised the TRAIN demand shapes - a reason it extrapolates badly to new shapes."""
    days = load_manifest("val")
    res = {}
    perturb = {"none": lambda o: o, "t=0.5": lambda o: _set(o, TF_IDX, 0.5), "t+0.25": lambda o: _add(o, TF_IDX, 0.25),
               "t-0.25": lambda o: _add(o, TF_IDX, -0.25), "t=0.5,budget=0.5": lambda o: _set(_set(o, TF_IDX, 0.5), BUDGET_IDX, 0.5)}
    for run in DDQN[:3] + DUEL[:3]:
        ag, _, _ = load_agent(run)
        env = EnvV4()
        for name, fn in perturb.items():
            R, agree, n = [], 0, 0
            for d in days:
                obs, info = env.reset(seed=d["seed"], family=d["family"])
                done, tot = False, 0.0
                while not done:
                    q = q_values(ag, fn(obs))
                    a = masked_argmax(q, info["action_mask"])
                    agree += int(a == masked_argmax(q_values(ag, obs), info["action_mask"]))
                    n += 1
                    obs, r, done, _, info = env.step(a)
                    tot += r
                R.append(tot)
            res.setdefault(run, {})[name] = {"val_return": round(float(np.mean(R)), 2), "same_decision_pct": round(100 * agree / n, 2)}
        print(run, res[run], flush=True)
    (RES / "diag_tfrac.json").write_text(json.dumps(res, indent=1))


def _set(o, i, v):
    o = o.copy()
    o[i] = v
    return o


def _add(o, i, v):
    o = o.copy()
    o[i] = np.clip(o[i] + v, 0, 1)
    return o


def qgap():
    """For each decision on VAL: gap between the best and 2nd-best valid Q-value, and the Q-value loss of the
    best move INTO queue C. Q-values are in return units (sum of future rewards), so a gap of 0.06 = the cost of one
    session for one step. Tiny gaps = the net is close to indifferent = noisy, seed-dependent decisions."""
    from env.callcenter_env import MOVES
    days = load_manifest("val")[::2]
    res = {}
    for run in DDQN[:3] + DUEL[:3]:
        ag, _, _ = load_agent(run)
        env = EnvV4()
        gaps, into_c_loss, c_backlog = [], [], []
        for d in days:
            obs, info = env.reset(seed=d["seed"], family=d["family"])
            done = False
            while not done:
                m = info["action_mask"]
                q = np.where(m, q_values(ag, obs), -np.inf)
                srt = np.sort(q[np.isfinite(q)])[::-1]
                if len(srt) > 1:
                    gaps.append(srt[0] - srt[1])
                ups = [a for a in range(1, 13) if m[a] and MOVES[a - 1][1] == QC]
                if ups:
                    into_c_loss.append(srt[0] - max(q[a] for a in ups))
                    c_backlog.append(len(env.queue[QC]))
                obs, r, done, _, info = env.step(int(np.argmax(q)))
        gaps, il, cb = np.array(gaps), np.array(into_c_loss), np.array(c_backlog)
        res[run] = {"median_gap_best_vs_2nd": round(float(np.median(gaps)), 4),
                    "share_gap_below_one_session_step": round(float((gaps < 1 / 16).mean()), 3),
                    "median_q_loss_best_move_into_C": round(float(np.median(il)), 4),
                    "median_q_loss_move_into_C_when_C_backlog>=3": round(float(np.median(il[cb >= 3])), 4) if (cb >= 3).any() else None,
                    "share_steps_C_backlog>=3": round(float((cb >= 3).mean()), 3)}
        print(run, res[run], flush=True)
    (RES / "diag_qgap.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    if sys.argv[1] != "figs2":
        {"traces": traces, "analyse": analyse, "tfrac": tfrac, "qgap": qgap}[sys.argv[1]]()


def figs2():
    """Figures from diagnosis.json, diag_tfrac.json, diag_qgap.json (real data only)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    d = json.loads((RES / "diagnosis.json").read_text())
    show = ["rule:mpc:0.5", "rule:erlang:0.4", "rule:forecast:0.25", "rl:dueling_double_dqn_equal_h64x64_150k",
            "rl:dueling_dqn_equal_h64x64_150k", "guarded:dueling_double_dqn_equal_h64x64_150k"]
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.5))
    w = 0.8 / len(show)
    for i, g in enumerate(show):
        f = d["val_per_queue"][g]["fail_per_day"]
        axes[0].bar(np.arange(4) + i * w, [f[q] for q in Q_NAMES], w, label=g.replace("_equal_h64x64_150k", ""))
    axes[0].set_xticks(np.arange(4) + 0.4, ["queue A", "queue B", "queue C (urgent)", "queue D"])
    axes[0].set_ylabel("failed tickets per day (SLA miss + lost)")
    axes[0].set_title("V3 VAL: where each policy fails")
    axes[0].legend(fontsize=7)
    tf = json.loads((RES / "diag_tfrac.json").read_text())
    names = list(next(iter(tf.values())))
    for run, v in tf.items():
        axes[1].plot(names, [v[n]["val_return"] - v["none"]["val_return"] for n in names], "o-", label=run.replace("_equal_h64x64_150k", ""))
    axes[1].set_ylabel("VAL return change vs unperturbed")
    axes[1].set_title("time-of-day input perturbed (obs[28], obs[27])")
    axes[1].tick_params(axis="x", rotation=20)
    axes[1].legend(fontsize=6)
    qg = json.loads((RES / "diag_qgap.json").read_text())
    runs = list(qg)
    axes[2].bar(np.arange(len(runs)) - 0.2, [qg[r]["share_gap_below_one_session_step"] for r in runs], 0.4,
                label="share of decisions with Q-gap < 1 session-step")
    axes[2].bar(np.arange(len(runs)) + 0.2, [qg[r]["median_q_loss_move_into_C_when_C_backlog>=3"] for r in runs], 0.4,
                label="median Q-value penalty of moving into C when >=3 C tickets wait")
    axes[2].set_xticks(range(len(runs)), [r.replace("_equal_h64x64_150k", "") for r in runs], rotation=30, ha="right", fontsize=7)
    axes[2].set_title("RL value estimates: indifference and C under-valuation")
    axes[2].legend(fontsize=6)
    fig.tight_layout()
    fig.savefig(FIG / "e1_queue_fail_tfrac_qgap.png", dpi=110)
    plt.close(fig)


if __name__ == "__main__" and sys.argv[1] == "figs2":
    figs2()
