"""Train a CANDIDATE Agent F style-aware reward model from SIMULATED TRAINING personas.

Examples:
  python -m benchmarks.agent_f.train_style data/rl4_train_personas_rated.jsonl
  python -m benchmarks.agent_f.train_style data/rl4_train_personas_rated.jsonl --min-rows 2000

Never use the team's ~100 genuine support ratings, or the evaluation-persona set,
for fitting or model/alpha selection. This is an RLHF-style *reward proxy* for a
contextual bandit, NOT a PPO policy or proof of real human preference.

Records need: style, situation.emotion, messages, rating 1..5, source=simulated,
and a persona_id (or persona.id or situation.persona_id). scenario_id recommended.
Training and internal validation are disjoint BY TRAINING PERSONA.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import pickle
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupShuffleSplit

from callverse.quality.satisfaction import STYLES, EMOTIONS, TEXT_MODEL, MODEL_DIR, features, predict_satisfaction


def persona_id(record: dict) -> str:
    p = record.get("persona")
    val = record.get("persona_id") or (p.get("id") if isinstance(p, dict) else None) or (
        (record.get("situation") or {}).get("persona_id"))
    if not isinstance(val, (str, int)) or not str(val).strip():
        raise ValueError("Each training record needs persona_id to prevent train/dev persona leakage")
    return str(val)


def scenario_id(record: dict) -> str | None:
    s = record.get("situation") or {}
    val = record.get("scenario_id") or record.get("situation_id") or s.get("scenario_id")
    return str(val) if val is not None else None


def validate_rows(rows: list[dict], min_rows: int = 2000, min_personas: int = 8) -> dict:
    """Fail closed on unmarked or real ratings, malformed records and weak persona coverage."""
    if len(rows) < min_rows:
        raise ValueError(f"Need >= {min_rows} simulated TRAINING-persona ratings; got {len(rows)}")
    ps = set()
    styles = set()
    paired = defaultdict(set)
    for i, r in enumerate(rows):
        if r.get("source") != "simulated":
            raise ValueError(f"row {i}: source must explicitly equal 'simulated'; real ratings are test-only")
        p = persona_id(r)
        ps.add(p)
        style = r.get("style")
        if style not in STYLES:
            raise ValueError(f"row {i}: invalid style {style!r}")
        styles.add(style)
        sit = r.get("situation") or {}
        if sit.get("emotion", "neutral") not in EMOTIONS:
            raise ValueError(f"row {i}: unknown emotion")
        if not isinstance(r.get("messages"), list):
            raise ValueError(f"row {i}: need messages array")
        score = r.get("rating")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 1 <= score <= 5:
            raise ValueError(f"row {i}: rating must be finite and in [1, 5]")
        sc = scenario_id(r)
        if sc is not None:
            paired[(p, sc)].add(style)
    if len(ps) < min_personas:
        raise ValueError(f"Need >= {min_personas} distinct TRAINING personas; got {len(ps)}")
    if styles != set(STYLES):
        raise ValueError(f"All 3 styles required; found {sorted(styles)}")
    return {"rows": len(rows), "personas": len(ps), "paired_scenarios": sum(len(v) >= 2 for v in paired.values()),
            "styles": sorted(styles)}


def stats(y, p):
    y, p = np.asarray(y, dtype=float), np.clip(np.asarray(p, dtype=float), 1, 5)
    rho = spearmanr(y, p).statistic if len(set(p)) > 1 else 0.0
    if not np.isfinite(rho):
        rho = 0.0
    return {"mae": round(float(np.mean(np.abs(y - p))), 4), "spearman": round(float(rho), 4)}


def train_and_validate(rows: list[dict], base_model, *, min_rows: int = 2000,
                       min_personas: int = 8, seed: int = 42, alphas=(0.1, 1.0, 10.0, 100.0)):
    inventory = validate_rows(rows, min_rows, min_personas)
    groups = [persona_id(r) for r in rows]
    split = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=seed)
    train_idx, dev_idx = next(split.split(rows, groups=groups))
    tr_personas = {groups[i] for i in train_idx}
    dev_personas = {groups[i] for i in dev_idx}
    assert tr_personas.isdisjoint(dev_personas)

    # Features are computed only once; pretrained real-review text model stays frozen.
    x = np.asarray([features(r, base_model) for r in rows], dtype=float)
    y = np.asarray([float(r["rating"]) for r in rows], dtype=float)
    baseline = np.asarray([predict_satisfaction(r, model=base_model, stacker=False)["score"]
                           for r in rows], dtype=float)
    comparison = stats(y[dev_idx], baseline[dev_idx])

    scores = []
    for alpha in alphas:
        mdl = Ridge(alpha=float(alpha)).fit(x[train_idx], y[train_idx])
        pred = np.clip(mdl.predict(x[dev_idx]), 1, 5)
        scores.append((float(np.mean(np.abs(y[dev_idx] - pred))), float(alpha), mdl))
    mae, alpha, chosen = min(scores, key=lambda z: (z[0], z[1]))
    valid_pred = np.clip(chosen.predict(x[dev_idx]), 1, 5)

    # Counterfactual sensitivity: same situation, alternate allowed styles.
    spreads = []
    for i in dev_idx:
        r = rows[i]
        alt = [dict(r, style=s) for s in STYLES]
        preds = np.clip(chosen.predict(np.asarray([features(a, base_model) for a in alt])), 1, 5)
        spreads.append(float(max(preds) - min(preds)))
    style_spread = float(np.median(spreads)) if spreads else 0.0
    result = {
        "data_provenance": "simulated TRAINING personas only; never real/locked evaluation personas",
        "inventory": inventory,
        "split": {"train_rows": len(train_idx), "dev_rows": len(dev_idx),
                  "train_personas": len(tr_personas), "dev_personas": len(dev_personas),
                  "persona_overlap": len(tr_personas & dev_personas), "seed": seed},
        "fixed_baseline_dev": comparison, "candidate_dev": stats(y[dev_idx], valid_pred),
        "ridge_alpha": alpha, "feature_schema_version": "v2-style-emotion-cross-34d",
        "median_style_reward_spread": round(style_spread, 4),
        "candidate_improves_simulated_mae": bool(mae < comparison["mae"]),
        "style_effect_present": bool(style_spread >= 0.05),
        "real_support_evaluation": "NOT RUN — separate locked ~100 rated conversations required",
        "can_promote": False,
    }
    return chosen, result


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("training_jsonl", type=Path, help="Simulated reactions from RL4 TRAINING personas only")
    parser.add_argument("--min-rows", type=int, default=2000)
    parser.add_argument("--min-personas", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=MODEL_DIR / "stacker_candidate.pkl")
    args = parser.parse_args(argv)
    if args.min_rows < 1 or args.min_personas < 2:
        parser.error("Invalid minimums")
    rows = read_jsonl(args.training_jsonl)
    with TEXT_MODEL.open("rb") as f:
        base = pickle.load(f)  # trusted local artifact from benchmark Agent F training
    candidate, report = train_and_validate(rows, base, min_rows=args.min_rows,
                                           min_personas=args.min_personas, seed=args.seed)
    report["training_file_sha256"] = hashlib.sha256(args.training_jsonl.read_bytes()).hexdigest()
    report["model_path"] = str(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(pickle.dumps(candidate))
    args.output.with_suffix(".report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print("CANDIDATE ONLY; do not copy to stacker.pkl until locked real-support evaluation and team review.")


if __name__ == "__main__":
    main()
