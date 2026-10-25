"""F4 — run Agent F v4 on the scripted M7 corpus and measure false positives (dev = building, test = held out).

    python -m v4.f.eval_m7_v4 --corpus <m7_corpus> --split dev  --scorer tfidf:<f_v3>/ckpt/tfidf_ridge_tail256
    python -m v4.f.eval_m7_v4 --corpus <m7_corpus> --split test --scorer ...   (ONCE, after the code is frozen)

What is measured (v4/f/results/m7/<split>/eval.json):
  wiring_recall        planted defects that occurred -> caught by the expected flag. A WIRING check only: the corpus
                       agents are scripted and the defects are visible in the trace by construction.
  false_positives      flags on CLEAN conversations (no planted defect). Three codes describe real, verifiable
                       prototype behaviour and are checked against an independent fact instead of being counted:
                         slm_fallback_template   correct iff the trace's reply_source is "template"
                         reply_language_mismatch correct iff the corpus says the client wrote French (lang fr)
                         escalated               correct iff the final decision outcome is "escalate"
                       Every other flag on a clean conversation is counted as a false positive.
  extra_flags_on_planted  flags on planted conversations other than the expected one (listed for reading).
  v3_vs_v4             flag counts of V3's checks and v4's on the same conversations.
  evidence_integrity   evidence refs re-read from the trace and matched.
  language_detector    detect_language(client text) vs the corpus language.
  code_sha256          SHA256 of every v4 M7 source file at run time (the held-out run must match the frozen set).
"""

import argparse
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from v3.m7 import quality as q3  # noqa: E402
from v4.f.agent_f import AgentF, strip_private  # noqa: E402

EXPECTED = {"agent_wrong_amount": "sent_back", "agent_claim_contradicts_data": "claim_false",
            "agent_cites_missing_rule": "cited_missing_rule", "rule_not_searched": "rule_not_searched",
            "user_not_confirmed": None, "agent_answered_without_tools": "agent_answered_without_tools",
            "pipeline_error": "pipeline_error"}
NEEDS_PROPOSAL = {"agent_wrong_amount", "agent_claim_contradicts_data", "agent_cites_missing_rule",
                  "rule_not_searched", "user_not_confirmed"}
CODE_FILES = ["agent_f.py", "m7/conversations_v4.py", "m7/quality_v4.py", "m7/rule_audit_v4.py",
              "m7/satisfaction_v4.py", "m7/feedback_v4.py", "m7/report_v4.py", "tfidf_predictor.py",
              "eval_m7_v4.py"]


def code_hashes():
    return {f: hashlib.sha256((HERE / f).read_bytes()).hexdigest() for f in CODE_FILES}


def evaluate(results, truth):
    gt = {t["conversation_id"]: t for t in truth["conversations"]}
    per, not_manifested, fp, correct, extra = {}, Counter(), Counter(), Counter(), []
    n_clean = 0
    fp_examples = defaultdict(list)
    for r in results:
        t = gt.get(r["conversation_id"])
        if t is None:
            continue
        conv = r["_conv"]
        codes = [f["code"] for f in r["quality_flags"]]
        d = t["planted_defect"]
        if d is None:
            n_clean += 1
            for f in r["quality_flags"]:
                c = f["code"]
                if c == "slm_fallback_template":
                    ok = r["reply_source"] == "template"
                elif c == "reply_language_mismatch":
                    ok = t["lang"] == "fr"
                elif c == "escalated":
                    ok = r["outcome"] == "escalate"
                else:
                    ok = False
                if ok:
                    correct[c] += 1
                else:
                    fp[c] += 1
                    fp_examples[c].append({"conversation_id": r["conversation_id"], "what": f["what"],
                                           "ref": f["evidence"].get("ref") or f["evidence"].get("claim_ref")})
            continue
        if d in NEEDS_PROPOSAL and not (conv["proposals"] or conv["proposal_refusals"]):
            not_manifested[d] += 1
            continue
        exp = EXPECTED.get(d)
        s = per.setdefault(d, {"n": 0, "caught": 0, "expected_flag": exp or "outcome ask_user"})
        s["n"] += 1
        s["caught"] += int(r["outcome"] == "ask_user") if exp is None else int(exp in codes)
        others = sorted(set(codes) - {exp, "slm_fallback_template", "reply_language_mismatch"})
        if others:
            extra.append({"conversation_id": r["conversation_id"], "planted": d, "other_flags": others})
    for s in per.values():
        s["recall"] = round(s["caught"] / s["n"], 3)
    # language-mismatch oracle check also on planted conversations (false alarms / misses vs corpus language)
    lm = Counter()
    for r in results:
        t = gt.get(r["conversation_id"])
        if t:
            flagged = any(f["code"] == "reply_language_mismatch" for f in r["quality_flags"])
            lm[("flagged" if flagged else "not_flagged", t["lang"])] += 1
    return {"wiring_recall": per, "planted_not_manifested": dict(not_manifested), "n_clean": n_clean,
            "false_positives_on_clean": dict(fp), "false_positive_examples": dict(fp_examples),
            "verified_observations_on_clean": dict(correct), "extra_flags_on_planted": extra,
            "language_mismatch_vs_corpus_lang": {f"{a}|{b}": n for (a, b), n in lm.items()},
            "note": "SCRIPTED corpus: recall is a wiring check, not an estimate of real-world accuracy"}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--split", required=True, choices=["dev", "test"])
    ap.add_argument("--scorer", default="none")
    ap.add_argument("--frozen", default=str(HERE / "results/m7/frozen_code_sha256.json"))
    ap.add_argument("--post-freeze-tag", default=None,
                    help="re-check the held-out split with CHANGED code (fix found on DEV): results go to "
                         "results/m7/test_<tag>/ and record which files changed; the first held-out run is kept")
    ap.add_argument("--reason", default="", help="with --post-freeze-tag: why the code changed")
    a = ap.parse_args(argv)
    out = HERE / "results" / "m7" / (a.split if not a.post_freeze_tag else f"{a.split}_{a.post_freeze_tag}")
    out.mkdir(parents=True, exist_ok=True)
    hashes = code_hashes()
    post = None
    if a.post_freeze_tag:
        if not a.reason:
            raise SystemExit("--post-freeze-tag needs --reason")
        frozen = json.loads(Path(a.frozen).read_text())
        post = {"tag": a.post_freeze_tag, "reason": a.reason,
                "files_changed_since_freeze": [f for f in CODE_FILES if frozen.get(f) != hashes[f]],
                "first_heldout_run_kept_in": "results/m7/test/"}
    elif a.split == "test":
        fz = Path(a.frozen)
        if not fz.exists():
            raise SystemExit("freeze the code first: write results/m7/frozen_code_sha256.json after the dev run")
        frozen = json.loads(fz.read_text())
        changed = [f for f in CODE_FILES if frozen.get(f) != hashes[f]]
        if changed:
            raise SystemExit(f"code changed since freezing: {changed}")
        if (out / "eval.json").exists():
            raise SystemExit("held-out split already evaluated once; not re-running")
    t0 = time.perf_counter()
    f = AgentF.load({"scorer": a.scorer})
    t_load = time.perf_counter() - t0
    t1 = time.perf_counter()
    results = f.process_folder(Path(a.corpus) / a.split / "traces")
    t_proc = time.perf_counter() - t1
    rep = f.owner_report(results, corpus_label=f"scripted M7 corpus, {a.split} split (prototype pipeline, "
                                               "scripted agents' LLM, SLM offline)")
    truth = json.loads((Path(a.corpus) / a.split / "ground_truth.json").read_text())
    ev = evaluate(results, truth)
    v3c, v4c = Counter(), Counter()
    for r in results:
        v3c.update(fl["code"] for fl in q3.review(r["_conv"])["flags"])
        v4c.update(fl["code"] for fl in r["quality_flags"])
    gt = {t["conversation_id"]: t for t in truth["conversations"]}
    det = Counter((r["satisfaction_validity"]["language"], gt[r["conversation_id"]]["lang"]) for r in results)
    ev.update(v3_vs_v4={"v3": dict(v3c), "v4": dict(v4c)},
              evidence_integrity={k: v for k, v in rep["json"]["evidence_integrity"].items()},
              language_detector={f"detected {a_}|corpus {b}": n for (a_, b), n in det.items()},
              satisfaction_validity=rep["json"]["satisfaction"]["validity"],
              e_reward_allowed=rep["json"]["e_feedback"]["e_reward_allowed"],
              e_reward_reasons=rep["json"]["e_feedback"]["reasons"],
              rule_flag_counts={c: len(rep["json"]["rules_and_knowledge"][c]) for c in
                                ("internal_consistency", "coverage", "governance", "usage")},
              rule_flags=[{k: fl[k] for k in ("category", "kind", "rule_id", "severity", "what")}
                          for c in ("internal_consistency", "coverage", "governance", "usage")
                          for fl in rep["json"]["rules_and_knowledge"][c]],
              per_conversation_rule_warnings=rep["json"]["per_conversation_rule_warnings"],
              timings_s={"load": round(t_load, 2), "process_all": round(t_proc, 2),
                         "per_conversation_ms": round(1000 * t_proc / max(1, len(results)), 2)},
              n_conversations=len(results), scorer=a.scorer, code_sha256=hashes, post_freeze=post,
              created=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    (out / "eval.json").write_text(json.dumps(ev, indent=1, default=str))
    with open(out / "agent_f_results.jsonl", "w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(strip_private(r), ensure_ascii=False, default=str) + "\n")
    j = {k: v for k, v in rep["json"].items() if not k.startswith("_")}
    (out / "owner_report.json").write_text(json.dumps(j, indent=1, default=str))
    (out / "owner_report.md").write_text(rep["markdown"])
    (out / "e_feedback_rows.jsonl").write_text("".join(json.dumps(x) + "\n" for x in rep["json"]["_rows"]))
    print(json.dumps({k: ev[k] for k in ("wiring_recall", "false_positives_on_clean",
                                         "verified_observations_on_clean", "evidence_integrity", "v3_vs_v4",
                                         "language_detector", "satisfaction_validity", "e_reward_allowed",
                                         "timings_s")}, indent=1, default=str))


if __name__ == "__main__":
    main()
