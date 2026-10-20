"""Priority of a ticket: based on the REAL situation first, and only a little on how upset the client sounds.

    severity          (0-1) = base for the reason + 0.3 if days_late > 5 + 0.2 if paid > 300   (max 1)
    time_pressure     (0-1) = min(days_late / 7, 1)   (0 if no order, not late, or delivered)
    emotion_intensity (0-1) = negative-sentiment score
    priority = 0.6 * severity + 0.25 * time_pressure + 0.15 * emotion_intensity
    label: high >= 0.6, medium >= 0.35, else low

Why these weights? Facts (severity + time pressure = 85%) decide; emotion only breaks ties (15%).
So a calm client whose order is 6 days late gets served before an angry client whose order is on time.
All numbers live in config.yaml (intake.priority), so they can change without touching this code.
"""

from callverse.config import load_config


def severity(reasons: list[str], days_late: int | None, paid: float | None, cfg: dict) -> float:
    """Base of the most severe reason found (a ticket is as serious as its worst sub-case) + fact bonuses."""
    base = max((cfg["severity_base"].get(r, cfg["severity_base"]["other"]) for r in reasons),
               default=cfg["severity_base"]["other"])
    value = base
    if days_late is not None and days_late > cfg["late_bonus"]["days_late_over"]:
        value += cfg["late_bonus"]["add"]
    if paid is not None and paid > cfg["amount_bonus"]["paid_over"]:
        value += cfg["amount_bonus"]["add"]
    return min(value, 1.0)


def time_pressure(days_late: int | None, cfg: dict) -> float:
    """How urgent in time: 0 when there is no order or it is not late, 1 when a week late or more."""
    if not days_late or days_late <= 0:
        return 0.0
    return min(days_late / cfg["time_pressure_days"], 1.0)


def compute(reasons: list[str], facts: dict, negative_score: float) -> dict:
    """Return severity, time_pressure, emotion_intensity, priority_score and priority_label.

    facts = {"days_late", "delivered", "paid"} from the tools (values are None when there is no order).
    """
    cfg = load_config()["intake"]["priority"]
    sev = severity(reasons, facts.get("days_late"), facts.get("paid"), cfg)
    # A delivered order has no time pressure left, even if it arrived late.
    tp = 0.0 if facts.get("delivered") else time_pressure(facts.get("days_late"), cfg)
    emo = max(0.0, min(negative_score, 1.0))

    w = cfg["weights"]
    score = w["severity"] * sev + w["time_pressure"] * tp + w["emotion_intensity"] * emo

    if score >= cfg["labels"]["high"]:
        label = "high"
    elif score >= cfg["labels"]["medium"]:
        label = "medium"
    else:
        label = "low"

    return {"severity": round(sev, 3), "time_pressure": round(tp, 3), "emotion_intensity": round(emo, 3),
            "priority_score": round(score, 3), "priority_label": label}
