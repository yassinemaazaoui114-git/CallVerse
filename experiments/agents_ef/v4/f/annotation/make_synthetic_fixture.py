"""SYNTHETIC FIXTURE — fake labels for testing eval_labels.py only. NOT data, NOT results.

    python -m v4.f.annotation.make_synthetic_fixture --out v4/f/annotation/fixture_SYNTHETIC

Writes labels.jsonl (3 fake annotators per conversation), predictions.jsonl and split.json for 60 fake conversation
ids "SYN-000".."SYN-059". Every record has data_quality.is_test_or_synthetic = true, so the real pipeline drops it
unless --allow-synthetic is given, and the card it produces is labelled "synthetic_fixture" (it can never open the
F->E gate). The "true" satisfaction is drawn at random; the annotators and the "model" are that value plus noise.
"""

import argparse
import json
from pathlib import Path

import numpy as np


def make(n=60, seed=7, fr_share=0.2):
    rng = np.random.default_rng(seed)
    true = rng.uniform(1.5, 4.8, n)
    labels, preds = [], []
    for i in range(n):
        cid = f"SYN-{i:03d}"
        lang = "fr" if i < int(fr_share * n) else "en"
        for a in range(3):
            labels.append({"schema_version": "0.1", "record_id": f"{cid}-a{a}", "conversation_id": cid,
                           "ticket_id": None, "order_id": None, "rating_source": "annotator",
                           "rating": int(np.clip(np.rint(true[i] + rng.normal(0, 0.6)), 1, 5)),
                           "predicted_score": None, "prediction": None, "annotator_id": f"ANN-{a}",
                           "feedback_text": None, "submitted_at": "2026-10-26T10:00:00",
                           "conversation_closed_at": "2026-10-09T09:00:00", "channel": "annotation_tool",
                           "language": lang,
                           "consent": {"given": True, "scope": ["quality_reporting", "model_validation"]},
                           "pii_redaction": {"status": "redacted", "method": "fixture", "checked_by": "fixture"},
                           "data_quality": {"is_duplicate": False, "is_test_or_synthetic": True}})
        withheld = lang == "fr"                                   # as M7 v4 does: French gets no score
        preds.append({"conversation_id": cid, "predicted_satisfaction": None if withheld else
                      round(float(np.clip(true[i] * 0.5 + 1.6 + rng.normal(0, 0.3), 1, 5)), 3),
                      "satisfaction_validity": {"model_id": "synthetic_model", "validity":
                                                "withheld_language_not_validated" if withheld else
                                                "indicative_out_of_domain"}})
    ids = [f"SYN-{i:03d}" for i in range(n)]
    order = rng.permutation(n)
    split = {"dev": [ids[j] for j in order[: n // 3]], "test": [ids[j] for j in order[n // 3:]],
             "note": "SYNTHETIC FIXTURE split"}
    return labels, preds, split


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    labels, preds, split = make()
    (out / "labels.jsonl").write_text("".join(json.dumps(x) + "\n" for x in labels))
    (out / "predictions.jsonl").write_text("".join(json.dumps(x) + "\n" for x in preds))
    (out / "split.json").write_text(json.dumps(split, indent=1))
    (out / "README_SYNTHETIC.txt").write_text("SYNTHETIC FIXTURE for tests of eval_labels.py. Not real labels. "
                                              "Do not report any number computed from these files.\n")
    print("wrote", out)


if __name__ == "__main__":
    main()
