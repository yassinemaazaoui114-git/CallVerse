"""RL evaluation (RL6) on SIMULATED feedback: satisfaction, correctness, reward, and style policies vs baselines.

Run: python -m benchmarks.agent_f.rl_eval [--generate-only] [--episodes N] [--seeds K]
Out: benchmarks/agent_f/results/rl_eval.json, data/simulated/agent_f/*.jsonl, models/agent_f/style_policy_*.json
Persona sets: TRAIN seed 101 (12 personas), VAL seed 202 (6), EVAL seed 303 (6), disjoint. Policies learn on TRAIN
episodes only and are scored greedily on EVAL personas. Satisfaction model = models/agent_f/stacker_selected.pkl
(chosen on VAL by compare_satisfaction.py) or, if missing, a Ridge candidate fitted here.
Everything is simulated: it shows the loop learns from its own simulator, NOT that real customers are happier.
"""
from __future__ import annotations

import json
import math
import pickle
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from benchmarks.agent_f.train_style import stats, train_and_validate
from callverse.data.atlas.seed import seed as seed_atlas
from callverse.data.seed import seed as seed_shopnova
from callverse.learning.simulator import build_dataset, make_personas, make_situations, record_for, write_jsonl
from callverse.learning.style_policy import (EpsilonGreedy, GaussianThompson, LinUCB, StylePolicy, agent_f_argmax,
                                             always, from_table, random_style, rule_based, supervised_group_policy)
from callverse.learning.style_writer import STYLES, write
from callverse.quality.reward import check_correctness, evaluate_response, reward_of
from callverse.quality.satisfaction import MODEL_DIR, TEXT_MODEL

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "benchmarks/agent_f/results"
DATA = ROOT / "data/simulated/agent_f"
SETS = {"train": (12, 101, 1), "val": (6, 202, 2), "eval": (6, 303, 3)}   # personas, persona seed, data seed
ALGOS = {"thompson_beta": lambda seed: StylePolicy(seed=seed),
         "gaussian_thompson": lambda seed: GaussianThompson(seed=seed),
         "linucb": lambda seed: LinUCB(alpha=0.5, seed=seed),
         "epsilon_greedy": lambda seed: EpsilonGreedy(epsilon=0.2, seed=seed)}
CONTINUOUS = {"gaussian_thompson", "linucb"}


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 1.0]
    p, d = k / n, 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 4), round(c + h, 4)]


def boot_ci(values, seed=0, n=1000) -> list[float]:
    rng, v = np.random.default_rng(seed), np.asarray(values, float)
    means = [rng.choice(v, len(v)).mean() for _ in range(n)]
    return [round(float(np.percentile(means, 2.5)), 4), round(float(np.percentile(means, 97.5)), 4)]


def by_company(rows, fn):
    out = {"all": fn(rows)}
    for c in ("shopnova", "atlas"):
        sub = [r for r in rows if r["company"] == c]
        if sub:
            out[c] = fn(sub)
    return out


def satisfaction_metrics(rows, base, stacker):
    y = [r["rating"] for r in rows]
    fixed = [evaluate_response(r, model=base, stacker=False)["satisfaction"] for r in rows]
    sel = [evaluate_response(r, model=base, stacker=stacker)["satisfaction"] for r in rows]
    return {"fixed_text_delay": stats(y, fixed), "selected_response_aware": stats(y, sel),
            "baseline_mean_rating": stats(y, [float(np.mean(y))] * len(y))}


def correctness_metrics(rows):
    tp = fp = fn = tn = unk = 0
    for r in rows:
        st = check_correctness(r)["status"]
        wrong = r["corruption"] is not None
        if st == "UNKNOWN":
            unk += 1
        elif st == "FAIL":
            tp += wrong; fp += (not wrong)
        else:
            fn += wrong; tn += (not wrong)
    n_wrong = sum(r["corruption"] is not None for r in rows)
    return {"n": len(rows), "n_wrong": n_wrong, "false_pass": fn, "false_pass_rate": round(fn / max(1, n_wrong), 4),
            "false_pass_95ci": wilson(fn, n_wrong), "fail_precision": round(tp / max(1, tp + fp), 4),
            "fail_recall": round(tp / max(1, tp + fn), 4), "unknown_rate": round(unk / len(rows), 4),
            "false_fail": fp, "clean_pass_rate": round(tn / max(1, tn + fp), 4)}


def reward_accuracy(rows, base, stacker):
    agree = total = 0
    for r in rows:
        out = evaluate_response(r, model=base, stacker=stacker)
        oracle = reward_of("FAIL" if r["corruption"] else "PASS", float(r["rating"]))
        if out["reward"] is None:
            continue
        total += 1; agree += out["reward"] == oracle
    return {"n": total, "agreement_with_oracle": round(agree / max(1, total), 4)}


def simulator_audit(rows):
    """Does the simulated rating respond to reply quality / style / mood? Mean rating per class."""
    def mean(sub):
        return round(float(np.mean([r["rating"] for r in sub])), 3) if sub else None
    quality = defaultdict(list)
    for r in rows:
        quality[r["corruption"] or r.get("degradation") or "clean"].append(r)
    style_mood = {f"{s}|{m}": mean([r for r in rows if r["style"] == s and r["corruption"] is None
                                     and (r["situation"]["sentiment"] == "negative") == (m == "upset")])
                  for s in STYLES for m in ("upset", "calm")}
    return {"by_reply_quality": {k: {"n": len(v), "mean_rating": mean(v)} for k, v in sorted(quality.items())},
            "clean_by_style_and_mood": style_mood}


def continuous_reward(out):
    if out["correctness"] == "UNKNOWN":
        return None
    return out["satisfaction"] if out["correctness"] == "PASS" else 1.0


def run_bandit(algo, personas, situations, base, stacker, reward_source, episodes, seed):
    """Online loop: situation x persona -> policy style -> writer -> Agent F -> reward -> update."""
    policy, rng = ALGOS[algo](seed), random.Random(seed)
    for _ in range(episodes):
        s, p = rng.choice(situations), rng.choice(personas)
        probe = record_for(s, p, "short", None, rng)                       # context only (reply unused)
        style = policy.choose(probe["situation"])
        rec = record_for(s, p, style, None, rng)
        if reward_source == "agent_f":
            out = evaluate_response(rec, model=base, stacker=stacker)
            reward = continuous_reward(out) if algo in CONTINUOUS else out["reward"]
        else:                                                               # the simulator's own rating as "real" feedback
            corr = check_correctness(rec)["status"]
            reward = (None if corr == "UNKNOWN" else (float(rec["rating"]) if corr == "PASS" else 1.0)) if algo in CONTINUOUS \
                else reward_of(corr, float(rec["rating"]))
        policy.update(rec["situation"], style, reward)
    return policy


def score_policy(pick, personas, situations, seed, with_verifier=False):
    """Greedy evaluation on EVAL personas, clean replies: ratings, satisfied share, e2e success, hallucination rate."""
    rng, ratings, success, fails = random.Random(seed), [], [], 0
    for p in personas:
        for s in situations:
            probe = record_for(s, p, "short", None, rng)
            style = pick(probe["situation"])
            rec = record_for(s, p, style, None, rng)
            ratings.append(rec["rating"])
            corr = check_correctness(rec)["status"] if with_verifier else "PASS"
            fails += corr == "FAIL"
            success.append(corr == "PASS" and rec["rating"] >= 4)
    out = {"n": len(ratings), "avg_rating": round(float(np.mean(ratings)), 4), "avg_rating_95ci": boot_ci(ratings, seed),
           "share_satisfied": round(float(np.mean([r >= 4 for r in ratings])), 4),
           "e2e_success_rate": round(float(np.mean(success)), 4)}
    if with_verifier:
        out["hallucination_rate"] = round(fails / len(ratings), 4)
    return out


def main(episodes=6000, seeds=(11, 12, 13, 14, 15)):
    situations, personas, rows = generate()
    base = pickle.loads(TEXT_MODEL.read_bytes())
    res = {"note": "ALL SIMULATED feedback (callverse/learning/simulator.py). Not evidence of real customer satisfaction.",
           "situations": len(situations), "personas": {k: len(v) for k, v in personas.items()},
           "rows": {k: len(v) for k, v in rows.items()}, "episodes": episodes, "seeds": list(seeds)}
    sel = MODEL_DIR / "stacker_selected.pkl"
    if sel.exists():
        stacker, res["satisfaction_model"] = pickle.loads(sel.read_bytes()), "stacker_selected.pkl (compare_satisfaction.py)"
    else:
        stacker, report = train_and_validate(rows["train"], base)
        res["satisfaction_model"], res["style_candidate_training"] = "ridge candidate (train_style)", report
        (MODEL_DIR / "stacker_candidate.pkl").write_bytes(pickle.dumps(stacker))

    res["satisfaction"] = {k: by_company(rows[k], lambda rs: satisfaction_metrics(rs, base, stacker)) for k in ("val", "eval")}
    res["simulator_audit_eval"] = simulator_audit(rows["eval"])
    res["correctness_eval"] = by_company(rows["eval"], correctness_metrics)
    res["reward_eval"] = {"fixed": reward_accuracy(rows["eval"], base, False), "selected": reward_accuracy(rows["eval"], base, stacker)}
    ms = []
    for r in rows["eval"][:300]:
        t = time.perf_counter(); evaluate_response(r, model=base, stacker=stacker); ms.append((time.perf_counter() - t) * 1000)
    res["latency_ms"] = {"evaluate_response_mean": round(float(np.mean(ms)), 2), "evaluate_response_p95": round(float(np.percentile(ms, 95)), 2)}

    # Fixed and supervised baselines.
    decision_of = {s["scenario_id"]: s["decision"] for s in situations}
    policies = {"always_short": always("short"), "always_apology_first": always("apology_first"),
                "always_apology_next_step": always("apology_next_step"), "random": random_style(7), "rule_based": rule_based,
                "supervised_group_train": from_table(supervised_group_policy(rows["train"])),
                "agent_f_argmax": agent_f_argmax(lambda rec: evaluate_response(rec, model=base, stacker=stacker)["satisfaction"],
                                                 write, lambda sit: decision_of[sit["scenario_id"]])}
    res["policies_eval"] = {}
    for name, pick in policies.items():
        res["policies_eval"][name] = score_policy(pick, personas["eval"], situations, seed=5, with_verifier=(name == "always_apology_next_step"))
        print(name, res["policies_eval"][name], flush=True)

    # Learned policies: algorithms x reward sources x seeds.
    res["bandits_eval"] = {}
    for algo in ALGOS:
        for src in ("agent_f", "simulated"):
            per_seed, t0 = [], time.perf_counter()
            for sd in seeds:
                pol = run_bandit(algo, personas["train"], situations, base, stacker, src, episodes, sd)
                per_seed.append(score_policy(pol.best, personas["eval"], situations, seed=5)["avg_rating"])
                if sd == seeds[0]:
                    pol.save(MODEL_DIR / f"style_policy_{algo}_{src}.json")
            m, sdv = float(np.mean(per_seed)), float(np.std(per_seed))
            res["bandits_eval"][f"{algo}|{src}"] = {"avg_rating_mean": round(m, 4), "avg_rating_std": round(sdv, 4),
                                                   "per_seed": [round(x, 4) for x in per_seed],
                                                   "train_s_per_seed": round((time.perf_counter() - t0) / len(seeds), 1)}
            print(algo, src, res["bandits_eval"][f"{algo}|{src}"], flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "rl_eval.json").write_text(json.dumps(res, indent=2))


def generate():
    """Seed both databases, build the three persona sets and their simulated feedback files."""
    seed_shopnova(); seed_atlas()
    situations = make_situations()
    personas = {k: make_personas(n, ps, k) for k, (n, ps, _) in SETS.items()}
    assert not ({p["id"] for p in personas["train"]} & {p["id"] for p in personas["eval"]})
    rows = {k: build_dataset(personas[k], SETS[k][2], situations=situations) for k in SETS}
    for k, rs in rows.items():
        write_jsonl(rs, DATA / f"{k}.jsonl")
    return situations, personas, rows


if __name__ == "__main__":
    if "--generate-only" in sys.argv:
        generate()
    else:
        ep = int(sys.argv[sys.argv.index("--episodes") + 1]) if "--episodes" in sys.argv else 6000
        k = int(sys.argv[sys.argv.index("--seeds") + 1]) if "--seeds" in sys.argv else 5
        main(episodes=ep, seeds=tuple(range(11, 11 + k)))
