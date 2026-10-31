"""RL evaluation (RL6) on SIMULATED feedback: satisfaction model, correctness verifier, dual reward, bandit vs baselines.

Run: python -m benchmarks.agent_f.rl_eval  ->  benchmarks/agent_f/results/rl_eval.json, data/simulated/agent_f/*.jsonl
Persona sets: TRAIN seed 101 (12 personas), VAL seed 202 (6), EVAL seed 303 (6). The style candidate is fitted on
TRAIN only (train_style.train_and_validate: its own persona-disjoint dev split picks alpha); VAL/EVAL are only read.
Everything here is simulated: it shows the pipeline learns from its own simulator, NOT that real customers are happier.
"""
from __future__ import annotations

import json
import pickle
import random
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from benchmarks.agent_f.train_style import stats, train_and_validate
from callverse.data.atlas.seed import seed as seed_atlas
from callverse.data.seed import seed as seed_shopnova
from callverse.learning.simulator import build_dataset, make_personas, make_situations, record_for, write_jsonl
from callverse.learning.style_policy import StylePolicy, always, random_style, rule_based
from callverse.learning.style_writer import STYLES
from callverse.quality.reward import check_correctness, evaluate_response, reward_of
from callverse.quality.satisfaction import MODEL_DIR, TEXT_MODEL

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "benchmarks/agent_f/results"
DATA = ROOT / "data/simulated/agent_f"
SETS = {"train": (12, 101, 1), "val": (6, 202, 2), "eval": (6, 303, 3)}   # personas, persona seed, data seed


def by_company(rows, fn):
    out = {"all": fn(rows)}
    for c in ("shopnova", "atlas"):
        sub = [r for r in rows if r["company"] == c]
        if sub:
            out[c] = fn(sub)
    return out


def satisfaction_metrics(rows, base, candidate):
    y = [r["rating"] for r in rows]
    fixed = [evaluate_response(r, model=base, stacker=False)["satisfaction"] for r in rows]
    cand = [evaluate_response(r, model=base, stacker=candidate)["satisfaction"] for r in rows]
    return {"fixed_text_delay": stats(y, fixed), "style_candidate": stats(y, cand),
            "baseline_mean_rating": stats(y, [float(np.mean(y))] * len(y))}


def correctness_metrics(rows):
    tp = fp = fn = tn = unk = false_pass = 0
    for r in rows:
        st = check_correctness(r)["status"]
        wrong = r["corruption"] is not None
        if st == "UNKNOWN":
            unk += 1
        elif st == "FAIL":
            tp += wrong; fp += (not wrong)
        else:
            fn += wrong; tn += (not wrong); false_pass += wrong
    n_wrong = sum(r["corruption"] is not None for r in rows)
    return {"n": len(rows), "n_wrong": n_wrong, "fail_precision": round(tp / max(1, tp + fp), 4),
            "fail_recall": round(tp / max(1, tp + fn), 4), "false_pass_rate": round(false_pass / max(1, n_wrong), 4),
            "unknown_rate": round(unk / len(rows), 4)}


def reward_accuracy(rows, base, candidate):
    agree = total = 0
    for r in rows:
        out = evaluate_response(r, model=base, stacker=candidate)
        oracle = reward_of("FAIL" if r["corruption"] else "PASS", float(r["rating"]))
        if out["reward"] is None:
            continue
        total += 1; agree += out["reward"] == oracle
    return {"n": total, "agreement_with_oracle": round(agree / max(1, total), 4)}


def run_bandit(personas, situations, base, candidate, reward_source, episodes, seed):
    """Online loop: situation x persona -> policy style -> writer -> Agent F -> reward -> update."""
    policy, rng = StylePolicy(seed=seed), random.Random(seed)
    for _ in range(episodes):
        s, p = rng.choice(situations), rng.choice(personas)
        probe = record_for(s, p, "short", None, rng)                       # context only (no reply used)
        style = policy.choose(probe["situation"])
        rec = record_for(s, p, style, None, rng)
        if reward_source == "agent_f":
            reward = evaluate_response(rec, model=base, stacker=candidate)["reward"]
        else:                                                               # the simulator's own rating as "real" feedback
            reward = reward_of(check_correctness(rec)["status"], float(rec["rating"]))
        policy.update(rec["situation"], style, reward)
    return policy


def evaluate_policies(policies: dict, personas, situations, seed):
    """Greedy evaluation on EVAL personas: average simulated rating and oracle reward per policy and company."""
    out = {}
    for name, pick in policies.items():
        rng = random.Random(seed)
        rows = []
        for p in personas:
            for s in situations:
                probe = record_for(s, p, "short", None, rng)
                style = pick(probe["situation"])
                rows.append(record_for(s, p, style, None, rng))
        out[name] = by_company(rows, lambda rs: {"avg_rating": round(float(np.mean([r["rating"] for r in rs])), 4),
                                                 "avg_reward": round(float(np.mean([1 if r["rating"] >= 4 else -1 for r in rs])), 4),
                                                 "share_satisfied": round(float(np.mean([r["rating"] >= 4 for r in rs])), 4)})
    return out


def main():
    seed_shopnova(); seed_atlas()
    base = pickle.loads(TEXT_MODEL.read_bytes())
    situations = make_situations()
    personas = {k: make_personas(n, ps, k) for k, (n, ps, _) in SETS.items()}
    assert not ({p["id"] for p in personas["train"]} & {p["id"] for p in personas["eval"]})
    rows = {k: build_dataset(personas[k], SETS[k][2], situations=situations) for k in SETS}
    for k, rs in rows.items():
        write_jsonl(rs, DATA / f"{k}.jsonl")
    res = {"note": "ALL SIMULATED feedback (callverse/learning/simulator.py). Not evidence of real customer satisfaction.",
           "situations": len(situations), "personas": {k: len(v) for k, v in personas.items()},
           "rows": {k: len(v) for k, v in rows.items()}}

    t0 = time.perf_counter()
    candidate, report = train_and_validate(rows["train"], base)
    res["style_candidate_training"] = {**report, "fit_s": round(time.perf_counter() - t0, 1)}
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    (MODEL_DIR / "stacker_candidate.pkl").write_bytes(pickle.dumps(candidate))

    res["satisfaction"] = {k: by_company(rows[k], lambda rs: satisfaction_metrics(rs, base, candidate)) for k in ("val", "eval")}
    res["correctness_eval"] = by_company(rows["eval"], correctness_metrics)
    res["reward_eval"] = {"fixed": reward_accuracy(rows["eval"], base, False),
                          "style_candidate": reward_accuracy(rows["eval"], base, candidate)}

    ms = []
    for r in rows["eval"][:300]:
        t = time.perf_counter(); evaluate_response(r, model=base, stacker=candidate); ms.append((time.perf_counter() - t) * 1000)
    res["latency_ms"] = {"mean": round(float(np.mean(ms)), 2), "p95": round(float(np.percentile(ms, 95)), 2)}

    policies = {"always_short": always("short"), "always_apology_first": always("apology_first"),
                "always_apology_next_step": always("apology_next_step"), "random": random_style(7), "rule_based": rule_based}
    for src in ("agent_f", "simulated"):
        pol = run_bandit(personas["train"], situations, base, candidate, src, episodes=3000, seed=11)
        pol.save(MODEL_DIR / f"style_policy_{src}.json")
        policies[f"bandit_reward_{src}"] = pol.best
        res[f"bandit_{src}_arms"] = pol.summary()
    res["policies_eval"] = evaluate_policies(policies, personas["eval"], situations, seed=5)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "rl_eval.json").write_text(json.dumps(res, indent=2))
    print(json.dumps({k: res[k] for k in ("rows", "satisfaction", "correctness_eval", "reward_eval", "latency_ms", "policies_eval")}, indent=1))


if __name__ == "__main__":
    main()
