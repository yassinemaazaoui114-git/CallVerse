"""Train the chosen Agent F model on the real train split and save it to models/agent_f/ (git-ignored).

Run: python -m benchmarks.agent_f.train [model_name]   (default: the 'chosen' entry of results/benchmark.json)
Then reports MAE / accuracy / latency on the real held-out TEST split once -> results/test_eval.json.
"""
from __future__ import annotations

import json
import pickle
import sys

from benchmarks.agent_f.benchmark import latency, metrics
from benchmarks.agent_f.common import ROOT, TRAIN_N, candidates, load
import numpy as np

from callverse.quality.satisfaction import TEXT_MODEL as MODEL_PATH


def main():
    res = ROOT / "benchmarks/agent_f/results"
    name = sys.argv[1] if len(sys.argv) > 1 else json.loads((res / "benchmark.json").read_text())["chosen"]
    model = candidates()[name]
    xtr, ytr = load("train", TRAIN_N)
    model.fit(xtr, ytr)
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODEL_PATH.write_bytes(pickle.dumps(model))
    xte, yte = load("test")
    out = {"model": name, "split": "test (real, held out)", "n": len(xte),
           "argmax": metrics(yte, model.predict(xte)),
           "expected": metrics(yte, model.predict_proba(xte) @ model.classes_), **latency(model, xte, 1000)}
    (res / "test_eval.json").write_text(json.dumps(out, indent=2))
    print(out)


if __name__ == "__main__":
    main()
