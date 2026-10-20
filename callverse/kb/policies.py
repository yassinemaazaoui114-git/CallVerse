"""Loads the ShopNova policy rules from policies_shopnova.json.

Each rule has:
- id         e.g. "R-REF-03" (agents cite it, the Coordinator looks it up)
- title      short name
- text       what agents read (and what policy search will index)
- condition  what the Coordinator checks in code, e.g. "days_late > 5 and not delivered"
             (null when the rule has nothing to check)
- ai_generated  true: the wording was written by an AI and is reviewed by Yassine

This file LOADS and VALIDATES the rules, and can CHECK a rule's condition against facts
(check_condition). Searching the rules (RAG) and deciding what to do (Coordinator) live elsewhere.
"""

import ast
import json
import operator
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


def layer3_threshold() -> float:
    """The amount above which a refund needs finance (Layer 3), read from R-ESC-01's condition.

    The condition looks like: amount > 300. Same idea as notification_events(): one place only.
    """
    compare = ast.parse(get_policy("R-ESC-01")["condition"], mode="eval").body
    return float(ast.literal_eval(compare.comparators[0]))


# The only operators a condition may use. Anything else is refused (no eval(), no function calls).
_COMPARE = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
            ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.In: lambda a, b: a in b}
_MATH = {ast.Add: operator.add, ast.Sub: operator.sub}


def check_condition(condition: str, facts: dict) -> bool:
    """True if `condition` (e.g. "days_late > 5 and not delivered") holds for `facts`.

    The condition text is split into a tree by Python's parser (ast) and each piece is computed
    by hand below: names are looked up in `facts`, then plain comparisons, and/or/not, + and -.
    Money results are rounded to 2 decimals, so 59.90 - 0 is exactly 59.90.
    A missing fact or an unsupported piece raises ValueError.
    """
    def value(node):
        if isinstance(node, ast.BoolOp):
            results = [value(v) for v in node.values]
            return all(results) if isinstance(node.op, ast.And) else any(results)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not value(node.operand)
        if isinstance(node, ast.Compare):
            left = value(node.left)
            for op, right_node in zip(node.ops, node.comparators):  # handles 1 <= x <= 5
                if type(op) not in _COMPARE:
                    raise ValueError(f"unsupported comparison in condition: {condition}")
                right = value(right_node)
                if not _COMPARE[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.BinOp) and type(node.op) in _MATH:
            return round(_MATH[type(node.op)](value(node.left), value(node.right)), 2)
        if isinstance(node, ast.Name):
            if node.id not in facts:
                raise ValueError(f"missing fact '{node.id}' for condition: {condition}")
            return facts[node.id]
        if isinstance(node, (ast.Constant, ast.List)):
            return ast.literal_eval(node)
        raise ValueError(f"unsupported expression in condition: {condition}")

    return bool(value(ast.parse(condition, mode="eval").body))
