"""Policy evaluation with uncertainty: fixed styles, rules, supervised and learned policies on EVAL personas over
several evaluation seeds; LinUCB alpha chosen on VAL personas (never on EVAL).

Run after rl_eval.py: python -m benchmarks.agent_f.policy_eval -> results/policy_eval.json, models/agent_f/style_policy.json
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np

from benchmarks.agent_f.rl_eval import DATA, OUT, SETS, run_bandit, score_policy
from callverse.data.atlas.seed import seed as seed_atlas
from callverse.data.seed import seed as seed_shopnova
from callverse.learning.simulator import make_personas, make_situations
from callverse.learning.style_policy import (GaussianThompson, LinUCB, always, from_table, random_style, rule_based,
                                             rule_based_v2, supervised_group_policy)
from callverse.quality.satisfaction import MODEL_DIR, TEXT_MODEL

EVAL_SEEDS = (5, 6, 7)


def multi_seed(pick, personas, situations):
    vals = [score_policy(pick, personas, situations, sd)["avg_rating"] for sd in EVAL_SEEDS]
    return {"avg_rating_mean": round(float(np.mean(vals)), 4), "avg_rating_std": round(float(np.std(vals)), 4), "per_eval_seed": vals}


def main():
    seed_shopnova(); seed_atlas()
    base = pickle.loads(TEXT_MODEL.read_bytes())
    stacker = pickle.loads((MODEL_DIR / "stacker_selected.pkl").read_bytes())
    situations = make_situations()
    personas = {k: make_personas(n, ps, k) for k, (n, ps, _) in SETS.items()}
    train_rows = [json.loads(l) for l in (DATA / "train.jsonl").open(encoding="utf-8")]
    res = {"note": "SIMULATED. Eval = EVAL personas x 69 situations, greedy, 3 evaluation seeds.", "fixed": {}, "learned": {}}
    for name, pick in {"always_short": always("short"), "always_apology_first": always("apology_first"),
                       "always_apology_next_step": always("apology_next_step"), "random": random_style(7),
                       "rule_based": rule_based, "rule_based_v2": rule_based_v2,
                       "supervised_group_train": from_table(supervised_group_policy(train_rows))}.items():
        res["fixed"][name] = multi_seed(pick, personas["eval"], situations)
        print(name, res["fixed"][name], flush=True)

    # LinUCB alpha: train on TRAIN, choose on VAL, then score on EVAL (3 training seeds).
    alpha_val = {}
    for alpha in (0.1, 0.5, 1.0, 2.0):
        scores = []
        for sd in (11, 12, 13):
            pol = LinUCB(alpha=alpha, seed=sd)
            _train(pol, personas["train"], situations, base, stacker, sd)
            scores.append(score_policy(pol.best, personas["val"], situations, 5)["avg_rating"])
        alpha_val[alpha] = round(float(np.mean(scores)), 4)
    best_alpha = max(alpha_val, key=alpha_val.get)
    res["linucb_alpha_on_val"] = {"scores": alpha_val, "chosen": best_alpha}
    for name, make in {"linucb_tuned": lambda sd: LinUCB(alpha=best_alpha, seed=sd),
                       "gaussian_thompson": lambda sd: GaussianThompson(seed=sd)}.items():
        per = []
        for sd in (11, 12, 13):
            pol = make(sd)
            _train(pol, personas["train"], situations, base, stacker, sd)
            per.append(multi_seed(pol.best, personas["eval"], situations)["avg_rating_mean"])
            if sd == 11:
                pol.save(MODEL_DIR / f"policy_eval_{name}.json")
        res["learned"][name] = {"avg_rating_mean": round(float(np.mean(per)), 4), "avg_rating_std": round(float(np.std(per)), 4), "per_train_seed": per}
        print(name, res["learned"][name], flush=True)
    best_fixed = max(res["fixed"], key=lambda n: res["fixed"][n]["avg_rating_mean"])
    best_learned = max(res["learned"], key=lambda n: res["learned"][n]["avg_rating_mean"])
    res["decision"] = {"best_fixed": best_fixed, "best_learned": best_learned,
                       "deploy": best_fixed if res["fixed"][best_fixed]["avg_rating_mean"] >= res["learned"][best_learned]["avg_rating_mean"] else best_learned}
    if res["decision"]["deploy"] == best_learned:
        (MODEL_DIR / f"policy_eval_{best_learned}.json").replace(MODEL_DIR / "style_policy.json")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "policy_eval.json").write_text(json.dumps(res, indent=2))
    print(res["decision"])


def _train(pol, personas, situations, base, stacker, seed, episodes=6000):
    import random
    from callverse.learning.simulator import record_for
    from callverse.quality.reward import evaluate_response
    rng = random.Random(seed)
    for _ in range(episodes):
        s, p = rng.choice(situations), rng.choice(personas)
        probe = record_for(s, p, "short", None, rng)
        style = pol.choose(probe["situation"])
        rec = record_for(s, p, style, None, rng)
        out = evaluate_response(rec, model=base, stacker=stacker)
        pol.update(rec["situation"], style, None if out["correctness"] == "UNKNOWN" else (out["satisfaction"] if out["correctness"] == "PASS" else 1.0))


if __name__ == "__main__":
    main()
