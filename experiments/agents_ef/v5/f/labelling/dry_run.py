"""F8 — DRY RUN of the labelling pipeline on the SCRIPTED M7 corpus. *** SCRIPTED — NOT FOR METRICS ***

    python -m v5.f.labelling.dry_run          -> v5/f/labelling/dryrun_SCRIPTED_NOT_FOR_METRICS/

Purpose: prove that sampling -> sheets -> import -> agreement -> adjudication queue -> evaluation runs end to end
on the real trace format. The conversations are scripted (fake agents) and the "ratings" are PSEUDO-RANDOM
integers drawn by numpy (seeded) to fill the sheets — they are NOT human, NOT model and NOT LLM ratings, carry no
information, and no number computed from them may be reported as a result. The card is stamped and marked
synthetic, so the F->E gate rejects it.
"""

import csv
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
from v4.f.m7.conversations_v4 import load_conversations_v4  # noqa: E402
from v4.f.m7.satisfaction_v4 import load_scorer_v4, score_with_validity  # noqa: E402
from v5.f.common import FV3  # noqa: E402
from v5.f.labelling import import_eval, sampling  # noqa: E402

M7C = Path("/tmp/claude-0/-home-user/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/m7_corpus")
OUT = HERE / "dryrun_SCRIPTED_NOT_FOR_METRICS"


def main():
    OUT.mkdir(exist_ok=True)
    (OUT / "README_SCRIPTED.txt").write_text(
        "SCRIPTED — NOT FOR METRICS. Scripted M7 conversations + pseudo-random fill-in ratings (numpy, seed 0).\n"
        "This folder only shows that the labelling pipeline runs. No number here is a result.\n")
    traces = [str(M7C / "dev" / "traces"), str(M7C / "test" / "traces")]
    sampling.main(["--traces", *traces, "--out", str(OUT / "plan"), "--n", "120", "--pilot", "10", "--dev", "30",
                   "--corpus-kind", "SCRIPTED"])
    plan = json.loads((OUT / "plan" / "plan.json").read_text())
    rng = np.random.default_rng(0)
    sheets = []
    for ann in ("ANN-1", "ANN-2", "ANN-3"):
        src = OUT / "plan" / f"sheet_{ann}.csv"
        rows = list(csv.DictReader(open(src, encoding="utf-8")))
        for r in rows:
            r["rating_1to5"] = str(int(rng.choice([1, 2, 3, 4, 5], p=[.08, .15, .37, .3, .1])))
            r["confidence_low_med_high"] = "med"
        dst = OUT / f"filled_{ann}_PSEUDORANDOM.csv"
        with open(dst, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=sampling.SHEET_COLS)
            w.writeheader()
            w.writerows(rows)
        sheets.append(str(dst))
    # predictions: the v4 default scorer with validity (French withheld), as M7 does
    scorer = load_scorer_v4(f"tfidf:{FV3 / 'ckpt' / 'tfidf_ridge_tail256'}")
    convs = [c for t in traces for c in load_conversations_v4(t)]
    want = {r["conversation_id"] for r in plan["items"]}
    preds = score_with_validity([c for c in convs if c["conversation_id"] in want], scorer)
    with open(OUT / "predictions.jsonl", "w", encoding="utf-8") as f:
        for p in preds:
            f.write(json.dumps({"conversation_id": p["conversation_id"],
                                "predicted_satisfaction": p["predicted_satisfaction"],
                                "satisfaction_validity": {"model_id": p["model_id"], "validity": p["validity"]}}) + "\n")
    # first import -> adjudication queue; fill it (pseudo-random median of the ratings) -> second import
    import_eval.main(["--plan", str(OUT / "plan"), "--sheets", *sheets, "--predictions", str(OUT / "predictions.jsonl"),
                      "--out", str(OUT / "eval"), "--allow-scripted"])
    q = list(csv.DictReader(open(OUT / "eval" / "adjudication_queue.csv", encoding="utf-8")))
    for r in q:
        r["adjudicated_rating_1to5"] = str(int(np.median([int(x) for x in r["ratings"].split()])))
        r["adjudicator_id"], r["reason"] = "ADJ-DRYRUN", "dry run: median filled automatically (NOT a human decision)"
    with open(OUT / "adjudication_filled_PSEUDO.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["conversation_id", "ratings", "adjudicated_rating_1to5", "adjudicator_id",
                                          "reason"])
        w.writeheader()
        w.writerows(q)
    import_eval.main(["--plan", str(OUT / "plan"), "--sheets", *sheets, "--adjudication",
                      str(OUT / "adjudication_filled_PSEUDO.csv"), "--predictions", str(OUT / "predictions.jsonl"),
                      "--out", str(OUT / "eval"), "--allow-scripted"])


if __name__ == "__main__":
    main()
