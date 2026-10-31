"""Hypothesis check: the style ranking flips between VAL and EVAL because each set has only 6 hidden personas.
Re-score the fixed styles, the train-derived mood rule and a Gaussian-Thompson policy on LARGER persona sets
(40 personas each, new seeds 404 / 505, disjoint from train 101). Ratings only; SIMULATED.
Run: python -m benchmarks.agent_f.persona_scale_eval -> results/persona_scale_eval.json
"""
from __future__ import annotations

import json
import pickle

import numpy as np

from benchmarks.agent_f.policy_eval import _train, multi_seed, rule_by_mood_from
from benchmarks.agent_f.rl_eval import DATA, OUT, SETS
from callverse.data.atlas.seed import seed as seed_atlas
from callverse.data.seed import seed as seed_shopnova
from callverse.learning.simulator import make_personas, make_situations
from callverse.learning.style_policy import UPSET, GaussianThompson, always, rule_based
from callverse.quality.satisfaction import MODEL_DIR, TEXT_MODEL


def main():
    seed_shopnova(); seed_atlas()
    base = pickle.loads(TEXT_MODEL.read_bytes())
    stacker = pickle.loads((MODEL_DIR / "stacker_selected.pkl").read_bytes())
    situations = make_situations()
    train = make_personas(SETS["train"][0], SETS["train"][1], "train")
    big = {"val40": make_personas(40, 404, "val40"), "eval40": make_personas(40, 505, "eval40")}
    train_rows = [json.loads(l) for l in (DATA / "train.jsonl").open(encoding="utf-8")]
    mood = rule_by_mood_from(train_rows)
    policies = {"always_short": always("short"), "always_apology_first": always("apology_first"),
                "always_apology_next_step": always("apology_next_step"), "rule_based": rule_based,
                "rule_by_mood_from_train": lambda sit: mood["upset" if sit.get("emotion") in UPSET else "calm"]}
    res = {"note": "SIMULATED; 40-persona sets", "personas": {k: len(v) for k, v in big.items()}, "policies": {}}
    for name, pick in policies.items():
        res["policies"][name] = {k: multi_seed(pick, ps, situations) for k, ps in big.items()}
        print(name, res["policies"][name], flush=True)
    per = []
    for sd in (11, 12, 13):
        pol = GaussianThompson(seed=sd)
        _train(pol, train, situations, base, stacker, sd)
        per.append({k: multi_seed(pol.best, ps, situations)["avg_rating_mean"] for k, ps in big.items()})
    res["policies"]["gaussian_thompson_train12"] = {k: {"avg_rating_mean": round(float(np.mean([x[k] for x in per])), 4),
                                                         "avg_rating_std": round(float(np.std([x[k] for x in per])), 4)} for k in big}
    print("gaussian_thompson", res["policies"]["gaussian_thompson_train12"], flush=True)
    # archetype mix of each persona set: the hidden driver of the style ranking
    for k, ps in list(big.items()) + [("train12", train), ("val6", make_personas(6, 202, "val")), ("eval6", make_personas(6, 303, "eval"))]:
        from collections import Counter
        res.setdefault("archetype_mix", {})[k] = dict(Counter(p["archetype"] for p in ps))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "persona_scale_eval.json").write_text(json.dumps(res, indent=2))
    print(res["archetype_mix"])


if __name__ == "__main__":
    main()
