"""Tests for the F8 labelling package (v5/f/labelling): allocation, sheet checks, adjudication rule, scripted guard.
No real labels exist; these tests use tiny hand-made inputs only."""

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from v5.f.labelling import import_eval, sampling  # noqa: E402


def test_allocation_oversamples_p1_and_respects_population():
    pop = {("en", "P1"): 20, ("en", "P0"): 380, ("fr", "P1"): 10, ("fr", "P0"): 190, ("ar+other", "P0"): 5}
    al = sampling.allocate(pop, 100)
    assert all(al[h] <= pop.get(h, 0) for h in al)                                  # never more than exists
    assert al[("en", "P1")] / (al[("en", "P1")] + al[("en", "P0")]) > 20 / 400  # P1 oversampled
    assert sum(al.values()) == 100                                           # AR shortfall moved to EN/FR


def test_sheet_errors_detected(tmp_path):
    items = [{"item_id": "I0000", "conversation_id": "c0", "language": "en", "inclusion_prob": 0.5}]
    p = tmp_path / "s.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(sampling.SHEET_COLS)
        w.writerow(["I0000", "c0", "en", "A1", "x", "y", "7", "", "", ""])        # out of range
        w.writerow(["I0000", "c0", "en", "A2", "x", "y", "", "", "", ""])         # empty without reason
        w.writerow(["I9999", "c9", "en", "A1", "x", "y", "3", "", "", ""])        # not in plan
        w.writerow(["I0000", "c0", "en", "A3", "x", "y", "", "", "cut", ""])      # cannot judge: ok, skipped
    rows, errs = import_eval.read_sheet(p, items)
    assert rows == [] and len(errs) == 3


def test_records_are_annotator_kind_and_valid():
    from v4.f.contracts.validate_reviews import validate
    r = import_eval.to_record({"item_id": "I1", "annotator_id": "A1", "conversation_id": "c1", "rating": 2},
                              {"language": "fr"}, scripted=False, when="2026-10-26T00:00:00")
    assert r["rating_source"] == "annotator" and validate(r) == []
    s = import_eval.to_record({"item_id": "I1", "annotator_id": "A1", "conversation_id": "c1", "rating": 2},
                              {"language": "fr"}, scripted=True, when="2026-10-26T00:00:00")
    assert s["data_quality"]["is_test_or_synthetic"] is True


def test_ipw_metrics_weight_oversampled_items_less():
    m = import_eval.wmetrics([1, 3, 3, 3], [3, 3, 3, 3], [1, 4, 4, 4])
    assert m["mae"] == 0.5 and m["mae_ipw"] == pytest.approx(2 / 13, abs=1e-4)


def test_scripted_plan_refused_without_flag(tmp_path):
    (tmp_path / "plan.json").write_text(json.dumps({"corpus_kind": "SCRIPTED", "stamp": "x", "items": []}))
    (tmp_path / "split.json").write_text(json.dumps({"dev": [], "test": []}))
    (tmp_path / "p.jsonl").write_text("")
    with pytest.raises(SystemExit):
        import_eval.main(["--plan", str(tmp_path), "--sheets", str(tmp_path / "none.csv"),
                          "--predictions", str(tmp_path / "p.jsonl"), "--out", str(tmp_path / "o")])
