"""Turn e_calibration.json (from prepare_subset.py) into an Agent E simulator config.

What is changed, and why only this:
- queue mix: the TOTAL arrival rate is kept (it is not observable from messages without timestamps), only its
  split across the 4 queues follows the real intent distribution;
- service time per queue: only if the real data had handle times (otherwise the simulator's assumption stays).
Hourly arrival shape, patience and abandonment are NOT taken from messages (needs operational logs).
"""

import json
from dataclasses import replace
from pathlib import Path

from env.callcenter_env import QUEUES, REWARD_PRESETS, EnvConfig


def env_config(preset: str = "balanced", calibration: str | None = None) -> EnvConfig:
    cfg = EnvConfig(**REWARD_PRESETS[preset])
    if not calibration:
        return cfg
    cal = json.loads(Path(calibration).read_text())
    share = cal["queue_share"]
    total = sum(cfg.base_rate)
    # a queue with no real traffic keeps a small floor so the action space stays meaningful
    raw = [max(share.get(q, 0.0), 0.02) for q in QUEUES]
    s = sum(raw)
    cfg = replace(cfg, base_rate=tuple(round(total * x / s, 4) for x in raw))
    svc = cal.get("service_min_by_queue")
    if isinstance(svc, dict):
        cfg = replace(cfg, service_min=tuple(float(svc.get(q, d)) for q, d in zip(QUEUES, cfg.service_min)))
    return cfg
