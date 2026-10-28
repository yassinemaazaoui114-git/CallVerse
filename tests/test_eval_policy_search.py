"""The policy-search evaluation script counts top-1 / top-2 / top-3 and skips questions with no rule.

Offline: search_policy is replaced by a fake that returns fixed rules, so no embedding model is loaded.
"""

import json
import sys

from scripts import eval_policy_search as ev


def test_counts_top1_top2_top3_and_skips_empty_expected(tmp_path, monkeypatch, capsys):
    assert ev.grade(["A"], ["A", "B", "C"]) == "OK"
    assert ev.grade(["B"], ["A", "B", "C"]) == "top2"
    assert ev.grade(["C"], ["A", "B", "C"]) == "top3"
    assert ev.grade(["D"], ["A", "B", "C"]) == "MISS"

    questions = {"questions": [
        {"id": "q1", "text": "x", "expected": "A"},          # OK
        {"id": "q2", "text": "x", "expected": ["B", "Z"]},   # top 2
        {"id": "q3", "text": "x", "expected": ["C"]},        # top 3
        {"id": "q4", "text": "x", "expected": ["D"]},        # MISS
        {"id": "q5", "text": "x", "expected": []},           # no rule: not scored
    ]}
    path = tmp_path / "questions.json"
    path.write_text(json.dumps(questions), encoding="utf-8")

    fake = [{"id": i, "score": s} for i, s in (("A", 0.9), ("B", 0.8), ("C", 0.7))]
    monkeypatch.setattr(ev, "search_policy", lambda text, k=3: fake)
    monkeypatch.setattr(ev.trace, "start_run", lambda: tmp_path / "run.jsonl")
    monkeypatch.setattr(sys, "argv", ["eval_policy_search", str(path)])

    ev.main()
    out = capsys.readouterr().out
    assert "Top 1: 1/4   Top 2: 2/4   Top 3: 3/4   (not scored: 1)" in out
    assert "not scored q5" in out
    assert "gap 0.100" in out
