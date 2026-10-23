"""Intake -> Agent E adapter: the structured ticket fields Agent E may use, and nothing else.

Agent E never reads customer text. Intake (callverse/intake) already turned the message into:
    reasons, facts {days_late, delivered, paid}, negative_score -> severity, time_pressure, emotion_intensity,
    priority_score, priority_label  (priority = 0.6*severity + 0.25*time_pressure + 0.15*emotion, config.yaml)
This file
  1. re-implements that priority formula VECTORISED (the simulator creates thousands of tickets a day) with the
     numbers read from the prototype's config.yaml; tests/test_intake_env.py checks it equals
     callverse.intake.priority.compute exactly;
  2. samples synthetic Intake outputs per queue for the simulator (distributions below; lateness and order value
     from the public Olist data, results/real_olist/intake_stats.json; emotion = ASSUMPTION);
  3. turns one real Intake ticket dict into the fields the simulator / Agent E use (from_intake_ticket).
The 60/25/15 weights decide the priority LABEL only. They are never used as Agent E's reward weights.
"""

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]                       # repository root
LABELS = ("low", "medium", "high")                               # rank 0, 1, 2

# which Intake reasons arrive in which Agent E queue, and how often (ASSUMPTION, editable)
QUEUE_REASONS = {
    0: (("order_status", 0.6), ("late_delivery", 0.4)),          # A status / tracking
    1: (("refund_request", 0.65), ("return_item", 0.35)),        # B payment / refund
    2: (("damaged_item", 1.0),),                                  # C urgent problems
    3: (("other", 1.0),),                                         # D availability / other
}
LATE_REASONS = {"late_delivery"}                                  # these tickets are about a late order


def load_priority_cfg() -> dict:
    """The prototype's intake.priority section + the R-ESC-01 amount threshold (same sources as priority.py)."""
    import yaml
    cfg = yaml.safe_load(open(ROOT / "config.yaml"))["intake"]["priority"]
    import ast
    pol = json.loads(open(ROOT / "callverse" / "kb" / "policies_shopnova.json").read())
    cond = next(p["condition"] for p in pol if p["id"] == "R-ESC-01")          # e.g. "amount > 300"
    cfg = dict(cfg)
    cfg["_amount_threshold"] = float(ast.literal_eval(ast.parse(cond, mode="eval").body.comparators[0]))
    return cfg


def priority_vec(sev_base, days_late, delivered, paid, emotion, cfg):
    """Vectorised callverse.intake.priority.compute -> (severity, time_pressure, emotion, score, label_rank)."""
    sev = np.array(sev_base, float)
    dl = np.nan_to_num(np.array(days_late, float), nan=0.0)
    sev = sev + np.where(dl > cfg["late_bonus"]["days_late_over"], cfg["late_bonus"]["add"], 0.0)
    sev = sev + np.where(np.nan_to_num(np.array(paid, float), nan=0.0) > cfg["_amount_threshold"],
                         cfg["amount_bonus"]["add"], 0.0)
    sev = np.minimum(sev, 1.0)
    tp = np.where((dl > 0) & ~np.array(delivered, bool), np.minimum(dl / cfg["time_pressure_days"], 1.0), 0.0)
    emo = np.clip(np.array(emotion, float), 0.0, 1.0)
    w = cfg["weights"]
    score = w["severity"] * sev + w["time_pressure"] * tp + w["emotion_intensity"] * emo
    rank = np.where(score >= cfg["labels"]["high"], 2, np.where(score >= cfg["labels"]["medium"], 1, 0))
    return sev, tp, emo, score, rank


class TicketSampler:
    """Draws the Intake fields of n new tickets in one queue (one random generator = reproducible days)."""

    def __init__(self, cfg=None, stats_path=None):
        self.cfg = cfg or load_priority_cfg()
        sp = Path(stats_path or Path(__file__).resolve().parents[1] / "results" / "real_olist" / "intake_stats.json")
        st = json.loads(sp.read_text()) if sp.exists() else {}
        q = st.get("late_days_quantiles_given_late", {"0": 0.0, "50": 5.8, "100": 30.0})
        self.late_q = np.array([q[k] for k in sorted(q, key=float)], float)
        self.late_share = float(st.get("late_share", 0.08))
        self.paid_over = float(st.get("order_value_share_over_300", 0.10))
        self.base = self.cfg["severity_base"]

    def sample(self, q: int, n: int, rng: np.random.Generator):
        names, probs = zip(*QUEUE_REASONS[q])
        reasons = rng.choice(len(names), size=n, p=probs)
        sev_base = np.array([self.base.get(names[r], self.base["other"]) for r in reasons])
        is_late_reason = np.array([names[r] in LATE_REASONS for r in reasons])
        late = is_late_reason | (rng.random(n) < self.late_share)
        days = np.where(late, np.interp(rng.random(n), np.linspace(0, 1, len(self.late_q)), self.late_q), 0.0)
        days = np.round(days)
        delivered = np.where(is_late_reason, rng.random(n) < 0.3, rng.random(n) < 0.7)
        paid = np.where(rng.random(n) < self.paid_over, 400.0, 100.0)
        # ASSUMPTION: customers with long delays sound more upset (emotion only breaks ties in the priority)
        emo = np.where(days > 5, rng.beta(5, 2, n), rng.beta(2, 5, n))
        sev, tp, emo, score, rank = priority_vec(sev_base, days, delivered, paid, emo, self.cfg)
        return score.astype(np.float32), rank.astype(np.int8), emo.astype(np.float32)


def from_intake_ticket(ticket: dict) -> dict:
    """Real prototype ticket (callverse.intake output) -> the only fields Agent E's simulator/queue uses."""
    return {"priority_score": float(ticket["priority_score"]),
            "priority_rank": LABELS.index(ticket["priority_label"]),
            "emotion_intensity": float(ticket.get("emotion_intensity", 0.0))}
