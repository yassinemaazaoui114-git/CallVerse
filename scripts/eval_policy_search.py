"""Evaluate policy search ONCE on the held-out questions (final evaluation, never for tuning).

Usage (from the repo root):
    python -m scripts.eval_policy_search                       # tests/data/policy_search_questions.json
    python -m scripts.eval_policy_search path/to/questions.json

File format: {"questions": [{"id", "text", "expected"}]}; expected = one rule id or a list of
acceptable rule ids. Counts: top 1 = the best rule is expected; top 3 = an expected rule is in the 3 best.
"""

import json
import sys
from pathlib import Path

from callverse import trace
from callverse.kb.search import search_policy

DEFAULT_PATH = Path("tests/data/policy_search_questions.json")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    questions = json.loads(path.read_text(encoding="utf-8"))["questions"]
    trace_path = trace.start_run()

    top1 = top3 = 0
    for q in questions:
        expected = [q["expected"]] if isinstance(q["expected"], str) else list(q["expected"])
        found = [r["id"] for r in search_policy(q["text"], k=3)]
        hit1, hit3 = found[0] in expected, any(f in expected for f in found)
        top1 += hit1
        top3 += hit3
        mark = "OK " if hit1 else ("top3" if hit3 else "MISS")
        print(f"{mark:4s} {q['id']}: expected {expected}  found {found}  | {q['text']}")

    n = len(questions)
    print(f"\nTop 1: {top1}/{n}   Top 3: {top3}/{n}")
    print(f"Trace file : {trace_path}")


if __name__ == "__main__":
    main()
