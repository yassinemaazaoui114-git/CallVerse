"""Validate satisfaction records against the PROPOSED reviews contract (reviews.schema.json + reviews_contract.md).

    python -m v4.f.contracts.validate_reviews <records.jsonl>        -> prints problems per record, exit 1 if any

No new library: `jsonschema` is not installed in this project, so this file checks the small subset of JSON Schema
that reviews.schema.json uses (type, enum, const, required, additionalProperties: false, properties,
minimum/maximum, minLength/maxLength, pattern, array items, uniqueItems; "format" is checked for date-time only),
then the CROSS-FIELD rules of the contract, which keep a measured rating and an AI prediction apart:
  R1 rating (1-5) only for customer_submitted / annotator records; predicted_score must be null there
  R2 ai_predicted records: rating must be null; predicted_score and prediction{} are required
  R3 annotator records need annotator_id
  R4 feedback_text may be stored only if pii_redaction.status is "redacted" or "none_found"
  R5 customer_submitted records need consent.given = true (otherwise they must not be stored at all)
usable_for_validation(record) says if a record may be used to VALIDATE a satisfaction model (measured rating,
consent scope includes model_validation, not a duplicate, not test/synthetic).
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

SCHEMA = json.loads((Path(__file__).resolve().parent / "reviews.schema.json").read_text())
TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list,
         "null": type(None)}


def _type_ok(v, t):
    if t == "integer" and isinstance(v, bool):
        return False
    if t == "number" and isinstance(v, bool):
        return False
    return isinstance(v, TYPES[t])


def check_schema(v, s, path="$") -> list[str]:
    errs = []
    if "const" in s and v != s["const"]:
        return [f"{path}: must be {s['const']!r}"]
    if "enum" in s and v not in s["enum"]:
        return [f"{path}: {v!r} not in {s['enum']}"]
    if "type" in s:
        ts = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(_type_ok(v, t) for t in ts):
            return [f"{path}: type {type(v).__name__}, expected {ts}"]
    if v is None:
        return errs
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if "minimum" in s and v < s["minimum"]:
            errs.append(f"{path}: {v} < {s['minimum']}")
        if "maximum" in s and v > s["maximum"]:
            errs.append(f"{path}: {v} > {s['maximum']}")
    if isinstance(v, str):
        if len(v) < s.get("minLength", 0):
            errs.append(f"{path}: too short")
        if "maxLength" in s and len(v) > s["maxLength"]:
            errs.append(f"{path}: longer than {s['maxLength']}")
        if "pattern" in s and not re.search(s["pattern"], v):
            errs.append(f"{path}: does not match {s['pattern']}")
        if s.get("format") == "date-time":
            try:
                datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                errs.append(f"{path}: not an ISO 8601 date-time")
    if isinstance(v, dict):
        props = s.get("properties", {})
        for k in s.get("required", []):
            if k not in v:
                errs.append(f"{path}.{k}: required")
        for k, x in v.items():
            if k in props:
                errs += check_schema(x, props[k], f"{path}.{k}")
            elif s.get("additionalProperties") is False:
                errs.append(f"{path}.{k}: unknown field")
    if isinstance(v, list):
        if s.get("uniqueItems") and len({json.dumps(x, sort_keys=True) for x in v}) != len(v):
            errs.append(f"{path}: repeated items")
        for i, x in enumerate(v):
            errs += check_schema(x, s.get("items", {}), f"{path}[{i}]")
    return errs


def check_rules(r: dict) -> list[str]:
    errs, src = [], r.get("rating_source")
    if src in ("customer_submitted", "annotator"):
        if r.get("rating") is None:
            errs.append("R1: a measured record needs rating 1-5")
        if r.get("predicted_score") is not None or r.get("prediction") is not None:
            errs.append("R1: a measured record must not carry predicted_score / prediction")
    if src == "ai_predicted":
        if r.get("rating") is not None:
            errs.append("R2: an ai_predicted record must have rating = null (a prediction is not a rating)")
        if r.get("prediction") is None:
            errs.append("R2: an ai_predicted record needs prediction {model_id, model_sha256, ...}")
        if r.get("predicted_score") is None and (r.get("prediction") or {}).get("validity") not in (
                "withheld_language_not_validated", "no_score"):
            errs.append("R2: predicted_score missing although the prediction was not withheld")
    if src == "annotator" and not r.get("annotator_id"):
        errs.append("R3: annotator records need annotator_id")
    if r.get("feedback_text") and (r.get("pii_redaction") or {}).get("status") not in ("redacted", "none_found"):
        errs.append("R4: feedback_text stored without PII redaction")
    if src == "customer_submitted" and not (r.get("consent") or {}).get("given"):
        errs.append("R5: customer rating without consent must not be stored")
    return errs


def validate(record: dict) -> list[str]:
    return check_schema(record, SCHEMA) + check_rules(record)


def usable_for_validation(record: dict) -> bool:
    """May this record be used as a LABEL to validate a satisfaction model?"""
    return (not validate(record) and record["rating_source"] in ("customer_submitted", "annotator")
            and "model_validation" in record["consent"]["scope"]
            and not record["data_quality"]["is_duplicate"] and not record["data_quality"]["is_test_or_synthetic"])


def main(argv=None):
    argv = argv or sys.argv[1:]
    bad = 0
    for n, line in enumerate(open(argv[0], encoding="utf-8"), 1):
        if line.strip():
            errs = validate(json.loads(line))
            if errs:
                bad += 1
                print(f"line {n}: " + "; ".join(errs))
    print(f"{bad} invalid record(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
