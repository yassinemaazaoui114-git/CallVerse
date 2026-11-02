"""RL5: the style policy. A small bandit that picks HOW a reply is said: short, warm or warm_next_step.

Why a bandit? Each reply is one try: we pick a style, the client (or a rater) gives a score, and we want to pick the
better style more often next time, while still trying the others a little. That is a "multi-armed bandit". We use
Thompson sampling: for each style we keep a Beta(alpha, beta) belief about its reward (reward scaled to 0..1). To choose,
we draw one random number from each style's belief and take the style with the highest draw. A style with few tries has
a wide belief, so it still gets drawn sometimes (exploration); a style that keeps scoring well wins more and more.

What the policy may change: ONLY decision["reply_style"] (callverse/slm/reply_styles.py). Never the outcome, an amount,
a rule, must_say or the rule check. The Coordinator decided those before the policy runs.

Situation groups: one bandit per group, kept COARSE on purpose (we will have few ratings):
    group = (company, outcome class, emotion class)
    outcome class = approve / decline / ask / info / other    (from situation["outcome"])
    emotion class = angry / other    (angry = Intake emotion anger or disgust)
    Why not "or a negative sentiment"? Almost every complaint has a negative sentiment (24 of the 27 RL1 situations),
    so the split would mean nothing; anger / disgust is 5 of 27. One constant (ANGRY_EMOTIONS) to change if needed.
With fewer than MIN_OBS (5) observations in a group, the policy explores: it takes the least-tried style.

Storage: a small JSON file (config.yaml learning.style_policy_file). The log of every choice and reward is the
style_log table of the tickets DB (callverse/tickets/store.py).
"""

import json
import random
from pathlib import Path

from callverse.slm.reply_styles import REPLY_STYLES

STYLES = tuple(REPLY_STYLES)   # ("short", "warm", "warm_next_step"): the same names the writer knows
DEFAULT_STYLE = "warm"         # fixed fallback: used for a group with no data in best_per_group / best()
MIN_OBS = 5                    # fewer observations than this in a group -> explore (least-tried style)
ANGRY_EMOTIONS = ("anger", "disgust")
ASK_OUTCOMES = ("ask_user", "ask_proof")
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FILE = ROOT / "out" / "rl5_policy.json"


def outcome_class(outcome) -> str:
    """approve / decline / ask / info / other (coarse on purpose)."""
    if outcome in ("approve", "decline", "info"):
        return outcome
    if outcome in ASK_OUTCOMES:
        return "ask"
    return "other"


def emotion_class(situation: dict) -> str:
    """angry (Intake emotion anger or disgust) or other. The sentiment is not used (see the module text)."""
    if situation.get("emotion") in ANGRY_EMOTIONS:
        return "angry"
    return "other"


def group_of(situation: dict) -> str:
    """The group key as text, e.g. "shopnova|approve|angry"."""
    return f"{situation.get('company') or 'unknown'}|{outcome_class(situation.get('outcome'))}|{emotion_class(situation)}"


class StylePolicy:
    """Thompson sampling, one Beta(alpha, beta) per (group, style). Prior Beta(1, 1) = "no idea yet"."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else DEFAULT_FILE
        # stats[group][style] = {"alpha": float, "beta": float, "n": int, "total": float}
        self.stats: dict[str, dict[str, dict]] = {}

    def _arm(self, group: str, style: str) -> dict:
        arms = self.stats.setdefault(group, {})
        return arms.setdefault(style, {"alpha": 1.0, "beta": 1.0, "n": 0, "total": 0.0})

    def observations(self, group: str) -> int:
        return sum(a["n"] for a in self.stats.get(group, {}).values())

    def choose(self, situation: dict, rng: random.Random | None = None) -> str:
        """The style for this situation. Explores (least-tried style) until the group has MIN_OBS observations."""
        rng = rng or random.Random()
        group = group_of(situation)
        if self.observations(group) < MIN_OBS:
            tries = {s: self._arm(group, s)["n"] for s in STYLES}
            fewest = min(tries.values())
            return rng.choice([s for s in STYLES if tries[s] == fewest])
        draws = {s: rng.betavariate(self._arm(group, s)["alpha"], self._arm(group, s)["beta"]) for s in STYLES}
        return max(STYLES, key=lambda s: draws[s])

    def update(self, situation: dict, style: str, reward: float) -> None:
        """Learn from one reward in 0..1 (1 = best). A fractional reward adds to both counts (alpha += r, beta += 1 - r)."""
        if style not in STYLES:
            raise ValueError(f"unknown style {style!r}: use one of {STYLES}")
        r = float(reward)
        if not 0.0 <= r <= 1.0:
            raise ValueError(f"reward must be between 0 and 1, got {reward!r}")
        arm = self._arm(group_of(situation), style)
        arm["alpha"] += r
        arm["beta"] += 1.0 - r
        arm["n"] += 1
        arm["total"] += r

    def best(self, situation: dict) -> str:
        """The style with the best mean reward so far for this situation's group (DEFAULT_STYLE when no data)."""
        return self._best_of(group_of(situation))

    def _best_of(self, group: str) -> str:
        arms = {s: a for s, a in self.stats.get(group, {}).items() if a["n"] > 0}
        if not arms:
            return DEFAULT_STYLE
        return max(arms, key=lambda s: arms[s]["alpha"] / (arms[s]["alpha"] + arms[s]["beta"]))

    def best_per_group(self) -> dict[str, dict]:
        """{group: {"best": style, "n": observations, "mean": {style: mean reward or None}}} for the report / Console."""
        out = {}
        for group, arms in sorted(self.stats.items()):
            out[group] = {"best": self._best_of(group), "n": self.observations(group),
                          "mean": {s: (round(arms[s]["total"] / arms[s]["n"], 3) if s in arms and arms[s]["n"] else None)
                                   for s in STYLES}}
        return out

    def save(self, path: str | Path | None = None) -> Path:
        p = Path(path) if path else self.path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"styles": list(STYLES), "min_obs": MIN_OBS, "stats": self.stats}, indent=1),
                     encoding="utf-8")
        return p

    @classmethod
    def load(cls, path: str | Path | None = None) -> "StylePolicy":
        """Read the JSON file; a missing file gives an empty policy (it will explore)."""
        policy = cls(path)
        if policy.path.exists():
            policy.stats = json.loads(policy.path.read_text(encoding="utf-8")).get("stats", {})
        return policy
