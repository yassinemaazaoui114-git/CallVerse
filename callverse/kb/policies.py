"""Loads the ShopNova policy rules from policies_shopnova.json.

Each rule has:
- id         e.g. "R-REF-03" (agents cite it, the Coordinator looks it up)
- title      short name
- text       what agents read (and what policy search will index)
- condition  what the Coordinator checks in code, e.g. "days_late > 5 and not delivered"
             (null when the rule has nothing to check)
- ai_generated  true: the wording was written by an AI and is reviewed by Yassine

This file only LOADS and VALIDATES the rules. Searching them (RAG) and checking conditions
(Coordinator) are done by other parts of the code.
"""

import ast
import json
from pathlib import Path

POLICIES_PATH = Path(__file__).resolve().parent / "policies_shopnova.json"
REQUIRED_FIELDS = ("id", "title", "text", "condition")


def load_policies(path: str | Path = POLICIES_PATH) -> list[dict]:
    """Return the list of rules. Raises ValueError if a field is missing or an id is repeated."""
    with open(path, encoding="utf-8") as f:
        rules = json.load(f)

    seen = set()
    for rule in rules:
        missing = [field for field in REQUIRED_FIELDS if field not in rule]
        if missing:
            raise ValueError(f"policy {rule.get('id', '?')} is missing {missing}")
        if rule["id"] in seen:
            raise ValueError(f"policy id {rule['id']} appears twice")
        seen.add(rule["id"])
    return rules


def get_policy(rule_id: str) -> dict | None:
    """One rule by id, or None if it does not exist."""
    return next((r for r in load_policies() if r["id"] == rule_id), None)


def notification_events() -> list[str]:
    """The events a client can subscribe to, read from rule R-NOT-01's condition.

    The condition looks like: event in ['shipped', 'out_for_delivery', 'delivered'].
    We read the list from it (ast.literal_eval only reads plain values, it runs no code),
    so the policy file stays the single place where the list is written.
    """
    condition = get_policy("R-NOT-01")["condition"]
    compare = ast.parse(condition, mode="eval").body
    return list(ast.literal_eval(compare.comparators[0]))
