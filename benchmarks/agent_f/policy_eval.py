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
from callverse.learning.style_policy import (UPSET, GaussianThompson, LinUCB, always, from_table, random_style,
                                             rule_based, rule_based_v2, supervised_group_policy)
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
    res = {"note": "SIMULATED. Policies scored on VAL and EVAL personas x 69 situations, greedy, 3 evaluation seeds. "
                   "The deployment choice is made on VAL only; EVAL is reported once.", "fixed": {}, "learned": {}}
    mood_rule = rule_by_mood_from(train_rows)
    res["rule_from_train_by_mood"] = mood_rule
    fixed = {"always_short": always("short"), "always_apology_first": always("apology_first"),
             "always_apology_next_step": always("apology_next_step"), "random": random_style(7),
             "rule_based": rule_based, "rule_based_v2_from_eval_audit": rule_based_v2,
             "rule_by_mood_from_train": lambda sit: mood_rule["upset" if sit.get("emotion") in UPSET else "calm"],
             "supervised_group_train": from_table(supervised_group_policy(train_rows))}
    for name, pick in fixed.items():
        res["fixed"][name] = {"val": multi_seed(pick, personas["val"], situations), "eval": multi_seed(pick, personas["eval"], situations)}
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
            per.append({"val": multi_seed(pol.best, personas["val"], situations)["avg_rating_mean"],
                        "eval": multi_seed(pol.best, personas["eval"], situations)["avg_rating_mean"]})
            if sd == 11:
                pol.save(MODEL_DIR / f"policy_eval_{name}.json")
        res["learned"][name] = {k: {"avg_rating_mean": round(float(np.mean([x[k] for x in per])), 4),
                                    "avg_rating_std": round(float(np.std([x[k] for x in per])), 4)} for k in ("val", "eval")}
        print(name, res["learned"][name], flush=True)
    candidates = {n: v["val"]["avg_rating_mean"] for n, v in res["fixed"].items() if n != "rule_based_v2_from_eval_audit"}
    candidates.update({n: v["val"]["avg_rating_mean"] for n, v in res["learned"].items()})
    deploy = max(candidates, key=candidates.get)
    res["decision"] = {"selected_on_val": deploy, "val_scores": candidates,
                       "eval_of_selected": (res["fixed"].get(deploy) or res["learned"][deploy])["eval"]["avg_rating_mean"],
                       "note": "rule_based_v2 was read off the EVAL audit and is excluded from selection (leakage)"}
    if deploy in res["learned"]:
        (MODEL_DIR / f"policy_eval_{deploy}.json").replace(MODEL_DIR / "style_policy.json")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "policy_eval.json").write_text(json.dumps(res, indent=2))
    print(res["decision"])


def rule_by_mood_from(rows) -> dict:
    """Best style for upset and for calm customers by mean rating on TRAIN rows (clean replies only)."""
    from collections import defaultdict
    acc = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["corruption"] is None and r.get("degradation") is None:
            acc["upset" if r["situation"]["emotion"] in UPSET else "calm"][r["style"]].append(float(r["rating"]))
    return {m: max(v, key=lambda s: sum(v[s]) / len(v[s])) for m, v in acc.items()}


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
