"""Priority of a ticket: based on the REAL situation first, and only a little on how upset the client sounds.

    severity          (0-1) = base for the reason + 0.3 if days_late > 5 + 0.2 if paid > 300   (max 1)
                              (the 300 TND is read from rule R-ESC-01, the same threshold as finance approval)
    time_pressure     (0-1) = min(days_late / 7, 1)   (0 if no order, not late, or delivered)
    emotion_intensity (0-1) = negative-sentiment score
    priority = 0.6 * severity + 0.25 * time_pressure + 0.15 * emotion_intensity
    label: high >= 0.6, medium >= 0.35, else low

Why these weights? Facts (severity + time pressure = 85%) decide; emotion only breaks ties (15%).
So a calm client whose order is 6 days late gets served before an angry client whose order is on time.
All numbers live in config.yaml (intake.priority), so they can change without touching this code.

T21, Atlas Travel: the same weights and labels, with its own two parts (config.yaml companies.atlas.priority):
    severity      = base of the most severe reason
    time_pressure = 1.0 if the departure / arrival is within 24 h, 0.5 within 72 h, else 0 (past trips: 0)
"""

from callverse import companies
from callverse.config import load_config
from callverse.kb.policies import layer3_threshold


def severity(reasons: list[str], days_late: int | None, paid: float | None, cfg: dict) -> float:
    """Base of the most severe reason found (a ticket is as serious as its worst sub-case) + fact bonuses."""
    base = max((cfg["severity_base"].get(r, cfg["severity_base"]["other"]) for r in reasons),
               default=cfg["severity_base"]["other"])
    value = base
    if days_late is not None and days_late > cfg["late_bonus"]["days_late_over"]:
        value += cfg["late_bonus"]["add"]
    # Large amount = above R-ESC-01's threshold (single source: the policy file, not config.yaml).
    if paid is not None and paid > layer3_threshold():
        value += cfg["amount_bonus"]["add"]
    return min(value, 1.0)


def time_pressure(days_late: int | None, cfg: dict) -> float:
    """How urgent in time: 0 when there is no order or it is not late, 1 when a week late or more."""
    if not days_late or days_late <= 0:
        return 0.0
    return min(days_late / cfg["time_pressure_days"], 1.0)


def trip_pressure(hours_to_start: float | None, steps: list) -> float:
    """Atlas: how soon the trip starts. steps = [[hours, pressure], ...], nearest first. A past trip: 0."""
    if hours_to_start is None or hours_to_start < 0:
        return 0.0
    return next((pressure for hours, pressure in steps if hours_to_start <= hours), 0.0)


def compute(reasons: list[str], facts: dict, negative_score: float, company: str = companies.DEFAULT) -> dict:
    """Return severity, time_pressure, emotion_intensity, priority_score and priority_label.

    facts = {"days_late", "delivered", "paid"} from the tools (values are None when there is no order);
    Atlas: {"hours_to_start"}.
    """
    cfg = load_config()["intake"]["priority"]
    if company == "atlas":
        own = companies.get(company)["priority"]
        base = own["severity_base"]
        sev = max((base.get(r, base["other"]) for r in reasons), default=base["other"])
        tp = trip_pressure(facts.get("hours_to_start"), own["time_pressure_hours"])
    else:
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
