"""F8 labelling package — step 1: choose WHICH closed conversations humans will label (sampling plan).

    python -m v5.f.labelling.sampling --traces <folder> [<folder> ...] --out <plan folder> \
        --n 460 --pilot 30 --dev 130 --corpus-kind genuine|SCRIPTED [--seed 7]

Why a plan file at all
  We need 300-500 labelled conversations with enough FRENCH ones (French is not validated today) and enough
  DISSATISFIED ones (the class Agent F misses most: on USS true-class-1 dialogues are over-predicted by ~1.8).
  A simple random sample of a demo channel would contain few unhappy clients. So the plan OVERSAMPLES a
  "likely dissatisfied" stratum. The stratum is chosen with M7 quality flags and the Intake sentiment, which are
  only a PRIORITISER, never a label: annotators never see the stratum, the flags or Agent F's score.
  Because some strata are oversampled, every sampled conversation carries its inclusion probability pi = n_h/N_h,
  so population numbers (e.g. "share of dissatisfied clients", MAE over all conversations) are computed with
  inverse-probability weights 1/pi; model metrics are reported both on the labelled sample and IPW-weighted.
Strata  language (en / fr / ar / other, from the client's message, v4 detector) x priority (P1 likely dissatisfied /
        P0 other). P1 = any M7 v5 flag of severity high, or escalated / sent_back / reply_language_mismatch /
        followup_promise_unbacked / reply_refund_promise_unbacked, or Intake emotion anger/sadness/fear with
        negative sentiment.
Allocation (fixed here, before any label exists)
  language quotas: fr 40%, en 40%, ar + other 20% of n (a language with too few conversations gives its rest to
  the others in proportion); inside a language, P1 gets min(N_P1, max(2 x its population share, 30%) of the quota,
  capped at 50%); the rest is P0. Within a stratum: simple random sample (seeded).
Splits  pilot (calibration only, never evaluated) / dev / test, stratified by stratum, written BEFORE any prediction.
Outputs plan.json (items with stratum, pi, split), split.json (v4 eval_labels format), sheet_<annotator>.csv
        (blank rating sheets, shuffled per annotator, no stratum / flag / score column).
"""

import argparse
import csv
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))                               # experiments/agents_ef
from v4.f.m7.conversations_v4 import dialogue_text, load_conversations_v4  # noqa: E402
from v4.f.m7.satisfaction_v4 import detect_language  # noqa: E402
from v5.f.m7.quality_v5 import review_v5  # noqa: E402

P1_CODES = {"escalated", "sent_back", "reply_language_mismatch", "followup_promise_unbacked",
            "reply_refund_promise_unbacked", "missed_entitlement", "pipeline_error", "claim_false"}
LANG_SHARE = {"fr": 0.40, "en": 0.40, "ar+other": 0.20}
SHEET_COLS = ["item_id", "conversation_id", "language", "annotator_id", "client_messages", "replies_received",
              "rating_1to5", "confidence_low_med_high", "cannot_judge_reason", "comment"]


def priority(conv, review):
    t = conv.get("ticket") or {}
    neg = (t.get("sentiment") or {}).get("label") == "negative" and \
        (t.get("emotion") or {}).get("label") in ("anger", "sadness", "fear")
    codes = {f["code"] for f in review["flags"]}
    high = any(f["severity"] == "high" for f in review["flags"])
    why = sorted(codes & P1_CODES) + (["any_high_severity_flag"] if high else []) + (["intake_negative"] if neg else [])
    return ("P1" if why else "P0"), why


def allocate(pop: dict, n: int) -> dict:
    """pop: {(lang_group, prio): N_h} -> {(lang_group, prio): n_h}."""
    groups = defaultdict(dict)
    for (g, p), N in pop.items():
        groups[g][p] = N
    quota = {g: LANG_SHARE.get(g, 0) * n for g in LANG_SHARE}
    # give the quota a language cannot fill to the others, proportionally
    for _ in range(3):
        spare = sum(max(0, quota[g] - sum(groups.get(g, {}).values())) for g in quota)
        quota = {g: min(quota[g], sum(groups.get(g, {}).values())) for g in quota}
        open_g = [g for g in quota if sum(groups.get(g, {}).values()) > quota[g]]
        tot = sum(LANG_SHARE[g] for g in open_g)
        for g in open_g:
            quota[g] += spare * LANG_SHARE[g] / tot if tot else 0
    out = {}
    for g, q in quota.items():
        N1, N0 = groups.get(g, {}).get("P1", 0), groups.get(g, {}).get("P0", 0)
        if N1 + N0 == 0:
            continue
        share1 = N1 / (N1 + N0)
        n1 = min(N1, round(min(0.5, max(2 * share1, 0.30)) * q))
        n0 = min(N0, round(q) - n1)
        n1 = min(N1, round(q) - n0)                                     # top up P1 if P0 is short
        out[(g, "P1")], out[(g, "P0")] = n1, n0
    # rounding can leave the total 1-2 off n: fix it on the largest strata that have room (P0 first)
    total_pop = sum(pop.values())
    target = min(n, total_pop)
    order = sorted(out, key=lambda h: (h[1] != "P0", -out[h]))
    while sum(out.values()) > target:
        h = next(h for h in order if out[h] > 0)
        out[h] -= 1
    while sum(out.values()) < target:
        h = next(h for h in order if out[h] < pop.get(h, 0))
        out[h] += 1
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=460)
    ap.add_argument("--pilot", type=int, default=30)
    ap.add_argument("--dev", type=int, default=130)
    ap.add_argument("--annotators", nargs="+", default=["ANN-1", "ANN-2", "ANN-3"])
    ap.add_argument("--corpus-kind", choices=["genuine", "SCRIPTED"], required=True,
                    help="SCRIPTED = dry run on the scripted M7 corpus: every output is stamped NOT FOR METRICS")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)
    convs = [c for f in a.traces for c in load_conversations_v4(f)]
    rows = []
    for c in convs:
        lg = detect_language(c.get("client_text") or "")
        p, why = priority(c, review_v5(c))
        rows.append({"conversation_id": c["conversation_id"], "file": c.get("file"), "language": lg,
                     "lang_group": lg if lg in ("en", "fr") else "ar+other", "priority": p, "priority_why": why,
                     "text": dialogue_text(c)})
    pop = Counter((r["lang_group"], r["priority"]) for r in rows)
    alloc = allocate(dict(pop), min(a.n, len(rows)))
    rng = random.Random(a.seed)
    chosen = []
    for h, k in sorted(alloc.items()):
        members = sorted([r for r in rows if (r["lang_group"], r["priority"]) == h], key=lambda r: r["conversation_id"])
        for r in rng.sample(members, k):
            chosen.append({**r, "stratum": f"{h[0]}|{h[1]}", "inclusion_prob": round(k / pop[h], 6)})
    # splits, stratified: pilot and dev take the same share of every stratum; the rest is test
    n = len(chosen)
    by_h = defaultdict(list)
    for r in chosen:
        by_h[r["stratum"]].append(r)
    for h, items in by_h.items():
        rng.shuffle(items)
        k_pi, k_dev = round(a.pilot * len(items) / n), round(a.dev * len(items) / n)
        for i, r in enumerate(items):
            r["split"] = "pilot" if i < k_pi else "dev" if i < k_pi + k_dev else "test"
    for i, r in enumerate(sorted(chosen, key=lambda r: r["conversation_id"])):
        r["item_id"] = f"I{i:04d}"
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = "SCRIPTED — NOT FOR METRICS (dry run of the labelling pipeline)" if a.corpus_kind == "SCRIPTED" else \
        "genuine tester conversations"
    plan = {"corpus_kind": a.corpus_kind, "stamp": stamp, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "seed": a.seed, "n_population": len(rows), "n_sampled": n,
            "population_by_stratum": {f"{g}|{p}": v for (g, p), v in sorted(pop.items())},
            "allocation": {f"{g}|{p}": v for (g, p), v in sorted(alloc.items())},
            "split_counts": dict(Counter(r["split"] for r in chosen)),
            "priority_is_not_a_label": "P1/P0 come from M7 flags and Intake sentiment; they only decide sampling "
                                       "rates. Annotators never see them.",
            "items": [{k: v for k, v in r.items() if k != "text"} for r in chosen]}
    (out / "plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False))
    split = {"dev": [r["conversation_id"] for r in chosen if r["split"] == "dev"],
             "test": [r["conversation_id"] for r in chosen if r["split"] == "test"],
             "pilot_not_evaluated": [r["conversation_id"] for r in chosen if r["split"] == "pilot"],
             "stamp": stamp}
    (out / "split.json").write_text(json.dumps(split, indent=1))
    for ann in a.annotators:
        items = sorted(chosen, key=lambda r: r["item_id"])
        random.Random(f"{a.seed}-{ann}").shuffle(items)                  # own order per annotator
        with open(out / f"sheet_{ann}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(SHEET_COLS)
            for r in items:
                cl = "\n".join(l.split(":", 1)[1].strip() for l in r["text"].split("\n") if l.startswith("Customer:"))
                rp = "\n".join(l.split(":", 1)[1].strip() for l in r["text"].split("\n") if l.startswith("Agent:"))
                w.writerow([r["item_id"], r["conversation_id"], r["language"], ann, cl, rp, "", "", "", ""])
    print(json.dumps({k: plan[k] for k in ("stamp", "n_population", "n_sampled", "population_by_stratum",
                                           "allocation", "split_counts")}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
