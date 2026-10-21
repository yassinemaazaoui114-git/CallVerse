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


def sim_start() -> date:
    """The date the simulation starts on (sim_today in config.yaml, 2026-10-09). Never moves."""
    return date.fromisoformat(load_config()["sim_today"])


def sim_today() -> date:
    """Today in the simulation: the date of the simulation clock (callverse/data/clock.py).

    The clock starts at sim_start() and only moves when clock.advance() is called (story S3), so if nobody
    moves it this is the fixed date from config.yaml, as before. Never the real computer clock.
    """
    from callverse.data import clock   # imported here: the clock needs the database, config must not at import
    return clock.now().date()
