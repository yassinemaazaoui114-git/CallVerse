"""F2 — after the single TEST score: is the VAL-selected variant really better, and does it change anything on
ShopNova? (descriptive only; nothing here selects or tunes anything)

    python -m v4.f.f2_compare --fv3 <f_v3> --corpus <m7_corpus>

  1. reloads the saved variant from disk (checks SHA256) and re-computes its TEST predictions (load round trip);
  2. paired bootstrap (2,000 resamples of TEST dialogues) of MAE(variant) - MAE(baseline), all / EN / ZH;
  3. its prediction spread on the ShopNova corpus and on the F1 minimal-pair probes, next to the baseline.
Output: v4/f/results/f2_compare.json
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fv3", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--variant", default="roles")
    a = ap.parse_args(argv)
    from v3.m7.conversations import dialogue_text, load_conversations
    from v4.f.diagnose_shift import probe_set
    from v4.f.f2_experiments import BlockSatisfactionPredictor
    from v4.f.tfidf_predictor import TfidfSatisfactionPredictor
    te = [json.loads(l) for l in open(Path(a.fv3) / "data_uss/test.jsonl", encoding="utf-8")]
    y = np.array([r["rating"] for r in te])
    lang = np.array([r["lang"] for r in te])
    var = BlockSatisfactionPredictor.load(Path(a.fv3) / f"ckpt/tfidf_{a.variant}_tail256")
    base = TfidfSatisfactionPredictor.load(Path(a.fv3) / "ckpt/tfidf_ridge_tail256")
    pv = var.scores([r["text"] for r in te], [r["lang"] for r in te])
    pb = base.scores([r["text"] for r in te], [r["lang"] for r in te])
    stored = json.loads((HERE / f"results/f2_test_{a.variant}.json").read_text())["test"]
    rep = {"variant": a.variant, "roundtrip_test_mae": round(float(np.abs(pv - y).mean()), 5),
           "stored_test_mae": stored["mae"], "baseline_test_mae": round(float(np.abs(pb - y).mean()), 5)}
    rng = np.random.default_rng(0)
    for name, mask in (("all", np.ones(len(y), bool)), ("en", lang == "en"), ("zh", lang == "zh")):
        ev, eb = np.abs(pv[mask] - y[mask]), np.abs(pb[mask] - y[mask])
        d = ev - eb
        boots = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)]
        rep[f"paired_mae_diff_{name}"] = {"diff": round(float(d.mean()), 5),
                                          "ci95": [round(float(np.percentile(boots, 2.5)), 5),
                                                   round(float(np.percentile(boots, 97.5)), 5)],
                                          "n": int(mask.sum())}
    sn = []
    for split in ("dev", "test"):
        sn += [dialogue_text(c) for c in load_conversations(Path(a.corpus) / split / "traces")]
    sv, sb = var.scores(sn), base.scores(sn)
    rep["shopnova_sd"] = {"variant": round(float(sv.std()), 4), "baseline": round(float(sb.std()), 4),
                          "variant_mean": round(float(sv.mean()), 4), "baseline_mean": round(float(sb.mean()), 4),
                          "corr_variant_baseline": round(float(np.corrcoef(sv, sb)[0, 1]), 4), "n": len(sn)}
    probes = probe_set()
    ps = var.scores([p[2] for p in probes])
    rep["probes"] = {}
    for (g, v, _), s in zip(probes, ps):
        rep["probes"].setdefault(g, {})[v] = round(float(s), 4)
    (HERE / "results/f2_compare.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
