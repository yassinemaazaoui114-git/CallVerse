"""Reads config.yaml once and gives the rest of the code access to it."""

from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

# Project root = the folder that contains config.yaml (one level above this package).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


@lru_cache(maxsize=1)
def load_config() -> dict:
    """Return the whole config.yaml as a Python dict (read from disk only the first time)."""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def sim_today() -> date:
    """The fixed simulation date. We use it instead of the real clock so demos are reproducible."""
    return date.fromisoformat(load_config()["sim_today"])
