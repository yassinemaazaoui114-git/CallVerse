"""Agent E v3 scenarios: EXOGENOUS day specifications, independent of any policy.

A scenario = everything the world does on one day (demand level and shape, queue mix, spikes, HIGH-priority
surges, slowdowns, capacity failures). env_v3 turns a (spec, seed) pair into a fixed TAPE of tickets and events
BEFORE any decision is taken, so every policy evaluated on the same (spec, seed) faces exactly the same world.

Workload is defined by the offered-load ratio
    rho = mean over the day of  sum_q lambda_q(t) * service_q / step   /   planned sessions (16)
i.e. how many sessions the demand needs on average relative to the planned staffing (not by multiplying
arrivals blindly). Regimes: under 0.6 | near 0.9 | moderate overload 1.1 | severe overload 1.3
(budget = 1.15 x planned staffing, so rho 1.3 cannot be fully served within budget).

Families (TRAIN draws random parameters from the TRAIN families; VAL/TEST use fixed manifests):
  normal, morning_peak, two_peak, tracking_spike (A), volatile, slowdown, failure,
  high_priority_surge                                                     -> train + val + test (in-distribution)
  evening_peak, refund_surge (B), combined_shock, severe_overload, random_shape -> TEST ONLY (held out)
"""

from dataclasses import asdict, dataclass, field

import numpy as np

QUEUES = ["A_status", "B_refund", "C_urgent", "D_availability"]
BASE_MIX = np.array([5.0, 2.6, 1.8, 5.6]) / 15.0      # queue shares (ASSUMPTION, same as v1/v2)
SERVICE_MIN = np.array([4.0, 8.0, 6.0, 3.0])          # ASSUMPTION (v1/v2)
STEP_MIN, STEPS, PLANNED = 5.0, 96, 16

SHAPES = {   # relative demand per hour of the 8-hour day (mean 1 after normalisation)
    "flat_real": (0.9667, 1.0295, 0.9383, 1.0201, 1.0281, 1.0101, 1.0447, 0.9625),   # Olist orders 10-18 h
    "two_peak": (0.8, 1.35, 1.25, 0.8, 0.85, 1.25, 1.0, 0.7),
    "morning": (1.5, 1.45, 1.3, 1.05, 0.85, 0.7, 0.6, 0.55),
    "evening": (0.55, 0.6, 0.7, 0.85, 1.05, 1.3, 1.45, 1.5),                       # held out
}
TRAIN_FAMILIES = ["normal", "morning_peak", "two_peak", "tracking_spike", "volatile", "slowdown", "failure",
                  "high_priority_surge"]
HELDOUT_FAMILIES = ["evening_peak", "refund_surge", "combined_shock", "severe_overload", "random_shape"]


@dataclass
class Spec:
    family: str
    rho: float = 0.9
    shape: tuple = SHAPES["flat_real"]
    mix: tuple = tuple(BASE_MIX)
    spikes: list = field(default_factory=list)          # [(queue, start_step, end_step, multiplier)]
    high_surge: tuple = ()                               # (start, end, extra_late_share) more late orders -> HIGH
    slowdown: tuple = ()                                 # (start, end, service_time_multiplier)
    failure: tuple = ()                                  # (start, end, sessions_lost)

    def to_dict(self):
        return asdict(self)


def _norm(shape):
    s = np.asarray(shape, float)
    return tuple((s / s.mean()).round(4))


def make_spec(family: str, rng: np.random.Generator, rho: float | None = None) -> Spec:
    """Draw one day of a family. All randomness from `rng` (the scenario stream)."""
    r = rho if rho is not None else float(rng.choice([0.6, 0.8, 0.9, 1.0, 1.1]))
    s = Spec(family=family, rho=r)
    if family == "normal":
        s.shape = _norm(SHAPES["flat_real"])
    elif family == "morning_peak":
        s.shape = _norm(SHAPES["morning"])
    elif family == "two_peak":
        s.shape = _norm(SHAPES["two_peak"])
    elif family == "evening_peak":
        s.shape = _norm(SHAPES["evening"])
    elif family == "random_shape":                       # unfamiliar: smooth random curve, never seen in training
        k = rng.uniform(0.4, 1.6, 4)
        s.shape = _norm(np.interp(np.linspace(0, 3, 8), np.arange(4), k))
    else:
        s.shape = _norm(SHAPES["flat_real"])
    if family == "tracking_spike":
        st = int(rng.integers(12, 70))
        s.spikes = [(0, st, st + int(rng.integers(6, 15)), float(rng.uniform(2.5, 4.0)))]
    if family == "refund_surge":
        st = int(rng.integers(12, 60))
        s.spikes = [(1, st, st + int(rng.integers(12, 30)), float(rng.uniform(2.0, 3.0)))]
    if family == "volatile":
        s.rho = float(np.clip(r * rng.lognormal(-0.43 ** 2 / 2, 0.43), 0.4, 1.6))     # Olist daily CV 0.43
    if family == "high_priority_surge":
        st = int(rng.integers(12, 60))
        s.high_surge = (st, st + int(rng.integers(12, 30)), float(rng.uniform(0.3, 0.6)))
    if family == "slowdown":
        st = int(rng.integers(12, 48))
        s.slowdown = (st, st + int(rng.integers(15, 30)), float(rng.uniform(1.3, 1.7)))
    if family == "failure":
        st = int(rng.integers(12, 48))
        s.failure = (st, st + int(rng.integers(10, 25)), int(rng.integers(4, 9)))
    if family == "combined_shock":                       # demand + capacity shocks at once (held out)
        st = int(rng.integers(12, 40))
        s.spikes = [(int(rng.integers(4)), st, st + 12, float(rng.uniform(2.5, 3.5)))]
        s.slowdown = (st + 4, st + 30, float(rng.uniform(1.3, 1.6)))
        s.failure = (st + 8, st + 24, int(rng.integers(4, 8)))
        s.rho = max(r, 0.9)
    if family == "severe_overload":
        s.rho = 1.3
    return s


# ------------------------------------------------------------------ fixed manifests (VAL / locked TEST)
VAL_SEED0, TEST_SEED0 = 500_000, 900_000          # disjoint from TRAIN seeds (0..199_999) and from v1/v2 seeds


def manifest(split: str, days_per_family: int) -> list[dict]:
    """[{day_id, family, seed}] - the seed fixes BOTH the spec draw and the tape."""
    fams = TRAIN_FAMILIES if split == "val" else TRAIN_FAMILIES + HELDOUT_FAMILIES
    s0 = VAL_SEED0 if split == "val" else TEST_SEED0
    return [{"day_id": f"{split}-{f}-{i:03d}", "family": f, "seed": s0 + 1000 * k + i}
            for k, f in enumerate(fams) for i in range(days_per_family)]
