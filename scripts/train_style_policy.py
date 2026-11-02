"""T30 (RL5): train the style policy OFFLINE (CPU / local only, 0 API calls).

    python -m scripts.train_style_policy --source synthetic --n 300 --seed 1
    python -m scripts.train_style_policy --source ratings          # after scripts.import_ratings
    python -m scripts.train_style_policy --source agent_f
    python -m scripts.train_style_policy --baselines               # step 6: the bandit vs fixed styles (synthetic)

The loop, one round at a time:  situation -> policy.choose -> reply in that style -> reward -> policy.update -> style_log

Where the situations come from: the 27 situations of the RL1 rating sheet (out/rl1_samples.json), rebuilt from the
traces of the runs they were taken from (out/t14b_after.json, out/t14c_practice_run1.json, out/t14c_heldout.json: run
OUTPUT files, the locked message files are not opened). Without the RL1 files: the practice runs' decisions.
The replies: the RL1 sheet already has each situation written in the 3 styles by the local SLM (--replies cached, the
default). --replies slm writes them again with the local SLM (slower, Ollama must run).

Rewards (callverse/learning/rewards.py), each with its label in style_log and in the outputs:
  synthetic  made-up world (warm best for angry clients, short for calm ones): a DEMO, not real learning
  ratings    the team's stars imported with scripts.import_ratings (style_log source = real); offline replay: a round
             only counts when that situation was rated in the chosen style
  agent_f    agent F's predicted satisfaction: today it ignores the style, so the script warns "nothing to learn"

Outputs: out/rl5_curve.csv (reward curve), out/rl5_policy.json (the policy the pipeline loads when the switch is on),
out/rl5_baselines.csv / .md with --baselines.
"""

import argparse
import csv
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from callverse.learning import rewards  # noqa: E402
from callverse.learning.situation import situation as situation_of  # noqa: E402
from callverse.learning.style_policy import STYLES, StylePolicy, group_of  # noqa: E402

OUT = ROOT / "out"
RUNS = ["out/t14b_after.json", "out/t14c_practice_run1.json", "out/t14c_heldout.json"]
PRACTICE_RUNS = RUNS[:2]


def _trace_cases(run_file: Path) -> dict[str, dict]:
    """{message id: {"ticket", "decision"}} for one earlier run: its result rows matched, in order, with the trace's
    tickets (intake_ticket) and the decision the SLM saw (pipeline_done). The channel renames ticket ids between the
    two events, so they are paired by order (one of each per message); a row whose reply does not match is skipped."""
    run = json.loads(run_file.read_text(encoding="utf-8"))
    trace_path = Path(run["summary"]["trace"])
    if not trace_path.exists():
        return {}
    tickets, done = [], []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event["step"] == "intake_ticket":
            tickets.append(event["data"])
        elif event["step"] == "pipeline_done":
            done.append(event["data"])
    if len(tickets) != len(done):
        return {}
    out = {}
    for row, ticket, d in zip(run["results"], tickets, done):
        if row.get("reply") == d.get("final_reply"):
            out[row["id"]] = {"ticket": ticket, "decision": d["decision"]}
    return out


def load_situations() -> list[dict]:
    """[{"situation_id", "situation", "ticket", "decision", "replies": {style: text}}]: the RL1 sheet's 27 when its files
    exist, else every practice-run decision (no cached replies: use --replies slm or the synthetic reward)."""
    samples_file = OUT / "rl1_samples.json"
    cases, runs = {}, RUNS if samples_file.exists() else PRACTICE_RUNS
    for run in runs:
        if (ROOT / run).exists():
            cases.update(_trace_cases(ROOT / run))
    replies: dict[str, dict] = {}
    if samples_file.exists():
        for s in json.loads(samples_file.read_text(encoding="utf-8")):
            replies.setdefault(s["situation_id"], {})[s["reply_style"]] = s["reply"]
        cases = {sid: c for sid, c in cases.items() if sid in replies}
    out = []
    for sid, c in cases.items():
        if c["decision"].get("action") == "redirect":
            continue   # fixed text: the style does not apply
        sit = situation_of(c["ticket"], c["decision"])
        out.append({"situation_id": sid, "situation": sit, "ticket": c["ticket"], "decision": c["decision"],
                    "replies": replies.get(sid, {})})
    return out


def write_reply(case: dict, style: str, mode: str) -> str:
    """The reply in this style: the RL1 sheet's cached one, or a new one from the local SLM."""
    if mode == "cached" and style in case["replies"]:
        return case["replies"][style]
    if mode == "none":
        return ""
    from callverse.slm import writer
    return writer.write_reply({**case["decision"], "reply_style": style})["reply"]   # local SLM (role "slm")


def agent_f_record(case: dict, style: str, reply: str) -> dict:
    return {"ticket_id": case["ticket"].get("ticket_id"), "company": case["situation"]["company"],
            "messages": [{"role": "user", "text": case["ticket"].get("text", "")}, {"role": "assistant", "text": reply}],
            "situation": case["situation"], "style": style, "decision": case["decision"], "reply": reply}


def real_ratings() -> dict[tuple[str, str], list[float]]:
    """{(situation_id, style): [rewards]} from style_log rows with source = real (scripts.import_ratings)."""
    from callverse.tickets import store
    found: dict[tuple[str, str], list[float]] = {}
    for r in store.style_log("real"):
        sid = r["situation"].get("situation_id")
        if sid is not None and r["reward"] is not None:
            found.setdefault((sid, r["style"]), []).append(float(r["reward"]))
    return found


def train(cases: list[dict], source: str, n: int, seed: int, replies: str = "cached", log: bool = True,
          policy: StylePolicy | None = None, evaluate=None) -> dict:
    """The offline loop. Returns {"policy", "curve": [rows], "warning": str | None, "used": rounds that counted}."""
    rng = random.Random(seed)
    policy = policy or StylePolicy()
    rated = real_ratings() if source == "ratings" else {}
    if source == "ratings":
        cases = [c for c in cases if any((c["situation_id"], s) in rated for s in STYLES)]
        if not rated or not cases:
            raise SystemExit("no real ratings in style_log: run python -m scripts.import_ratings <file> first")
    label = {"synthetic": "synthetic", "ratings": "real", "agent_f": "predicted"}[source]
    curve, seen, total, used = [], [], 0.0, 0
    for step in range(1, n + 1):
        case = rng.choice(cases)
        sit = case["situation"]
        style = policy.choose(sit, rng)
        reply = write_reply(case, style, replies if source != "ratings" else "cached")
        if source == "synthetic":
            reward = rewards.synthetic(sit, style, rng)
        elif source == "agent_f":
            reward = rewards.from_agent_f(agent_f_record(case, style, reply), evaluate=evaluate)
        else:
            options = rated.get((case["situation_id"], style))
            reward = rng.choice(options) if options else None   # replay: not rated in this style -> round skipped
        if reward is None:
            continue
        policy.update(sit, style, reward)
        used += 1
        total += reward
        seen.append({"situation_id": case["situation_id"], "style": style, "reward": reward})
        if log:
            from callverse.tickets import store
            store.add_style_log({**sit, "situation_id": case["situation_id"]}, group_of(sit), style, reply=reply,
                                reward=reward, source=label)
        curve.append({"round": step, "source": label, "situation_id": case["situation_id"], "group": group_of(sit),
                      "style": style, "reward": round(reward, 4), "mean_reward": round(total / used, 4)})
    warning = None
    if source == "agent_f" and rewards.constant_across_styles(seen):
        warning = "reward constant across styles -> nothing to learn (agent F ignores the reply style today)"
    return {"policy": policy, "curve": curve, "warning": warning, "used": used}


# --- step 6: baselines (synthetic world only) ---------------------------------------------------------------

def run_strategy(cases: list[dict], strategy: str, rounds: int, seed: int, means: dict | None = None) -> dict:
    """Mean reward and regret of one strategy over `rounds` rounds of the SYNTHETIC world.
    strategy = a style name (always that style), "random" or "bandit". Regret = best possible mean - what we got."""
    rng = random.Random(seed)
    policy = StylePolicy()
    total = best = 0.0
    for _ in range(rounds):
        sit = rng.choice(cases)["situation"]
        if strategy == "bandit":
            style = policy.choose(sit, rng)
        elif strategy == "random":
            style = rng.choice(STYLES)
        else:
            style = strategy
        reward = rewards.synthetic(sit, style, rng, means)
        if strategy == "bandit":
            policy.update(sit, style, reward)
        total += reward
        best += max(rewards.synthetic_mean(sit, s, means) for s in STYLES)
    return {"mean_reward": total / rounds, "regret": (best - total) / rounds}


def baselines(cases: list[dict], rounds: int = 300, seeds=(1, 2, 3), means: dict | None = None) -> list[dict]:
    rows = []
    for strategy in (*STYLES, "random", "bandit"):
        runs = [run_strategy(cases, strategy, rounds, seed, means) for seed in seeds]
        rows.append({"strategy": strategy, "source": "synthetic", "rounds": rounds, "seeds": len(seeds),
                     "mean_reward": round(sum(r["mean_reward"] for r in runs) / len(runs), 3),
                     "regret": round(sum(r["regret"] for r in runs) / len(runs), 3)})
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", choices=("synthetic", "ratings", "agent_f"), default="synthetic")
    ap.add_argument("--n", type=int, default=300, help="rounds")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--replies", choices=("cached", "slm", "none"), default="cached")
    ap.add_argument("--no-log", action="store_true", help="do not write style_log rows")
    ap.add_argument("--db", help="tickets DB file for style_log (default: callverse/data/callverse.db)")
    ap.add_argument("--baselines", action="store_true", help="step 6: bandit vs fixed styles vs random (synthetic)")
    args = ap.parse_args()
    if args.db:
        from callverse.tickets import store
        store.use_db(args.db)
    cases = load_situations()
    if not cases:
        raise SystemExit("no situations found (out/rl1_samples.json and the run traces are missing)")
    print(f"{len(cases)} situations, groups: {sorted({group_of(c['situation']) for c in cases})}")
    if args.baselines:
        rows = baselines(cases, args.n)
        write_csv(OUT / "rl5_baselines.csv", rows)
        flat = baselines(cases, args.n, means=rewards.FLAT_MEANS)
        lines = ["# RL5 baselines - SYNTHETIC reward (made-up world, not real learning)", "",
                 f"{args.n} rounds x 3 seeds, {len(cases)} RL1 situations. Synthetic world: warm best for angry "
                 "clients, short for calm ones (callverse/learning/rewards.py SYNTHETIC_MEANS).", "",
                 "| strategy | mean reward | regret |", "|---|---|---|"]
        lines += [f"| {r['strategy']} | {r['mean_reward']:.3f} | {r['regret']:.3f} |" for r in rows]
        lines += ["", "Flat world (all styles 0.6): the bandit must not break.", "",
                  "| strategy | mean reward | regret |", "|---|---|---|"]
        lines += [f"| {r['strategy']} | {r['mean_reward']:.3f} | {r['regret']:.3f} |" for r in flat]
        (OUT / "rl5_baselines.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines))
        return
    result = train(cases, args.source, args.n, args.seed, args.replies, log=not args.no_log,
                   policy=StylePolicy(OUT / "rl5_policy.json"))
    if result["warning"]:
        print(f"WARNING: {result['warning']}")
    if result["curve"]:
        write_csv(OUT / "rl5_curve.csv", result["curve"])
    path = result["policy"].save()
    label = {"synthetic": "SYNTHETIC", "ratings": "REAL", "agent_f": "PREDICTED"}[args.source]
    print(f"[{label}] {result['used']} rounds counted of {args.n}; policy -> {path}")
    for group, info in result["policy"].best_per_group().items():
        print(f"  {group:28s} best={info['best']:15s} n={info['n']:4d} mean={info['mean']}")


if __name__ == "__main__":
    main()
