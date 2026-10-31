"""Contextual bandit for the reply STYLE (RL5 minimal version): Thompson sampling, one Beta arm per
(situation group, style). Plain code, CPU, deterministic with a seed.

The policy chooses only HOW the Coordinator's decision is said (short / apology_first / apology_next_step).
It never sees or changes amounts, rules, facts or outcomes: its context is a small group key built from the
situation, and its reward is Agent F's dual reward (+1 / -1; None = not learned from).

    policy = StylePolicy(seed=0)
    style = policy.choose(situation)               # explore / exploit (Thompson)
    policy.update(situation, style, reward)        # +1 -> success, -1 -> failure, None -> ignored
    policy.best(situation)                         # greedy choice (evaluation)
    policy.save(path) / StylePolicy.load(path)     # JSON persistence
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from callverse.learning.style_writer import STYLES

UPSET = {"anger", "disgust", "sadness", "fear"}


def group_key(situation: dict) -> str:
    """Context -> group: company | upset or calm | outcome family | late or not."""
    mood = "upset" if situation.get("emotion") in UPSET else "calm"
    outcome = situation.get("outcome") or "info"
    family = outcome if outcome in ("approve", "info") else "other"
    late = "late" if (situation.get("days_late") or 0) > 0 else "ontime"
    return f"{situation.get('company', 'shopnova')}|{mood}|{family}|{late}"


class StylePolicy:
    def __init__(self, seed: int = 0, prior: float = 1.0):
        self.rng = random.Random(seed)
        self.seed, self.prior = seed, prior
        self.arms: dict[str, dict[str, list[float]]] = {}   # group -> style -> [successes, failures]
        self.n_updates = 0

    def _arms(self, situation: dict) -> dict[str, list[float]]:
        return self.arms.setdefault(group_key(situation), {s: [0.0, 0.0] for s in STYLES})

    def choose(self, situation: dict) -> str:
        arms = self._arms(situation)
        draws = {s: self.rng.betavariate(self.prior + a, self.prior + b) for s, (a, b) in arms.items()}
        return max(draws, key=draws.get)

    def best(self, situation: dict) -> str:
        arms = self._arms(situation)
        return max(STYLES, key=lambda s: (self.prior + arms[s][0]) / (2 * self.prior + arms[s][0] + arms[s][1]))

    def update(self, situation: dict, style: str, reward) -> None:
        if reward is None:
            return                                   # UNKNOWN correctness: excluded from training
        arms = self._arms(situation)
        arms[style][0 if reward > 0 else 1] += 1
        self.n_updates += 1

    def summary(self) -> dict:
        return {g: {s: {"wins": a, "losses": b, "p": round((self.prior + a) / (2 * self.prior + a + b), 3)}
                    for s, (a, b) in arms.items()} for g, arms in sorted(self.arms.items())}

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"seed": self.seed, "prior": self.prior, "arms": self.arms,
                                    "n_updates": self.n_updates, "styles": STYLES}, indent=2))

    @classmethod
    def load(cls, path: Path) -> "StylePolicy":
        d = json.loads(Path(path).read_text())
        p = cls(seed=d["seed"], prior=d["prior"])
        p.arms, p.n_updates = d["arms"], d["n_updates"]
        return p


# Fixed baselines for the evaluation (RL6).
def always(style: str):
    return lambda situation: style


def random_style(seed: int = 0):
    rng = random.Random(seed)
    return lambda situation: rng.choice(STYLES)


def rule_based(situation: dict) -> str:
    """Hand-written rule: upset customer -> apology first, else short."""
    return "apology_first" if situation.get("emotion") in UPSET else "short"
