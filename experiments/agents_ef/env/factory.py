"""One place that builds Agent E simulators, so training, benchmarks and frontiers always use the same config.

make_env("v1" | "intake", preset, calibration, overrides, scenarios)
  v1      = env/callcenter_env.py  (simulated benchmark of the first report; default preset "balanced")
  intake  = env/intake_env.py      (Intake-aware; default preset "intake": fallback capped at 25 % of the day)
overrides = EnvConfig fields, e.g. {"load_sigma": 0.43, "hourly_profile": "flat", "shape_pool": ["two_peak", "flat"]}
Demand shapes by name (8 values = relative demand per hour of the simulated day):
  two_peak  the original assumed shape            flat     Olist orders 10:00-18:00 (real, near flat)
  morning   front-loaded (assumed)                evening  back-loaded (assumed) - kept OUT of every training pool
"""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np

from env.callcenter_env import CallCenterEnv, profile

_x = (np.arange(8) + 0.5) / 8
SHAPES = {
    "two_peak": tuple(round(float(profile(x)), 4) for x in _x),
    "morning": (1.5, 1.45, 1.3, 1.05, 0.85, 0.7, 0.6, 0.55),
    "evening": (0.55, 0.6, 0.7, 0.85, 1.05, 1.3, 1.45, 1.5),
}
_olist = Path(__file__).resolve().parents[1] / "results" / "real_olist" / "e_calibration_olist.json"
SHAPES["flat"] = tuple(json.loads(_olist.read_text())["hourly_profile_8h"]) if _olist.exists() else (1.0,) * 8


def _shape(v):
    return SHAPES[v] if isinstance(v, str) else tuple(float(x) for x in v)


def make_config(kind="v1", preset=None, calibration=None, overrides=None):
    from real_data.calibration import env_config
    cfg = env_config(preset or ("intake" if kind == "intake" else "balanced"), calibration)
    ov = dict(overrides or {})
    if "hourly_profile" in ov:
        ov["hourly_profile"] = _shape(ov["hourly_profile"])
    if "shape_pool" in ov:
        ov["shape_pool"] = tuple(_shape(s) for s in ov["shape_pool"])
    ov = {k: tuple(v) if isinstance(v, list) else v for k, v in ov.items()}
    return replace(cfg, **ov)


def make_env(kind="v1", preset=None, calibration=None, overrides=None, scenarios=None, **kw):
    cfg = make_config(kind, preset, calibration, overrides)
    sc = scenarios or ("normal", "high", "spike", "drift", "slowdown", "failure")
    if kind == "intake":
        from env.intake_env import IntakeAwareEnv
        return IntakeAwareEnv(cfg, sc, **kw)
    return CallCenterEnv(cfg, sc, **kw)


def obs_dim(kind="v1"):
    if kind == "intake":
        from env.intake_env import IntakeAwareEnv
        return IntakeAwareEnv.obs_dim
    return CallCenterEnv.obs_dim
