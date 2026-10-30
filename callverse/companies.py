"""The companies of the center (T21): one small registry, read from config.yaml (`companies:`).

CallVerse is ONE center for several companies. Each company brings its own reasons, rules, routes, finance limit and
data; the steps are the same for all (Intake, router, agents, Coordinator, reply writer). So the shared code never
says "if ShopNova": it asks this file for the value of the ticket's company.

The company comes from the CHANNEL (web_chat.send), never from the words of the message: a client cannot move a
ticket to another company by writing about it. It then travels on the ticket (ticket["company"]) to every step.
A ticket without a company is a ShopNova ticket, so old callers keep working.
"""

import importlib
from pathlib import Path

from callverse.config import PROJECT_ROOT, load_config

DEFAULT = "shopnova"


def names() -> list[str]:
    """All the companies of the center."""
    return list(load_config()["companies"])


def get(company: str) -> dict:
    """One company's settings. An unknown company is an error: it must never fall back to another company's data."""
    settings = load_config()["companies"].get(company)
    if settings is None:
        raise ValueError(f"unknown company '{company}' (known: {', '.join(names())})")
    return settings


def of(ticket: dict | None) -> str:
    """The ticket's company; no company on the ticket = ShopNova."""
    return (ticket or {}).get("company") or DEFAULT


def path(company: str, key: str) -> Path:
    """A file of this company (e.g. key "rules_file"), as a full path."""
    return PROJECT_ROOT / get(company)[key]


def module(company: str, key: str):
    """A code module of this company (e.g. key "coordinator"), imported when it is first needed."""
    return importlib.import_module(get(company)[key])


def extra_args(company: str) -> dict:
    """The `company` argument for a call: nothing for ShopNova, so its calls stay exactly as they were."""
    return {} if company == DEFAULT else {"company": company}
