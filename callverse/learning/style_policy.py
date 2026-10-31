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


# ----------------------------------------------------------------------------- richer context + more algorithms
EMOTIONS = ["anger", "disgust", "fear", "joy", "neutral", "sadness", "surprise"]
OUTCOMES = ["approve", "info", "ask_proof", "layer3", "escalate", "send_back", "ask_user"]
REASONS = ["order_status", "late_delivery", "refund_request", "return_item", "damaged_item", "other", "booking_status",
           "delay_disruption", "cancellation", "compensation_request", "rebooking", "special_assistance"]


def context_vector(situation: dict) -> list[float]:
    """Observable context only (never the hidden persona): company, emotion, outcome, reason, lateness, priority."""
    late = situation.get("days_late") or 0
    return ([1.0, float(situation.get("company") == "atlas")]
            + [float(situation.get("emotion") == e) for e in EMOTIONS]
            + [float(situation.get("outcome") == o) for o in OUTCOMES]
            + [float(situation.get("reason") == r) for r in REASONS]
            + [float(late == 0), float(1 <= late <= 5), float(late > 5), float(situation.get("priority") == "high")])


class LinUCB:
    """One ridge model per style on the context vector; pick the arm with the highest upper confidence bound."""

    def __init__(self, alpha: float = 0.5, seed: int = 0, dim: int | None = None):
        import numpy as np
        self.np, self.alpha, self.seed = np, alpha, seed
        self.dim = dim or len(context_vector({}))
        self.A = {s: np.eye(self.dim) for s in STYLES}
        self.b = {s: np.zeros(self.dim) for s in STYLES}
        self.rng, self.n_updates = random.Random(seed), 0

    def _score(self, x, s, explore: bool):
        inv = self.np.linalg.inv(self.A[s])
        theta = inv @ self.b[s]
        return float(theta @ x + (self.alpha * self.np.sqrt(x @ inv @ x) if explore else 0.0))

    def choose(self, situation: dict) -> str:
        x = self.np.asarray(context_vector(situation))
        scores = {s: self._score(x, s, True) + self.rng.random() * 1e-9 for s in STYLES}   # tiny seeded tie-break
        return max(scores, key=scores.get)

    def best(self, situation: dict) -> str:
        x = self.np.asarray(context_vector(situation))
        return max(STYLES, key=lambda s: self._score(x, s, False))

    def update(self, situation: dict, style: str, reward) -> None:
        if reward is None:
            return
        x = self.np.asarray(context_vector(situation))
        self.A[style] += self.np.outer(x, x)
        self.b[style] += float(reward) * x
        self.n_updates += 1

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({"kind": "linucb", "alpha": self.alpha, "seed": self.seed, "dim": self.dim,
                                          "A": {s: self.A[s].tolist() for s in STYLES},
                                          "b": {s: self.b[s].tolist() for s in STYLES}, "n_updates": self.n_updates}))

    @classmethod
    def load(cls, path: Path) -> "LinUCB":
        d = json.loads(Path(path).read_text())
        p = cls(alpha=d["alpha"], seed=d["seed"], dim=d["dim"])
        p.A = {s: p.np.asarray(d["A"][s]) for s in STYLES}
        p.b = {s: p.np.asarray(d["b"][s]) for s in STYLES}
        p.n_updates = d["n_updates"]
        return p


class EpsilonGreedy:
    """Per-group running mean reward; explore with probability epsilon (decays with the group's visits)."""

    def __init__(self, epsilon: float = 0.2, seed: int = 0):
        self.epsilon, self.seed, self.rng = epsilon, seed, random.Random(seed)
        self.stats: dict[str, dict[str, list[float]]] = {}
        self.n_updates = 0

    def _arms(self, situation):
        return self.stats.setdefault(group_key(situation), {s: [0.0, 0.0] for s in STYLES})   # [sum, count]

    def best(self, situation: dict) -> str:
        arms = self._arms(situation)
        return max(STYLES, key=lambda s: (arms[s][0] / arms[s][1]) if arms[s][1] else 0.0)

    def choose(self, situation: dict) -> str:
        arms = self._arms(situation)
        visits = sum(c for _, c in arms.values())
        if self.rng.random() < self.epsilon / (1 + visits / 50) or any(c == 0 for _, c in arms.values()):
            return self.rng.choice([s for s in STYLES if arms[s][1] == 0] or STYLES)
        return self.best(situation)

    def update(self, situation: dict, style: str, reward) -> None:
        if reward is None:
            return
        arms = self._arms(situation)
        arms[style][0] += float(reward); arms[style][1] += 1
        self.n_updates += 1

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({"kind": "epsilon_greedy", "epsilon": self.epsilon, "seed": self.seed,
                                          "stats": self.stats, "n_updates": self.n_updates}))


class GaussianThompson:
    """Thompson sampling on the CONTINUOUS reward (Agent F satisfaction 1-5, or 1.0 on a FAIL) per group x style:
    keeps more information than the +1/-1 signal. Posterior: normal on the mean with known noise."""

    def __init__(self, seed: int = 0, noise: float = 0.8, prior_mean: float = 3.0):
        self.seed, self.noise, self.prior_mean = seed, noise, prior_mean
        self.rng, self.stats, self.n_updates = random.Random(seed), {}, 0

    def _arms(self, situation):
        return self.stats.setdefault(group_key(situation), {s: [0.0, 0.0] for s in STYLES})   # [sum, count]

    def _post(self, arm):
        n = arm[1]
        mean = (self.prior_mean + arm[0]) / (1 + n)
        return mean, self.noise / ((1 + n) ** 0.5)

    def choose(self, situation: dict) -> str:
        arms = self._arms(situation)
        draws = {s: self.rng.gauss(*self._post(arms[s])) for s in STYLES}
        return max(draws, key=draws.get)

    def best(self, situation: dict) -> str:
        arms = self._arms(situation)
        return max(STYLES, key=lambda s: self._post(arms[s])[0])

    def update(self, situation: dict, style: str, reward) -> None:
        if reward is None:
            return
        arms = self._arms(situation)
        arms[style][0] += float(reward); arms[style][1] += 1
        self.n_updates += 1

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({"kind": "gaussian_thompson", "seed": self.seed, "noise": self.noise,
                                          "prior_mean": self.prior_mean, "stats": self.stats, "n_updates": self.n_updates}))


def supervised_group_policy(rows: list[dict]) -> dict[str, str]:
    """Supervised policy selection: best style per observable group by mean rating on TRAINING rows (clean replies)."""
    from collections import defaultdict
    acc = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r.get("corruption") is None and r.get("degradation") is None:
            acc[group_key(r["situation"])][r["style"]].append(float(r["rating"]))
    return {g: max(STYLES, key=lambda s: (sum(v[s]) / len(v[s])) if v[s] else 0.0) for g, v in acc.items()}


def from_table(table: dict[str, str], default: str = "apology_next_step"):
    return lambda situation: table.get(group_key(situation), default)


def agent_f_argmax(predict_fn, write_fn, decision_of):
    """Counterfactual choice at inference: write the 3 styles, pick the one Agent F scores highest."""
    def pick(situation: dict) -> str:
        d = decision_of(situation)
        scores = {s: predict_fn({"company": situation.get("company"), "situation": situation, "style": s,
                                 "decision": d, "messages": [{"role": "user", "text": situation.get("first_message", "")},
                                                             {"role": "assistant", "text": write_fn(d, s)}]})
                  for s in STYLES}
        return max(scores, key=scores.get)
    return pick
