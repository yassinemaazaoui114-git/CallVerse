"""M7 responsibility 4: the owner's quality report, built from closed conversations (runs responsibilities 1-5).

    python -m v3.m7.report --traces <folder of trace .jsonl> --out <folder> [--scorer f:<ckpt>]
                           [--card-result v3/f/results/uss/<model>.json --card-data <test.jsonl>]
                           [--ground-truth <ground_truth.json>]

Writes, in --out:
  quality_reviews.jsonl   one review per closed conversation (grade, flags, evidence with trace refs)
  rule_flags.json         static + usage audit of rules and knowledge
  e_feedback.jsonl        per-conversation satisfaction for Agent E, marked reward / kpi_only by the gate
  e_feedback_steps.json   the same, summed per 5-minute step and route (EnvV3 units)
  owner_report.json/.md   the report for the owner
  detection_eval.json     only with --ground-truth: reviewer vs planted defects (development check)
F only reads and reports. It never changes a rule, a conversation, the database or Agent E.
"""

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))          # experiments/agents_ef
from v3.m7 import feedback_e, quality, rule_audit, satisfaction  # noqa: E402
from v3.m7.conversations import load_conversations  # noqa: E402

# Planted defect -> the reviewer flag code that should catch it (development check only).
EXPECTED = {"agent_wrong_amount": "sent_back", "agent_claim_contradicts_data": "claim_contradicts_data",
            "agent_cites_missing_rule": "cited_missing_rule", "rule_not_searched": "rule_not_searched",
            "user_not_confirmed": None, "agent_answered_without_tools": "agent_answered_without_tools",
            "pipeline_error": "pipeline_error"}


def card_from_f(result_path: Path, data_path: Path, label_type: str, domain: str, n_boot: int = 2000) -> dict:
    """Validation card from Agent F's measured test predictions (best seed by VAL) and the test labels."""
    from scipy.stats import spearmanr
    res = json.loads(result_path.read_text())
    run = next(r for r in res["runs"] if r.get("seed", res.get("best_seed_by_val")) == res.get("best_seed_by_val")) \
        if res.get("best_seed_by_val") is not None else res["runs"][0]
    truth, lang = {}, {}
    for line in open(data_path, encoding="utf-8"):
        d = json.loads(line)
        truth[d["id"]], lang[d["id"]] = d["rating"], d.get("lang")
    y = np.array([truth[i] for i in res["test_ids"]])
    p = np.array(run["test_pred"], float)
    # Mean baseline on the SAME test items: predict the TRAIN mean of the same language(s).
    langs = {lang[i] for i in res["test_ids"]}
    train = [json.loads(x) for x in open(data_path.parent / "train.jsonl", encoding="utf-8")]
    train_mean = float(np.mean([d["rating"] for d in train if d.get("lang") in langs]))
    rng = np.random.default_rng(0)
    boots = []
    for _ in range(n_boot):
        k = rng.integers(0, len(y), len(y))
        boots.append(spearmanr(y[k], p[k]).statistic)
    return {"model": f"{res['model']} (seed {run.get('seed')})", "label_type": label_type, "domain": domain,
            "test_n": int(len(y)), "mae": round(float(np.abs(p - y).mean()), 4),
            "mae_mean_baseline": round(float(np.abs(train_mean - y).mean()), 4),
            "spearman": round(float(spearmanr(y, p).statistic), 4),
            "spearman_ci_low": round(float(np.nanpercentile(boots, 2.5)), 4),
            "spearman_ci_high": round(float(np.nanpercentile(boots, 97.5)), 4),
            "source": str(result_path.name), "checkpoint": run.get("checkpoint")}


NEEDS_PROPOSAL = {"agent_wrong_amount", "agent_claim_contradicts_data", "agent_cites_missing_rule",
                  "rule_not_searched", "user_not_confirmed"}


def manifested(defect: str, conv: dict) -> bool:
    """A planted behaviour only becomes a defect if the agent got as far as proposing (an order already refunded
    by an earlier conversation gets no proposal). Decided from whether a proposal was attempted, not from the
    defect's own signal."""
    if defect in NEEDS_PROPOSAL:
        return bool(conv["proposals"] or conv["proposal_refusals"])
    return True


def detection_eval(reviews: list[dict], truth: dict, convs: list[dict]) -> dict:
    """Recall per planted defect and false-flag rate on clean conversations, for the reviewer's own check."""
    by_id = {r["conversation_id"]: r for r in reviews}
    conv_by_id = {c["conversation_id"]: c for c in convs}
    not_manifested = Counter()
    per, clean_flags = {}, Counter()
    n_clean = 0
    for t in truth["conversations"]:
        r = by_id.get(t["conversation_id"])
        if r is None:
            continue
        codes = {f["code"] for f in r["flags"]}
        d = t["planted_defect"]
        if d is None:
            n_clean += 1
            for c in codes - {"slm_fallback_template", "reply_language_mismatch", "escalated"}:
                clean_flags[c] += 1
            continue
        if not manifested(d, conv_by_id[t["conversation_id"]]):
            not_manifested[d] += 1
            continue
        exp = EXPECTED.get(d)
        s = per.setdefault(d, {"n": 0, "caught": 0, "expected_flag": exp})
        s["n"] += 1
        if exp is None:                                   # no defect in the reply: check outcome instead
            s["caught"] += int(r["outcome"] == "ask_user")
            s["expected_flag"] = "outcome ask_user"
        else:
            s["caught"] += int(exp in codes)
    for s in per.values():
        s["recall"] = round(s["caught"] / s["n"], 3)
    return {"per_defect": per, "planted_not_manifested": dict(not_manifested), "n_clean": n_clean,
            "flags_on_clean": dict(clean_flags),
            "note": "SCRIPTED corpus: defects are visible in the trace by design; this checks the wiring of the "
                    "checks, it is not an estimate of real-world performance"}


def write_md(rep: dict, path: Path):
    k = rep["kpis"]
    sat = rep["satisfaction"]
    L = [f"# Quality report for the owner — {rep['period']['from']} to {rep['period']['to']}", "",
         f"Prepared by Agent F (M7). F only reports; nothing was changed. Corpus: {rep['corpus']}.", "",
         "## 1. Conversations", "",
         "| Item | Value |", "|---|---|",
         f"| Closed conversations | {k['n']} |",
         f"| Resolved | {k['resolution'].get('resolved', 0)} ({k['resolved_pct']}%) |",
         f"| Waiting on the client / finance | {k['resolution'].get('waiting_on_client', 0)} / "
         f"{k['resolution'].get('waiting_on_finance', 0)} |",
         f"| Escalated to a human | {k['resolution'].get('escalated', 0)} |",
         f"| Grade fail / review / ok | {k['grades'].get('fail', 0)} / {k['grades'].get('review', 0)} / "
         f"{k['grades'].get('ok', 0) + k['grades'].get('ok_minor', 0)} |",
         f"| Reply from the SLM / template | {k['reply_source'].get('slm', 0) + k['reply_source'].get('slm_retry', 0)} / "
         f"{k['reply_source'].get('template', 0)} |", "",
         "## 2. Satisfaction (PREDICTED by a model, not reported by clients)", ""]
    if sat["n_scored"]:
        L += [f"- Model: {sat['model']}. Scored {sat['n_scored']} / {k['n']} conversations.",
              f"- Mean predicted score {sat['mean']:.2f} (1-5), spread (SD) {sat['std']:.2f}; share below 2.5: "
              f"{sat['share_low']:.1%}.",
              f"- By quality grade: " + ", ".join(f"{a} {b:.2f}" for a, b in sat["by_grade"].items()),
              f"- By resolution: " + ", ".join(f"{a} {b:.2f}" for a, b in sat["by_resolution"].items()),
              f"- Validation of the model: {sat['card_text']}", ""]
    else:
        L += ["- Not scored: no satisfaction model was given to this run.", ""]
    L += ["## 3. Flags in conversations (deterministic checks, evidence in quality_reviews.jsonl)", "",
          "| Flag | Severity | Count |", "|---|---|---|"]
    for code, (sev, n) in sorted(rep["flag_counts"].items(), key=lambda x: (-quality.SEVERITY_ORDER[x[1][0]], -x[1][1])):
        L.append(f"| {code} | {sev} | {n} |")
    L += ["", "Worst conversations (first 10):", ""]
    for w in rep["worst"][:10]:
        L.append(f"- `{w['conversation_id']}` order {w['order_id']}, {w['outcome']}: "
                 + "; ".join(f"{f['code']} — {f['what']}" for f in w["flags"] if f["severity"] != "low"))
    L += ["", "## 4. Rules and knowledge that may be outdated", "",
          "| Kind | Rule | Severity | What | Owner decision |", "|---|---|---|---|---|"]
    for f in rep["rule_flags"]:
        if f["kind"] == "unreviewed":
            continue
        L.append(f"| {f['kind']} | {f['rule_id'] or '—'} | {f['severity']} | {f['what']} | {f['owner_action']} |")
    n_unrev = sum(1 for f in rep["rule_flags"] if f["kind"] == "unreviewed")
    if n_unrev:
        L.append(f"| unreviewed | {n_unrev} rules | low | AI-written wording, no review/version/date | "
                 "review and add version + last_reviewed |")
    g = rep["e_feedback"]["gate"]
    L += ["", "## 5. Feedback to Agent E", "",
          f"- Satisfaction enters E's reward: **{'YES' if g['usable_for_reward'] else 'NO (KPI only)'}**.",
          "- Gate checks: " + "; ".join(f"{c['check']} {'pass' if c['pass'] else 'FAIL'} ({c['value']})"
                                        for c in g["checks"]),
          "- E's safety rules (mask, budget, fallback cap, no fallback for HIGH) never depend on this score.", ""]
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--scorer", default="none")
    ap.add_argument("--card-result")
    ap.add_argument("--card-data")
    ap.add_argument("--card-label-type", default="human_annotation")
    ap.add_argument("--card-domain", default="task_oriented_dialogue")
    ap.add_argument("--ground-truth")
    ap.add_argument("--corpus-label", default="")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()

    convs = load_conversations(a.traces)
    reviews = [quality.review(c) for c in convs]
    t_review = time.perf_counter() - t0

    t1 = time.perf_counter()
    scorer = satisfaction.load_scorer(a.scorer)
    scores = satisfaction.score_all(convs, scorer)
    t_score = time.perf_counter() - t1

    card = card_from_f(Path(a.card_result), Path(a.card_data), a.card_label_type, a.card_domain) \
        if a.card_result and a.card_data else None
    ends = {c["conversation_id"]: c.get("end") for c in convs}
    fb, g = feedback_e.per_conversation(reviews, scores, ends, card)
    steps = feedback_e.aggregate(fb)
    flags = rule_audit.static_audit() + rule_audit.usage_audit(reviews, convs, scores)

    with open(out / "quality_reviews.jsonl", "w", encoding="utf-8") as f:
        for r in reviews:
            f.write(json.dumps({**r, "predicted_satisfaction": scores.get(r["conversation_id"])}, ensure_ascii=False,
                               default=str) + "\n")
    with open(out / "e_feedback.jsonl", "w") as f:
        for r in fb:
            f.write(json.dumps(r) + "\n")
    (out / "e_feedback_steps.json").write_text(json.dumps(steps, indent=1))
    (out / "rule_flags.json").write_text(json.dumps(flags, indent=1, default=str))

    fc = {}
    for r in reviews:
        for fl in r["flags"]:
            sev, n = fc.get(fl["code"], (fl["severity"], 0))
            fc[fl["code"]] = (max(sev, fl["severity"], key=quality.SEVERITY_ORDER.get), n + 1)
    res = Counter(r["resolution"] for r in reviews)
    sv = np.array([scores[r["conversation_id"]] for r in reviews if r["conversation_id"] in scores])
    by_res = {}
    for r in reviews:
        if r["conversation_id"] in scores:
            by_res.setdefault(r["resolution"], []).append(scores[r["conversation_id"]])
    card_text = (f"{card['model']} on {card['label_type']} ({card['domain']}), test n={card['test_n']}: "
                 f"MAE {card['mae']} vs mean baseline {card['mae_mean_baseline']}, Spearman {card['spearman']} "
                 f"[95% CI {card['spearman_ci_low']}, {card['spearman_ci_high']}]") if card else "no validation card"
    rep = {"created": time.strftime("%Y-%m-%dT%H:%M:%S"), "corpus": a.corpus_label or a.traces,
           "period": {"from": min((c["start"] for c in convs), default=None),
                      "to": max((c.get("end") or "" for c in convs), default=None)},
           "kpis": {"n": len(reviews), "resolution": dict(res),
                    "resolved_pct": round(100 * res.get("resolved", 0) / max(1, len(reviews)), 1),
                    "grades": dict(Counter(r["grade"] for r in reviews)),
                    "reply_source": dict(Counter(r["reply_source"] for r in reviews)),
                    "outcomes": dict(Counter(r["outcome"] for r in reviews)),
                    "median_seconds": float(np.median([r["seconds"] for r in reviews if r["seconds"] is not None]))
                    if reviews else None},
           "satisfaction": {"model": a.scorer, "n_scored": int(len(sv)),
                            "mean": float(sv.mean()) if len(sv) else None,
                            "share_low": float((sv < 2.5).mean()) if len(sv) else None,
                            "std": float(sv.std()) if len(sv) else None,
                            "by_grade": {g: float(np.mean([scores[r["conversation_id"]] for r in reviews
                                                           if r["grade"] == g and r["conversation_id"] in scores]))
                                         for g in sorted({r["grade"] for r in reviews})} if len(sv) else {},
                            "by_resolution": {k: float(np.mean(v)) for k, v in sorted(by_res.items())},
                            "card": card, "card_text": card_text},
           "flag_counts": fc,
           "worst": sorted([r for r in reviews if r["grade"] in ("fail", "review")],
                           key=lambda r: (r["grade"] != "fail", r["conversation_id"]))[:25],
           "rule_flags": flags,
           "e_feedback": {"gate": g, "n_records": len(fb), "n_steps": len(steps)},
           "timings_s": {"parse_and_review": round(t_review, 3), "satisfaction_scoring": round(t_score, 3),
                         "per_conversation_review_ms": round(1000 * t_review / max(1, len(reviews)), 3)}}
    (out / "owner_report.json").write_text(json.dumps(rep, indent=1, default=str))
    write_md(rep, out / "owner_report.md")
    if a.ground_truth:
        ev = detection_eval(reviews, json.loads(Path(a.ground_truth).read_text()), convs)
        (out / "detection_eval.json").write_text(json.dumps(ev, indent=1))
        print(json.dumps(ev["per_defect"]), ev["flags_on_clean"])
    print(f"{len(reviews)} conversations -> {out}; gate reward={g['usable_for_reward']}; timings {rep['timings_s']}")


if __name__ == "__main__":
    main()
