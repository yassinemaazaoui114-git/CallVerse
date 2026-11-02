"""The photo check's answer format: one JSON object, 6 keys, only things that can be SEEN.

Why a fixed format? The router and the Coordinator are rules: they need values they can compare, not prose.
Why no intent / emotion / refund field? A photo cannot prove what the customer wants or feels, and the model
must never decide anything. Those fields do not exist, so the model cannot fill them.

The prompt is the exact one used to train and benchmark the adapter (Kaggle, 2026-11-01): changing it would
change the model's behaviour without a new benchmark.
"""
import json
import re

ISSUE_TYPES = ["cracked_screen", "screen_display_defect", "damaged_packaging", "damaged_luggage",
               "dirty_or_messy_room", "damaged_room_fixture", "no_visible_issue", "unclear"]
DAMAGE_TYPES = ISSUE_TYPES[:6]
KEYS = ["visible_damage", "object", "issue_type", "description", "confidence_level", "requires_review"]

PROMPT = (
    "You check photos sent to a customer-service centre (an online shop and a travel agency).\n"
    "Describe ONLY what is visible in the photo. Do not guess the customer's wishes, feelings, identity, "
    "orders, bookings, payments or any decision.\n"
    "Return one JSON object and nothing else, with exactly these keys:\n"
    '{"visible_damage": true | false | null, "object": "<main object, snake_case>", '
    '"issue_type": "<one value from the list>", "description": "<one short sentence about what is visible>", '
    '"confidence_level": "high" | "medium" | "low", "requires_review": true | false}\n'
    "issue_type values: cracked_screen, screen_display_defect, damaged_packaging, damaged_luggage, "
    "dirty_or_messy_room, damaged_room_fixture, no_visible_issue, unclear.\n"
    "Rules: visible_damage is true only for clearly visible damage or dirt; false when the object looks intact "
    "or clean (issue_type no_visible_issue); null when the photo does not allow a decision (issue_type unclear, "
    "confidence_level low). requires_review is true whenever visible_damage is not false or confidence is not high."
)


def parse_output(text: str):
    """Return (assessment dict or None, reason). Valid = one JSON object, the 6 keys, allowed values."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None, "no_json"
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None, "bad_json"
    if not isinstance(obj, dict) or set(obj) != set(KEYS):
        return None, "wrong_keys"
    if obj["visible_damage"] not in (True, False, None):
        return None, "bad_visible_damage"
    if obj["issue_type"] not in ISSUE_TYPES:
        return None, "bad_issue_type"
    if obj["confidence_level"] not in ("high", "medium", "low"):
        return None, "bad_confidence"
    if not isinstance(obj["requires_review"], bool) or not isinstance(obj["description"], str) \
            or not isinstance(obj["object"], str):
        return None, "bad_types"
    return normalise(obj), "ok"


def normalise(obj: dict) -> dict:
    """Make the answer consistent with its own rules (the model can contradict itself):
    damage types -> visible_damage true; no_visible_issue -> false; unclear -> null + low confidence;
    requires_review true whenever damage is not ruled out or confidence is not high."""
    out = {k: obj[k] for k in KEYS}
    issue = out["issue_type"]
    if issue in DAMAGE_TYPES:
        out["visible_damage"] = True
    elif issue == "no_visible_issue":
        out["visible_damage"] = False
    else:
        out["visible_damage"], out["confidence_level"] = None, "low"
    out["requires_review"] = out["visible_damage"] is not False or out["confidence_level"] != "high"
    out["description"] = out["description"].strip()[:300]
    out["object"] = out["object"].strip()[:60] or "unknown"
    return out


def unclear(description: str) -> dict:
    """The answer used when the photo could not be checked (model down, invalid output): no decision possible."""
    return {"visible_damage": None, "object": "unknown", "issue_type": "unclear", "description": description,
            "confidence_level": "low", "requires_review": True}
