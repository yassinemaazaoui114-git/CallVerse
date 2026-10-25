"""M7 responsibility 5: satisfaction feedback for Agent E, released to E's REWARD only after validation.

    gate(card)                         -> {"usable_for_reward": bool, "checks": [...]}
    per_conversation(reviews, scores, card) -> one record per closed conversation
    aggregate(records, step_min=5)     -> per (time step, route) shortfall sums, in EnvV3's units

Why a gate: E is an RL agent. If its reward contains a satisfaction score that is wrong or biased, E learns to
optimise the error (reward hacking). So the score enters E's reward only when the satisfaction model was shown
to work on the RIGHT kind of label (genuine customer ratings of support conversations) with enough data.
Otherwise the records are still produced, but marked kpi_only: E's dashboard may show them, its reward may not.

Units: EnvV3 uses the shortfall (5 - csat) / 4 per resolved ticket, summed per 5-minute step
(v3/e/env_v3.py, `csat_shortfall`), weighted by w_csat and capped by E's own config.
The feedback never touches E's action mask, budget, fallback cap or HIGH-ticket protections: those are rules
in E's environment and the Coordinator, not part of the reward.
"""

from collections import defaultdict
from datetime import datetime

# Thresholds fixed here BEFORE any evaluation (not tuned on test data).
GATE = {"label_type": "genuine_customer_rating", "domain": "support_conversation", "min_test_n": 300,
        "min_spearman_ci_low": 0.30, "must_beat_mean_baseline": True, "min_coverage": 0.95}


def gate(card: dict | None, coverage: float | None = None) -> dict:
    """card = the validation card of the satisfaction model (see make_card)."""
    if not card:
        return {"usable_for_reward": False, "checks": [{"check": "card", "pass": False, "why": "no validated model"}]}
    checks = [
        {"check": "label_type", "pass": card.get("label_type") == GATE["label_type"],
         "value": card.get("label_type"), "need": GATE["label_type"]},
        {"check": "domain", "pass": card.get("domain") == GATE["domain"], "value": card.get("domain"),
         "need": GATE["domain"]},
        {"check": "test_n", "pass": (card.get("test_n") or 0) >= GATE["min_test_n"], "value": card.get("test_n"),
         "need": f">= {GATE['min_test_n']}"},
        {"check": "spearman_ci_low", "pass": (card.get("spearman_ci_low") or -1) >= GATE["min_spearman_ci_low"],
         "value": card.get("spearman_ci_low"), "need": f">= {GATE['min_spearman_ci_low']}"},
        {"check": "beats_mean_baseline", "pass": bool(card.get("mae") is not None and card.get("mae_mean_baseline")
                                                      is not None and card["mae"] < card["mae_mean_baseline"]),
         "value": [card.get("mae"), card.get("mae_mean_baseline")], "need": "mae < mean-baseline mae"},
    ]
    if coverage is not None:
        checks.append({"check": "coverage", "pass": coverage >= GATE["min_coverage"], "value": round(coverage, 4),
                       "need": f">= {GATE['min_coverage']}"})
    return {"usable_for_reward": all(c["pass"] for c in checks), "checks": checks}


def per_conversation(reviews: list[dict], scores: dict, ends: dict, card: dict | None) -> tuple[list[dict], dict]:
    coverage = sum(1 for r in reviews if r["conversation_id"] in scores) / max(1, len(reviews))
    g = gate(card, coverage)
    out = []
    for r in reviews:
        s = scores.get(r["conversation_id"])
        out.append({"conversation_id": r["conversation_id"], "closed_at": ends.get(r["conversation_id"]),
                    "route": r["route"], "priority": r["priority"], "resolution": r["resolution"],
                    "predicted_satisfaction": None if s is None else round(s, 3),
                    "shortfall": None if s is None else round((5 - min(max(s, 1), 5)) / 4, 4),
                    "model": (card or {}).get("model"),
                    "use": "reward" if g["usable_for_reward"] and s is not None else "kpi_only"})
    return out, g


def aggregate(records: list[dict], step_min: int = 5) -> list[dict]:
    """Sum of shortfall per (step start, route), the signal EnvV3's csat term would read."""
    acc = defaultdict(lambda: {"n": 0, "shortfall_sum": 0.0, "use": set()})
    for r in records:
        if r["shortfall"] is None or not r["closed_at"]:
            continue
        t = datetime.fromisoformat(r["closed_at"])
        step = t.replace(minute=t.minute - t.minute % step_min, second=0, microsecond=0).isoformat()
        a = acc[(step, r["route"])]
        a["n"] += 1
        a["shortfall_sum"] += r["shortfall"]
        a["use"].add(r["use"])
    return [{"step_start": k[0], "route": k[1], "n": v["n"], "shortfall_sum": round(v["shortfall_sum"], 4),
             "use": "reward" if v["use"] == {"reward"} else "kpi_only"} for k, v in sorted(acc.items())]


def make_card(model: str, result_json: dict, label_type: str, domain: str) -> dict:
    """Validation card from an Agent F benchmark result JSON (v3/f/results/...). Only measured fields are used."""
    t = result_json.get("test", result_json)
    return {"model": model, "label_type": label_type, "domain": domain,
            "test_n": t.get("n") or result_json.get("test_n"), "mae": t.get("mae") or result_json.get("test_mae"),
            "mae_mean_baseline": result_json.get("mae_mean_baseline"),
            "spearman": t.get("spearman") or result_json.get("test_spearman"),
            "spearman_ci_low": t.get("spearman_ci_low") or result_json.get("test_spearman_ci_low"),
            "source": result_json.get("_source")}
