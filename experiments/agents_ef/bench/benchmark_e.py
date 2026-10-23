"""Final Agent E comparison on the held-out TEST days (never used for training or choices).

    python -m bench.benchmark_e --runs results/runs --out results/agent_e
For every heuristic and every trained run (its VAL-chosen best.pt): KPIs per scenario and overall, mean +- std over
training seeds, decision latency on CPU (batch 1), parameters, checkpoint size. Writes summary.json, test_rows.csv
and plots (learning curves, KPI bars). SIMULATOR results only.
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from baselines.heuristics import BASELINES  # noqa: E402
from bench.evaluation import KPI_KEYS, SPLITS, evaluate, summarize  # noqa: E402
from env.callcenter_env import CallCenterEnv  # noqa: E402
from rl.agents import make_agent  # noqa: E402

HEADLINE = ["ret", "sla_pct", "urgent_sla_pct", "abandon_pct", "mean_wait_min", "p95_wait_min", "sim_csat", "cost",
            "violations"]


def load_run(run_dir: Path):
    info = json.loads((run_dir / "run.json").read_text())
    env = CallCenterEnv()
    agent = make_agent(info["algo"], env.obs_dim, env.n_actions, info["seed"], hidden=tuple(info["hidden"]))
    state = torch.load(run_dir / "best.pt", weights_only=False)
    agent.load_state_dict(state)
    return info, agent


def score(policy, preset, calibration=None):
    from real_data.calibration import env_config
    env = CallCenterEnv(env_config(preset, calibration), scenarios=SPLITS["test"]["scenarios"])
    times = []
    rows = evaluate(policy, "test", env, decision_times=times)
    return rows, float(np.median(times) * 1e3), float(np.percentile(times, 95) * 1e3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="results/runs")
    ap.add_argument("--out", default="results/agent_e")
    ap.add_argument("--preset", default="balanced")
    ap.add_argument("--filter", default="", help="only runs whose folder contains this text")
    ap.add_argument("--calibration", default=None, help="score on the real-data-calibrated simulator")
    a = ap.parse_args()
    torch.set_num_threads(1)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    per_policy, csv_rows = defaultdict(list), []

    for name, P in BASELINES.items():
        p = P()
        rows, lat50, lat95 = score(lambda env, obs, mask: p.act(env, obs, mask), a.preset, a.calibration)
        per_policy[name].append({"rows": rows, "lat50": lat50, "lat95": lat95, "n_params": 0, "disk_kb": 0,
                                 "train_s": 0, "seed": 0})

    for run_dir in sorted(Path(a.runs).glob("*")):
        if not (run_dir / "best.pt").exists() or a.filter not in run_dir.name:
            continue
        info, agent = load_run(run_dir)
        if info["preset"] != a.preset:
            continue
        key = f"{info['algo']}_h{'x'.join(map(str, info['hidden']))}" + (run_dir.name.split(f"_s{info['seed']}")[-1])
        rows, lat50, lat95 = score(lambda env, obs, mask: agent.act(obs, mask, explore=False), a.preset, a.calibration)
        per_policy[key].append({"rows": rows, "lat50": lat50, "lat95": lat95, "n_params": info["n_params"],
                                "disk_kb": round((run_dir / "best.pt").stat().st_size / 1024, 1),
                                "train_s": info["train_wall_s"], "seed": info["seed"]})

    summary = {}
    for name, runs in per_policy.items():
        overall = [summarize(r["rows"]) for r in runs]                    # one summary per training seed
        by_sc = defaultdict(list)
        for r in runs:
            for row in r["rows"]:
                by_sc[row["scenario"]].append(row)
                csv_rows.append({"policy": name, "seed": r["seed"], **{k: row[k] for k in ["scenario"] + KPI_KEYS}})
        summary[name] = {
            "n_seeds": len(runs),
            "mean": {k: float(np.mean([o[k] for o in overall])) for k in HEADLINE},
            "std_over_seeds": {k: float(np.std([o[k] for o in overall])) for k in HEADLINE},
            "by_scenario_ret": {sc: float(np.mean([x["ret"] for x in v])) for sc, v in by_sc.items()},
            "by_scenario_sla": {sc: float(np.mean([x["sla_pct"] for x in v])) for sc, v in by_sc.items()},
            "budget_ok_pct": float(np.mean([o["budget_ok_pct"] for o in overall])),
            "decision_latency_ms_p50": float(np.mean([r["lat50"] for r in runs])),
            "decision_latency_ms_p95": float(np.mean([r["lat95"] for r in runs])),
            "n_params": runs[0]["n_params"], "checkpoint_kb": runs[0]["disk_kb"],
            "train_s_mean": float(np.mean([r["train_s"] for r in runs])),
        }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    with open(out / "test_rows.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(csv_rows[0]))
        w.writeheader()
        w.writerows(csv_rows)

    order = sorted(summary, key=lambda k: -summary[k]["mean"]["ret"])
    print(f"{'policy':34s} {'ret':>14s} {'SLA%':>6s} {'urgSLA':>6s} {'aband%':>6s} {'wait':>5s} {'p95':>5s} "
          f"{'csat':>5s} {'cost':>6s} {'viol':>4s} {'compound':>8s} {'params':>7s} {'ms':>6s}")
    for k in order:
        m, s = summary[k]["mean"], summary[k]["std_over_seeds"]
        print(f"{k:34s} {m['ret']:7.2f}±{s['ret']:5.2f} {m['sla_pct']:6.2f} {m['urgent_sla_pct']:6.2f} "
              f"{m['abandon_pct']:6.2f} {m['mean_wait_min']:5.2f} {m['p95_wait_min']:5.1f} {m['sim_csat']:5.3f} "
              f"{m['cost']:6.0f} {m['violations']:4.1f} {summary[k]['by_scenario_ret'].get('compound', 0):8.2f} "
              f"{summary[k]['n_params']:7d} {summary[k]['decision_latency_ms_p50']:6.3f}")
    plots(Path(a.runs), out, summary, order)


def plots(runs_dir: Path, out: Path, summary, order):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    curves = defaultdict(list)
    for d in runs_dir.glob("*"):
        if (d / "val_log.csv").exists():
            info = json.loads((d / "run.json").read_text())
            rows = list(csv.DictReader(open(d / "val_log.csv")))
            curves[f"{info['algo']}_{info['preset']}_h{'x'.join(map(str, info['hidden']))}"].append(
                ([int(r["step"]) for r in rows], [float(r["ret"]) for r in rows]))
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for name, cs in sorted(curves.items()):
        n = min(len(c[1]) for c in cs)
        ys = np.array([c[1][:n] for c in cs])
        ax.plot(cs[0][0][:n], ys.mean(0), label=f"{name} (n={len(cs)})")
        ax.fill_between(cs[0][0][:n], ys.min(0), ys.max(0), alpha=0.15)
    for b in BASELINES:
        if b in summary:
            ax.axhline(summary[b]["mean"]["ret"], ls="--", lw=0.8, color="grey")
    ax.set_xlabel("environment steps")
    ax.set_ylabel("VAL return (greedy)")
    ax.set_title("Agent E learning curves (simulator; dashed = heuristics on TEST)")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out / "learning_curves.png", dpi=110)
    fig, axes = plt.subplots(1, 3, figsize=(12, 4))
    for ax, key in zip(axes, ["ret", "sla_pct", "cost"]):
        vals = [summary[k]["mean"][key] for k in order]
        errs = [summary[k]["std_over_seeds"][key] for k in order]
        ax.barh(order, vals, xerr=errs)
        ax.set_title(f"TEST {key}")
        ax.tick_params(labelsize=7)
    fig.tight_layout()
    fig.savefig(out / "test_kpis.png", dpi=110)


if __name__ == "__main__":
    main()
