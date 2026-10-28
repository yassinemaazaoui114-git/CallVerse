"""Evaluate policy search ONCE on the held-out questions (final evaluation, never for tuning).

Usage (from the repo root):
    python -m scripts.eval_policy_search                       # tests/data/policy_search_questions.json
    python -m scripts.eval_policy_search path/to/questions.json

File format: {"questions": [{"id", "text", "expected"}]}; expected = one rule id or a list of
acceptable rule ids. Counts: top 1 = the best rule is expected; top 2 = an expected rule is in the 2 best
(= what the agents really see, search_policy_tool gives them 2 rules); top 3 = an expected rule is in the 3 best.
An empty expected list means no rule exists yet (e.g. cancellation): the question is printed as "not scored".
"""

import json
import sys
from pathlib import Path

from callverse import trace
from callverse.kb.search import search_policy

DEFAULT_PATH = Path("tests/data/policy_search_questions.json")


def grade(expected: list[str], found: list[str]) -> str:
    """Mark for one question: "OK" (best rule expected), "top2", "top3" or "MISS"."""
    if found[0] in expected:
        return "OK"
    if any(f in expected for f in found[:2]):
        return "top2"
    if any(f in expected for f in found[:3]):
        return "top3"
    return "MISS"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    questions = json.loads(path.read_text(encoding="utf-8"))["questions"]
    trace_path = trace.start_run()

    top1 = top2 = top3 = scored = 0
    for q in questions:
        expected = [q["expected"]] if isinstance(q["expected"], str) else list(q["expected"])
        results = search_policy(q["text"], k=3)
        found = [r["id"] for r in results]
        rules = "  ".join(f"{r['id']} {r['score']:.3f}" for r in results)
        gap = results[0]["score"] - results[1]["score"]    # small gap = the search hesitates between 2 rules
        if not expected:                                   # no rule exists for this question: not scored
            mark = "not scored"
        else:
            mark = grade(expected, found)
            scored += 1
            top1 += mark == "OK"
            top2 += mark in ("OK", "top2")
            top3 += mark != "MISS"
        print(f"{mark:10s} {q['id']}: expected {expected}  found [{rules}]  gap {gap:.3f}  | {q['text']}")

    skipped = len(questions) - scored
    print(f"\nTop 1: {top1}/{scored}   Top 2: {top2}/{scored}   Top 3: {top3}/{scored}"
          f"   (not scored: {skipped})")
    print(f"Trace file : {trace_path}")


if __name__ == "__main__":
    main()
