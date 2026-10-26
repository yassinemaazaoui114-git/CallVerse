"""F8 labelling package — step 2: import the filled rating sheets, adjudicate, evaluate Agent F on them.

    python -m v5.f.labelling.import_eval --plan <plan folder> --sheets <sheet_ANN-1.csv> ... \
        [--adjudication <adjudication.csv>] --predictions <agent_f_results.jsonl> --out <folder> [--allow-scripted]

What it does
  1. reads every annotator sheet (CSV made by sampling.py, filled by a human), checks it: rating is an integer 1-5
     or empty with a cannot_judge_reason; item / conversation ids are in the plan; one rating per annotator per item;
  2. writes the ratings as annotator records of the v4 reviews contract (v4/f/contracts/reviews.schema.json,
     rating_source = "annotator") and validates every record with v4 validate_reviews;
  3. agreement (Krippendorff alpha ordinal + interval, human leave-one-out MAE) with v4 eval_labels.agreement;
  4. ADJUDICATION QUEUE: items whose ratings spread >= 2 points, or that straddle the dissatisfied line
     (one rating <= 2 and another >= 3); written to adjudication_queue.csv for the adjudicator (rubric §5);
  5. reads the adjudication sheet (if given) into adjudicated.jsonl — a SEPARATE file with label_source
     "adjudicated_human": the v4 contract has no adjudicated kind and customer ratings must never be mixed with it;
  6. evaluation on TEST (split fixed by sampling.py): gold = mean of annotators (v4 card, the F->E gate input) AND
     gold = adjudicated label when one exists, else the mean; MAE / Spearman on the labelled sample and
     IPW-weighted with 1/inclusion_prob (the plan oversampled likely-dissatisfied conversations); recall of the
     dissatisfied class (gold <= 2.5) and per language. Conversations with no score (French withheld) are counted.
Never accepted as labels: ai_predicted records, LLM ratings, scripted/synthetic conversations (unless
--allow-scripted, which stamps every output "SCRIPTED — NOT FOR METRICS" and makes the card fail the gate).
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
from v4.f.annotation.eval_labels import agreement, evaluate  # noqa: E402
from v4.f.contracts.validate_reviews import validate  # noqa: E402


def read_sheet(path, plan_items):
    ids = {r["item_id"]: r for r in plan_items}
    rows, errors = [], []
    for n, r in enumerate(csv.DictReader(open(path, encoding="utf-8")), start=2):
        it = ids.get(r["item_id"])
        if it is None or it["conversation_id"] != r["conversation_id"]:
            errors.append(f"{path}:{n}: item/conversation not in the plan")
            continue
        v = (r.get("rating_1to5") or "").strip()
        if not v:
            if not (r.get("cannot_judge_reason") or "").strip():
                errors.append(f"{path}:{n}: empty rating without cannot_judge_reason")
            continue
        if v not in {"1", "2", "3", "4", "5"}:
            errors.append(f"{path}:{n}: rating '{v}' is not an integer 1-5")
            continue
        rows.append({**r, "rating": int(v)})
    seen = defaultdict(int)
    for r in rows:
        seen[(r["annotator_id"], r["item_id"])] += 1
    errors += [f"duplicate rating {k}" for k, c in seen.items() if c > 1]
    return rows, errors


def to_record(r, item, scripted, when):
    return {"schema_version": "0.1", "record_id": f"{r['item_id']}-{r['annotator_id']}",
            "conversation_id": r["conversation_id"], "ticket_id": None, "order_id": None,
            "rating_source": "annotator", "rating": r["rating"], "predicted_score": None, "prediction": None,
            "annotator_id": r["annotator_id"], "feedback_text": None, "submitted_at": when,
            "conversation_closed_at": None, "channel": "annotation_tool",
            "language": item["language"] if item["language"] in ("fr", "ar", "en") else "other",
            "consent": {"given": True, "scope": ["quality_reporting", "model_validation"]},
            "pii_redaction": {"status": "redacted", "method": "regex + human check (protocol §4)",
                              "checked_by": "SCRIPTED-DRY-RUN" if scripted else "redaction_checker"},
            "data_quality": {"is_duplicate": False, "is_test_or_synthetic": bool(scripted),
                             "flags": ["SCRIPTED_NOT_FOR_METRICS"] if scripted else []}}


def wmetrics(y, p, w):
    from scipy.stats import spearmanr
    y, p, w = (np.asarray(v, float) for v in (y, p, w))
    w = w / w.sum()
    return {"n": int(len(y)), "mae": round(float(np.abs(y - p).mean()), 4),
            "mae_ipw": round(float((w * np.abs(y - p)).sum()), 4),
            "spearman": round(float(spearmanr(y, p).statistic), 4) if np.std(p) > 0 and np.std(y) > 0 else None,
            "dissatisfied_n": int((y <= 2.5).sum()),
            "dissatisfied_recall_pred_lt_2.5": round(float((p[y <= 2.5] < 2.5).mean()), 4) if (y <= 2.5).any() else None,
            "gold_share_dissatisfied_ipw": round(float((w * (y <= 2.5)).sum()), 4)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--sheets", nargs="+", required=True)
    ap.add_argument("--adjudication", default=None)
    ap.add_argument("--predictions", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--allow-scripted", action="store_true")
    a = ap.parse_args(argv)
    plan = json.loads((Path(a.plan) / "plan.json").read_text())
    split = json.loads((Path(a.plan) / "split.json").read_text())
    scripted = plan["corpus_kind"] != "genuine"
    if scripted and not a.allow_scripted:
        raise SystemExit("plan is SCRIPTED: refusing (use --allow-scripted for a dry run; outputs are NOT FOR METRICS)")
    items = {r["item_id"]: r for r in plan["items"]}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows, errors = [], []
    for s in a.sheets:
        rr, ee = read_sheet(s, plan["items"])
        rows += rr
        errors += ee
    recs = [to_record(r, items[r["item_id"]], scripted, "2026-10-26T00:00:00") for r in rows]
    invalid = [(x["record_id"], validate(x)) for x in recs if validate(x)]
    with open(out / "labels_annotator.jsonl", "w", encoding="utf-8") as f:
        for x in recs:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    by_conv = defaultdict(list)
    for r in rows:
        by_conv[r["conversation_id"]].append(float(r["rating"]))
    queue = [c for c, v in by_conv.items() if len(v) >= 2 and (max(v) - min(v) >= 2 or (min(v) <= 2 and max(v) >= 3))]
    with open(out / "adjudication_queue.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["conversation_id", "ratings", "adjudicated_rating_1to5", "adjudicator_id", "reason"])
        for c in sorted(queue):
            w.writerow([c, " ".join(str(int(x)) for x in by_conv[c]), "", "", ""])
    adj = {}
    if a.adjudication:
        for r in csv.DictReader(open(a.adjudication, encoding="utf-8")):
            v = (r.get("adjudicated_rating_1to5") or "").strip()
            if v in {"1", "2", "3", "4", "5"}:
                adj[r["conversation_id"]] = {"conversation_id": r["conversation_id"], "label_source": "adjudicated_human",
                                             "rating": int(v), "adjudicator_id": r.get("adjudicator_id"),
                                             "reason": r.get("reason"), "annotator_ratings": by_conv.get(r["conversation_id"]),
                                             "is_test_or_synthetic": scripted}
    with open(out / "adjudicated.jsonl", "w", encoding="utf-8") as f:
        for v in adj.values():
            f.write(json.dumps(v, ensure_ascii=False) + "\n")
    preds = [json.loads(l) for l in open(a.predictions, encoding="utf-8") if l.strip()]
    rep, card = evaluate(recs, preds, split, allow_synthetic=scripted)            # v4: gold = annotator mean
    pred = {p["conversation_id"]: p.get("predicted_satisfaction") for p in preds}
    test = [c for c in split["test"] if c in by_conv]
    cid2item = {r["conversation_id"]: r for r in plan["items"]}
    v5 = {}
    for gname, gold in (("mean_of_annotators", {c: float(np.mean(v)) for c, v in by_conv.items()}),
                        ("adjudicated_else_mean", {c: float(adj[c]["rating"]) if c in adj else float(np.mean(v))
                                                   for c, v in by_conv.items()})):
        sc = [c for c in test if pred.get(c) is not None]
        if sc:
            v5[gname] = wmetrics([gold[c] for c in sc], [pred[c] for c in sc],
                                 [1 / cid2item[c]["inclusion_prob"] for c in sc])
            v5[gname]["by_language"] = {lg: wmetrics([gold[c] for c in sc if cid2item[c]["language"] == lg],
                                                     [pred[c] for c in sc if cid2item[c]["language"] == lg],
                                                     [1 / cid2item[c]["inclusion_prob"] for c in sc
                                                      if cid2item[c]["language"] == lg])
                                        for lg in sorted({cid2item[c]["language"] for c in sc})
                                        if sum(cid2item[c]["language"] == lg for c in sc) >= 3}
    report = {"stamp": plan["stamp"], "corpus_kind": plan["corpus_kind"], "sheet_errors": errors,
              "invalid_records": invalid, "n_ratings": len(rows), "n_conversations_rated": len(by_conv),
              "agreement_all": agreement(dict(by_conv)), "adjudication_queue_n": len(queue),
              "adjudicated_n": len(adj), "v4_eval": rep, "v5_eval_test": v5,
              "test_not_scored": sum(1 for c in test if pred.get(c) is None)}
    (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    (out / "card.json").write_text(json.dumps({**card, "stamp": plan["stamp"]}, indent=1))
    print(json.dumps({k: report[k] for k in ("stamp", "n_ratings", "adjudication_queue_n", "adjudicated_n",
                                             "test_not_scored", "sheet_errors")}, indent=1, ensure_ascii=False))
    print("gate:", rep["gate"]["e_reward_allowed"], rep["gate"]["reasons"][:3])


if __name__ == "__main__":
    main()
