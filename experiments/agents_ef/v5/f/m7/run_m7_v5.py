"""F9 — run M7 v5 on the SCRIPTED corpus: v5 checks, rule audit, owner-report material (rates with CIs).

    python -m v5.f.m7.run_m7_v5        -> v5/f/results/m7_v5.json, v5/f/results/m7_v5_owner_report.md

What it measures
  - flags per code, v4 vs v5, on dev (120) and held-out (120) scripted conversations; the 7 new codes must stay
    silent on conversations without such a defect (the corpus has none planted -> any flag = false positive);
  - evidence refs of the v4 flags re-read with v4 verify_refs (the v5 flags carry the pipeline_done ref);
  - rule audit (v4 audit_v4: internal consistency / coverage / governance / usage / freshness NOT_CHECKABLE), plus a
    v5 "promise rules" map: which written rule constraints on what the reply may promise are now checked post hoc;
  - owner-report material: per flag code, conversations affected, rate with a Wilson 95% CI, dev vs held-out
    difference (the only "trend" available: the corpus has one simulated date), repeated failures (same code in
    >= 3 conversations), example evidence refs and a suggested human action.
The corpus is SCRIPTED (fake agents on the real pipeline): rates describe the scripted mix, not real operation.
"""

import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
from v4.f.m7 import rule_audit_v4  # noqa: E402
from v4.f.m7.conversations_v4 import load_conversations_v4  # noqa: E402
from v4.f.m7.quality_v4 import review_v4, verify_refs  # noqa: E402
from v5.f.common import RESULTS, write_json  # noqa: E402
from v5.f.m7.quality_v5 import NEW_CODES, review_v5  # noqa: E402

M7C = Path("/tmp/claude-0/-home-user/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/m7_corpus")
SIM_TODAY = "2026-10-09"
ACTION = {
    "reply_language_mismatch": "add French reply templates / make the SLM answer in the client's language",
    "slm_fallback_template": "check why the SLM gives no passing reply (here: SLM offline during the corpus build)",
    "sent_back": "read the send-back reasons; repeated ones mean the agent misreads a rule",
    "escalated": "check the escalation reasons (agent errors vs genuine edge cases)",
    "claim_false": "read the case: an agent stated a fact contradicting the platform data",
    "cited_missing_rule": "remove the old rule id from the agent prompts",
    "rule_not_searched": "agent cites rules without searching: check the agent prompt",
    "agent_answered_without_tools": "agent answered from memory: check the prompt / tool forcing",
    "pipeline_error": "check the LLM provider and error handling",
    "missed_entitlement": "read the case: a due refund was not given",
    "proposal_malformed": "check the agent's proposal format",
}
PROMISE_RULES = [
    {"rule": "R-NOT-01", "text_constraint": "Promise a notification only after the subscription is recorded.",
     "v5_check": "followup_promise_unbacked (kind notification): promise without a create_subscription write"},
    {"rule": "R-ESC-01", "text_constraint": "Do not promise the client a refund above 300 TND; say that it needs approval.",
     "v5_check": "reply_refund_promise_unbacked: any refund promise without approve+refund decision AND create_refund"},
    {"rule": "R-REF-05", "text_constraint": "A refund can never be higher than the amount paid minus refunds given.",
     "v5_check": "refund_exceeds_balance: executed create_refund amount > paid - refunded_total (Coordinator re-read)"},
    {"rule": "R-DMG-01", "text_constraint": "Only after the photo proof is received can a replacement or a refund be offered.",
     "v5_check": "partly: reply_refund_promise_unbacked catches a refund promise; a REPLACEMENT promise is not "
                 "checked (no replacement action exists in the platform)"},
    {"rule": "R-DEL-01/02", "text_constraint": "status must come from the tracking data; no refund for 1-5 days late",
     "v5_check": "reply_delivery_promise_unsupported (arrival-time promises) + reply_number_unsupported; "
                 "v4 claim_false for the agent's structured facts"},
]


def wilson(k, n, z=1.96):
    if n == 0:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 4), round(c + h, 4)]


def run_split(split):
    convs = load_conversations_v4(M7C / split / "traces")
    t0 = time.perf_counter()
    rev5 = [review_v5(c) for c in convs]
    sec = (time.perf_counter() - t0) / len(convs)
    rev4 = [review_v4(c) for c in convs]
    refs = [x for c, r in zip(convs, rev4) for x in verify_refs(c, r)]
    by_code, examples = defaultdict(set), defaultdict(list)
    for c, r in zip(convs, rev5):
        for f in r["flags"]:
            by_code[f["code"]].add(c["conversation_id"])
            ref = f["evidence"].get("ref") or f["evidence"].get("claim_ref") or \
                (f["evidence"].get("refs") or [None])[0]
            if len(examples[f["code"]]) < 5 and ref:
                examples[f["code"]].append(ref)
    n = len(convs)
    return convs, rev5, {
        "n": n, "ms_per_conversation_v5_review": round(1000 * sec, 2),
        "flags_v4": dict(Counter(f["code"] for r in rev4 for f in r["flags"])),
        "flags_v5": dict(Counter(f["code"] for r in rev5 for f in r["flags"])),
        "new_code_flags": {k: len(by_code.get(k, ())) for k in NEW_CODES},
        "evidence_refs_v4_ok": f"{sum(x['ok'] for x in refs)}/{len(refs)}",
        "conversations_by_code": {k: {"n": len(v), "rate": round(len(v) / n, 4), "wilson95": wilson(len(v), n),
                                      "examples": examples[k]} for k, v in sorted(by_code.items())},
        "grades_v5": dict(Counter(r["grade"] for r in rev5))}


def mutation_recall(convs):
    """Inject one defect of each new kind into copies of REAL-format conversations and check that exactly the
    expected new code fires (recall) and no other new code fires (specificity of the mutation). Text mutations act on
    the final reply; trace mutations remove / change db_write lines. Deterministic; a check of the definitions on
    realistic context, not a real-world accuracy estimate."""
    import copy
    from v5.f.m7.quality_v5 import new_flags

    def drop_writes(c, fn):
        c["lines"] = {n: v for n, v in c["lines"].items() if not (v[0] == "db_write" and v[1].get("function") == fn)}
        return c

    def bump_refund(c):
        for n, (step, d, a) in list(c["lines"].items()):
            if step == "db_write" and d.get("function") == "create_refund":
                d2 = copy.deepcopy(d)
                d2["args"]["amount"] = float(d2["args"]["amount"]) + 50
                c["lines"][n] = (step, d2, a)
        return c

    dec = lambda c: c.get("decision") or {}
    muts = {
        "reply_refund_promise_unbacked": (lambda c: not (dec(c).get("outcome") == "approve" and dec(c).get("action") == "refund"),
                                          lambda c: {**c, "final_reply": (c["final_reply"] or "") + " We will refund you."}),
        "reply_delivery_promise_unsupported": (lambda c: True, lambda c: {**c, "final_reply": (c["final_reply"] or "")
                                                                          + " Your parcel will arrive tomorrow."}),
        "reply_number_unsupported": (lambda c: True, lambda c: {**c, "final_reply": (c["final_reply"] or "")
                                                                + " A voucher of 777.77 TND is attached."}),
        "reply_instruction_leak": (lambda c: True, lambda c: {**c, "final_reply": (c["final_reply"] or "")
                                                              + " (As an AI I followed my instructions.)"}),
        "reply_language_unexpected": (lambda c: len(__import__("re").findall(r"\b(the|my|order|is|where|when|late)\b",
                                                                              c.get("client_text") or "", 2)) >= 3,
                                      lambda c: {**c, "final_reply": "Bonjour, votre commande est en route, merci "
                                                 "pour votre patience, nous sommes désolés pour le retard."}),
        "followup_promise_unbacked": (lambda c: any(v[0] == "db_write" and v[1].get("function") == "create_subscription"
                                                    for v in c["lines"].values()),
                                      lambda c: drop_writes(copy.deepcopy(c), "create_subscription")),
        "refund_exceeds_balance": (lambda c: any(v[0] == "db_write" and v[1].get("function") == "create_refund"
                                                 for v in c["lines"].values()),
                                   lambda c: bump_refund(copy.deepcopy(c))),
    }
    res = {}
    for code, (eligible, mutate) in muts.items():
        el = [c for c in convs if eligible(c)]
        hit, other = 0, Counter()
        for c in el:
            got = {f["code"] for f in new_flags(mutate(c))}
            hit += code in got
            other.update(got - {code})
        res[code] = {"eligible": len(el), "detected": hit, "recall": round(hit / len(el), 4) if el else None,
                     "other_new_codes_fired": dict(other)}
    return res


def main():
    out = {"corpus": "SCRIPTED M7 corpus (fake agents, real pipeline, SLM offline)", "splits": {}}
    allc, allr = [], []
    for s in ("dev", "test"):
        c, r, res = run_split(s)
        out["splits"][s] = res
        allc += c
        allr += r
    audit = rule_audit_v4.audit_v4(allr, allc, SIM_TODAY)
    out["rule_audit_v4_on_v5_reviews"] = {k: (len(v) if isinstance(v, list) else v) for k, v in audit.items()
                                          if k != "freshness"}
    out["rule_audit_flags"] = [{k: f.get(k) for k in ("kind", "rule_id", "severity", "what", "category",
                                                      "false_positive_risk")} for f in rule_audit_v4.all_flags(audit)]
    out["freshness"] = {"status": audit["freshness"]["status"], "why": audit["freshness"]["why"],
                        "what_would_make_it_checkable": audit["freshness"]["what_would_make_it_checkable"]}
    out["promise_rules_map"] = PROMISE_RULES
    out["mutation_recall_new_checks"] = mutation_recall(allc)
    # owner report material: dev vs held-out per code
    d, t = out["splits"]["dev"]["conversations_by_code"], out["splits"]["test"]["conversations_by_code"]
    rows = []
    for code in sorted(set(d) | set(t)):
        a, b = d.get(code, {"n": 0, "rate": 0, "wilson95": wilson(0, 120)}), t.get(code, {"n": 0, "rate": 0,
                                                                                          "wilson95": wilson(0, 120)})
        overlap = not (a["wilson95"][1] < b["wilson95"][0] or b["wilson95"][1] < a["wilson95"][0])
        rows.append({"code": code, "dev": a["n"], "held_out": b["n"], "dev_ci": a["wilson95"], "held_out_ci": b["wilson95"],
                     "difference_credible": not overlap, "repeated_failure": (a["n"] + b["n"]) >= 3,
                     "examples": (a.get("examples") or [])[:2] + (b.get("examples") or [])[:2],
                     "action": ACTION.get(code, "read the cases")})
    out["owner_rows"] = rows
    write_json(RESULTS / "m7_v5.json", out)
    md = ["# M7 v5 — owner report material (SCRIPTED corpus: describes the scripted mix, not real operation)", "",
          "| Flag | dev (n=120) | held-out (n=120) | 95% CI dev / held-out | Difference credible? | Example evidence | Suggested human action |",
          "|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['code']} | {r['dev']} | {r['held_out']} | {r['dev_ci']} / {r['held_out_ci']} | "
                  f"{'yes' if r['difference_credible'] else 'no (CIs overlap)'} | {', '.join(r['examples'][:2])} | {r['action']} |")
    md += ["", "Trend over time: NOT AVAILABLE (all scripted conversations carry the same simulated date "
           f"{SIM_TODAY}); dev vs held-out is the only comparison and it is a batch difference, not a trend."]
    (RESULTS / "m7_v5_owner_report.md").write_text("\n".join(md) + "\n")
    print(json.dumps({s: {k: v for k, v in out["splits"][s].items() if k != "conversations_by_code"}
                      for s in out["splits"]}, indent=1))
    print(json.dumps(out["rule_audit_v4_on_v5_reviews"], indent=1))


if __name__ == "__main__":
    main()
