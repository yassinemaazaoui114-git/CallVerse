"""Evaluate Agent F's satisfaction model on HUMAN LABELS of CallVerse conversations (when they exist).

    python -m v4.f.annotation.eval_labels --labels <records.jsonl> --predictions <agent_f_results.jsonl> \
        --split <split.json> --out <folder> [--allow-synthetic]

Inputs
  --labels       satisfaction records in the PROPOSED reviews contract (v4/f/contracts/reviews.schema.json).
                 Only measured records are used (rating_source customer_submitted or annotator), only if valid,
                 consented for model_validation, not duplicate, not test/synthetic (contracts.usable_for_validation).
  --predictions  one JSON per line with conversation_id and predicted_satisfaction (+ satisfaction_validity),
                 e.g. the agent_f_results.jsonl written by v4/f/eval_m7_v4.py or AgentF.process().
  --split        {"dev": [conversation ids], "test": [...]} fixed BEFORE looking at any prediction
                 (ANNOTATION_PROTOCOL.md §6). The mean baseline is the DEV label mean; metrics are on TEST.
  --allow-synthetic  only for the unit-test fixture: synthetic records are accepted, and the card is marked
                 SYNTHETIC with label_type "synthetic_fixture", so it can never pass the F->E gate.
What it computes (output report.json + card.json)
  agreement      Krippendorff's alpha (interval AND ordinal), mean pairwise |diff|, share of exact agreement,
                 human leave-one-out MAE = how well ONE annotator predicts the others (the noise limit).
  gold label     mean of the annotators (annotator records) / the rating (customer_submitted).
  model          on TEST: n, coverage (conversations with a score), MAE, RMSE, Spearman + bootstrap 95% CI,
                 MAE of the DEV-mean baseline, per language; conversations with no score (e.g. French withheld)
                 are counted, never filled in.
  card           the validation card the F->E gate reads (v4/f/m7/feedback_v4.py), with corpus "callverse".
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))                         # experiments/agents_ef
from v3.f.uss_data import krippendorff_interval  # noqa: E402
from v4.f.contracts.validate_reviews import validate  # noqa: E402
from v4.f.m7.feedback_v4 import e_reward_decision  # noqa: E402


def krippendorff_ordinal(units: list[list[float]]) -> float:
    """Krippendorff's alpha, ordinal metric, for units with >= 2 ratings each (values on any ordered scale)."""
    units = [list(u) for u in units if len(u) >= 2]
    values = sorted({v for u in units for v in u})
    idx = {v: i for i, v in enumerate(values)}
    k = len(values)
    if k < 2:
        return float("nan")
    o = np.zeros((k, k))                                          # coincidence matrix
    for u in units:
        m = len(u)
        for a in range(m):
            for b in range(m):
                if a != b:
                    o[idx[u[a]], idx[u[b]]] += 1 / (m - 1)
    n_c = o.sum(axis=1)
    n = n_c.sum()
    d2 = np.zeros((k, k))
    for c in range(k):
        for e in range(k):
            lo, hi = min(c, e), max(c, e)
            d2[c, e] = (n_c[lo:hi + 1].sum() - (n_c[lo] + n_c[hi]) / 2) ** 2
    do = (o * d2).sum() / n
    de = (np.outer(n_c, n_c) * d2).sum() / (n * (n - 1))
    return float(1 - do / de) if de > 0 else float("nan")


def usable(record, allow_synthetic):
    errs = validate(record)
    if errs:
        return False, "invalid: " + errs[0]
    if record["rating_source"] not in ("customer_submitted", "annotator"):
        return False, "not a measured rating (ai_predicted)"
    if "model_validation" not in record["consent"]["scope"]:
        return False, "consent scope lacks model_validation"
    if record["data_quality"]["is_duplicate"]:
        return False, "duplicate"
    if record["data_quality"]["is_test_or_synthetic"] and not allow_synthetic:
        return False, "test or synthetic record"
    return True, None


def agreement(by_conv: dict) -> dict:
    units = [v for v in by_conv.values() if len(v) >= 2]
    if not units:
        return {"n_units_multi_rated": 0, "note": "fewer than 2 ratings per conversation: agreement not measurable"}
    pair = [abs(a - b) for u in units for i, a in enumerate(u) for b in u[i + 1:]]
    loo = [abs(u[i] - np.mean(u[:i] + u[i + 1:])) for u in units for i in range(len(u))]
    return {"n_units_multi_rated": len(units),
            "ratings_per_unit": {str(k): int(v) for k, v in zip(*np.unique([len(u) for u in units],
                                                                           return_counts=True))},
            "krippendorff_alpha_interval": round(krippendorff_interval(units), 4),
            "krippendorff_alpha_ordinal": round(krippendorff_ordinal(units), 4),
            "mean_pairwise_abs_diff": round(float(np.mean(pair)), 4),
            "share_all_agree": round(float(np.mean([len(set(u)) == 1 for u in units])), 4),
            "human_loo_mae": round(float(np.mean(loo)), 4)}


def model_metrics(y, p, n_boot=2000, seed=0):
    from scipy.stats import spearmanr
    y, p = np.asarray(y, float), np.asarray(p, float)
    out = {"n": int(len(y)), "mae": round(float(np.abs(y - p).mean()), 4),
           "rmse": round(float(np.sqrt(((y - p) ** 2).mean())), 4)}
    if len(y) >= 3 and np.std(p) > 0 and np.std(y) > 0:
        out["spearman"] = round(float(spearmanr(y, p).statistic), 4)
        rng = np.random.default_rng(seed)
        b = []
        for _ in range(n_boot):
            k = rng.integers(0, len(y), len(y))
            if np.std(p[k]) > 0 and np.std(y[k]) > 0:
                b.append(spearmanr(y[k], p[k]).statistic)
        out["spearman_ci95"] = [round(float(np.percentile(b, 2.5)), 4), round(float(np.percentile(b, 97.5)), 4)]
    else:
        out["spearman"], out["spearman_ci95"] = None, [None, None]
    return out


def evaluate(records, predictions, split, allow_synthetic=False):
    dropped = defaultdict(int)
    ratings, source, lang = defaultdict(list), defaultdict(set), {}
    synthetic = False
    for r in records:
        ok, why = usable(r, allow_synthetic)
        if not ok:
            dropped[why.split(":")[0] if why.startswith("invalid") else why] += 1
            continue
        synthetic |= r["data_quality"]["is_test_or_synthetic"]
        ratings[r["conversation_id"]].append(float(r["rating"]))
        source[r["conversation_id"]].add(r["rating_source"])
        lang[r["conversation_id"]] = r["language"]
    gold = {c: float(np.mean(v)) for c, v in ratings.items()}
    pred = {p["conversation_id"]: p.get("predicted_satisfaction") for p in predictions}
    dev = [c for c in split.get("dev", []) if c in gold]
    test = [c for c in split.get("test", []) if c in gold]
    overlap = set(split.get("dev", [])) & set(split.get("test", []))
    if overlap:
        raise ValueError(f"{len(overlap)} conversations are in both dev and test")
    base = float(np.mean([gold[c] for c in dev])) if dev else None
    scored = [c for c in test if pred.get(c) is not None]
    rep = {"n_records_in": len(records), "dropped": dict(dropped), "n_conversations_labelled": len(gold),
           "sources": sorted({s for v in source.values() for s in v}),
           "agreement": agreement({c: v for c, v in ratings.items()}),
           "split": {"dev": len(dev), "test": len(test)},
           "test_coverage": round(len(scored) / len(test), 4) if test else 0.0,
           "test_not_scored": len(test) - len(scored),
           "test_not_scored_by_language": dict(sorted({lg: sum(1 for c in test if pred.get(c) is None and
                                                                lang.get(c) == lg) for lg in set(lang.values())}.items())),
           "dev_mean_baseline": None if base is None else round(base, 4)}
    if scored:
        y = [gold[c] for c in scored]
        rep["model_test"] = model_metrics(y, [pred[c] for c in scored])
        if base is not None:
            rep["model_test"]["mae_dev_mean_baseline"] = round(float(np.mean([abs(base - v) for v in y])), 4)
        rep["model_test_by_language"] = {}
        for lg in sorted({lang[c] for c in scored}):
            cs = [c for c in scored if lang[c] == lg]
            rep["model_test_by_language"][lg] = model_metrics([gold[c] for c in cs], [pred[c] for c in cs])
    srcs = rep["sources"]
    label_type = "synthetic_fixture" if synthetic else ("genuine_customer_rating" if srcs == ["customer_submitted"]
                                                       else "human_annotation")
    m = rep.get("model_test", {})
    card = {"model": (predictions[0].get("satisfaction_validity") or {}).get("model_id") if predictions else None,
            "label_type": label_type, "domain": "support_conversation", "corpus": "callverse",
            "test_n": len(test), "test_n_scored": len(scored), "mae": m.get("mae"),
            "mae_mean_baseline": m.get("mae_dev_mean_baseline"), "spearman": m.get("spearman"),
            "spearman_ci_low": (m.get("spearman_ci95") or [None])[0],
            "spearman_ci_high": (m.get("spearman_ci95") or [None, None])[1],
            "agreement_alpha_ordinal": rep["agreement"].get("krippendorff_alpha_ordinal"),
            "human_loo_mae": rep["agreement"].get("human_loo_mae"),
            "SYNTHETIC": synthetic}
    # coverage for the gate = share of TEST conversations that received a score
    sat = [{"conversation_id": c, "validity": "validated" if pred.get(c) is not None else "no_score"} for c in test]
    rep["gate"] = e_reward_decision(card, sat)
    return rep, card


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True)
    ap.add_argument("--predictions", required=True)
    ap.add_argument("--split", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--allow-synthetic", action="store_true")
    a = ap.parse_args(argv)
    read = lambda p: [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    rep, card = evaluate(read(a.labels), read(a.predictions), json.loads(Path(a.split).read_text()),
                         a.allow_synthetic)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(rep, indent=1))
    (out / "card.json").write_text(json.dumps(card, indent=1))
    print(json.dumps({"agreement": rep["agreement"], "model_test": rep.get("model_test"),
                      "e_reward_allowed": rep["gate"]["e_reward_allowed"], "reasons": rep["gate"]["reasons"]},
                     indent=1))


if __name__ == "__main__":
    main()
