"""Checks of the vision dataset manifest and the vision helper code (benchmarks/vision_qlora).

No photo download and no model: these tests read manifest.jsonl and run the pure-Python parts
(labels, split, JSON parsing, metrics). The photos themselves are checked by build_dataset.py (sha256).
"""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent / "benchmarks" / "vision_qlora"
sys.path.insert(0, str(HERE))

import build_dataset as B  # noqa: E402
import cv_vision_lib as L  # noqa: E402

from callverse.config import load_config  # noqa: E402


@pytest.fixture(scope="module")
def rows():
    return [json.loads(line) for line in (HERE / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if line]


def test_manifest_has_150_real_photos_with_unique_ids_and_hashes(rows):
    assert len(rows) == 150
    assert len({r["id"] for r in rows}) == 150
    assert len({r["sha256_source"] for r in rows}) == 150      # no exact duplicate source file
    assert all(r["source_revision"] for r in rows)              # every source is pinned


def test_labels_are_valid(rows):
    assert B.check_labels(rows) == []
    assert {r["issue_type"] for r in rows} == set(B.ISSUE_TYPES)


def test_company_reasons_match_config_yaml(rows):
    # The vision dataset uses the SAME contact reasons as the running system (config.yaml companies:).
    companies = load_config()["companies"]
    assert B.REASONS["shopnova"] == companies["shopnova"]["reasons"]
    assert B.REASONS["atlas"] == companies["atlas"]["reasons"]
    used = {(r["domain"], r["company_reason"]) for r in rows if r["company_reason"]}
    assert len({reason for d, reason in used if d == "shopnova"}) == 7
    assert len({reason for d, reason in used if d == "atlas"}) == 8


def test_split_is_stratified_and_has_no_group_leak(rows):
    rows = [dict(r) for r in rows]
    have = B.group_split(rows)
    groups = {}
    for r in rows:
        groups.setdefault(r["group"], set()).add(r["split"])
    assert all(len(s) == 1 for s in groups.values())
    for cls in B.ISSUE_TYPES:            # every class is in all three splits
        assert all(have[s][cls] >= 1 for s in ("train", "val", "test")), cls
    n = {s: sum(have[s].values()) for s in have}
    assert 0.6 <= n["train"] / 150 <= 0.75


def test_target_rules(rows):
    for r in rows:
        t = B.target_for(r)
        assert set(t) == set(L.KEYS)
        if r["issue_type"] == "unclear":
            assert t["visible_damage"] is None and t["requires_review"] is True
        elif r["issue_type"] == "no_visible_issue":
            assert t["visible_damage"] is False
        else:
            assert t["visible_damage"] is True and t["requires_review"] is True
        assert L.parse_output(L.answer_text(t))[1] == "ok"


@pytest.mark.parametrize("text,why", [
    ("no json here", "no_json"),
    ('{"visible_damage": true', "no_json"),
    ('{"damaged": true}', "wrong_keys"),
    ('{"visible_damage": "yes", "object": "x", "issue_type": "unclear", "description": "d", '
     '"confidence_level": "low", "requires_review": true}', "bad_visible_damage"),
    ('{"visible_damage": true, "object": "x", "issue_type": "refund_request", "description": "d", '
     '"confidence_level": "low", "requires_review": true}', "bad_issue_type"),
])
def test_parser_rejects_invalid_model_output(text, why):
    assert L.parse_output(text) == (None, why)


def test_parser_accepts_code_fence():
    t = '```json\n{"visible_damage": false, "object": "shoe", "issue_type": "no_visible_issue", ' \
        '"description": "A shoe.", "confidence_level": "high", "requires_review": false}\n```'
    obj, why = L.parse_output(t)
    assert why == "ok" and obj["object"] == "shoe"


def test_metrics_counts_invalid_output_as_wrong():
    gold = [{"target": {"issue_type": "cracked_screen", "visible_damage": True}},
            {"target": {"issue_type": "no_visible_issue", "visible_damage": False}}]
    good = {"issue_type": "cracked_screen", "visible_damage": True}
    preds = [{"parsed": good, "raw": "", "latency_s": 1.0}, {"parsed": None, "raw": "{}", "latency_s": 2.0}]
    m = L.metrics(gold, preds, n_boot=50)
    assert m["accuracy"] == 0.5 and m["json_validity"] == 0.5
    assert m["damage_recall"] == 1.0 and m["false_alarm_rate"] == 0.0
    assert m["latency_s"]["mean"] == 1.5


def test_lenient_damage_reads_old_benchmark_format():
    assert L.lenient_damage('{"damaged": true}') is True
    assert L.lenient_damage('{"visible_damage": null}') is None
    assert L.lenient_damage("nothing") is None


def test_notebook_is_in_sync_with_source_files():
    nb = json.loads((HERE / "CallVerse_Qwen3VL_QLoRA_Training.ipynb").read_text(encoding="utf-8"))
    cells = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
    for name in ("cv_vision_lib.py", "build_dataset.py", "manifest.jsonl"):
        body = next(c for c in cells if c.startswith(f"%%writefile {name}\n")).split("\n", 1)[1]
        # the notebook cell drops the file's final newline; everything else must be identical
        assert body.rstrip("\n") == (HERE / name).read_text(encoding="utf-8").rstrip("\n"), \
            f"re-run make_notebook.py ({name} changed)"
