"""ONE-SHOT locked REAL support evaluation of a style-aware Agent F candidate.

No fitting, tuning or model selection is done here. Do not rerun for iterative tuning.
Usage:
 python -m benchmarks.agent_f.evaluate_style_candidate TEAM_REAL_RATINGS.jsonl \
   --candidate models/agent_f/stacker_candidate.pkl --confirm-real --out results/rl6_agent_f_real.json
"""
from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path

from benchmarks.agent_f.evaluate_rated import evaluate
from callverse.quality.satisfaction import predict_satisfaction


def compare_real(records, base_model, candidate):
    """Evaluation only; no fitting or changing either model."""
    if not records:
        raise ValueError("Empty real evaluation set")
    if any(r.get("source") == "simulated" for r in records):
        raise ValueError("Simulated ratings cannot be presented as real human evaluations")
    if any("rating" not in r for r in records):
        raise ValueError("All records require a human 1–5 rating")
    fixed = evaluate(records, predict=lambda r: predict_satisfaction(r, model=base_model, stacker=False))
    styled = evaluate(records, predict=lambda r: predict_satisfaction(r, model=base_model, stacker=candidate))
    # The existing evaluator collects the worst ten user texts; omit their content
    # from this saved report to avoid exporting potentially sensitive messages.
    for output in (fixed, styled):
        for err in output["worst"]:
            err.pop("user_text", None)
    m = styled["agent_f"]["mae_raw"]
    return {"dataset": "independent HUMAN-RATED support holdout",
            "n": len(records), "fixed_baseline": fixed, "style_candidate": styled,
            "mae_improvement": round(fixed["agent_f"]["mae_raw"] - m, 4),
            "candidate_not_worse_than_fixed": m <= fixed["agent_f"]["mae_raw"],
            "candidate_beats_average_baseline": m < styled["baseline_average"]["mae_raw"],
            "candidate_beats_delay_baseline": m < styled["baseline_delay_only"]["mae_raw"],
            "candidate_under_200ms_p95": styled["ms_p95"] < 200,
            "status": "evaluation-only; RL5 and team review still required"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("real_jsonl", type=Path)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--base", type=Path, default=Path("models/agent_f/satisfaction.pkl"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--confirm-real", action="store_true", help="Confirm this is the one locked human-rated holdout")
    args = parser.parse_args(argv)
    if not args.confirm_real:
        parser.error("Explicit --confirm-real required; do not evaluate synthetic ratings as real")
    rows = [json.loads(x) for x in args.real_jsonl.read_text(encoding="utf-8").splitlines() if x.strip()]
    with args.base.open("rb") as f:
        base = pickle.load(f)
    with args.candidate.open("rb") as f:
        candidate = pickle.load(f)
    report = compare_real(rows, base, candidate)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("fixed_baseline", "style_candidate")}, indent=2))
    print(f"Full real evaluation saved at {args.out}. Do not use this holdout for tuning.")


if __name__ == "__main__":
    main()
