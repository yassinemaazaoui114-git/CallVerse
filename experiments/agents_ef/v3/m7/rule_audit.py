"""M7 responsibility 3: flag rules or knowledge that may be OUTDATED, with evidence anyone can verify.

    static_audit()                          -> flags from the policy file, config, code and platform data alone
    usage_audit(reviews, convs, scores)     -> flags from how the rules behaved in closed conversations

F only REPORTS: it never edits a rule. Every flag says what was checked, the evidence (values, file:line or
trace refs) and what the owner should decide. "Outdated" cannot be proven by a model; what can be shown is that
a rule disagrees with something verifiable (its own condition, the config, the code, the data, or how it
works out in conversations). Usage flags need a minimum support (MIN_SUPPORT) so one odd case does not flag.

Kinds of flag:
  inconsistency   the rule's text and its checked condition (or the config / code) say different things
  stale_reference code, config or agents refer to a rule id that is not in the policy file
  knowledge_gap   a realistic case that no rule covers (fact grid)
  unverifiable    a condition uses a fact the Coordinator cannot read
  unreviewed      AI-written wording with no review / version / validity date
  usage_signal    rule often misapplied, never used, or linked to low predicted satisfaction
"""

import ast
import itertools
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from callverse.kb.policies import POLICIES_PATH, check_condition, load_policies  # noqa: E402

RULE_ID = re.compile(r"\bR-[A-Z]{2,4}-\d{2}\b")
NUM = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")
MIN_SUPPORT = 5            # usage flags need at least this many conversations citing the rule
CODE_DIRS = ("callverse/agents", "callverse/coordinator", "callverse/slm", "callverse/intake", "callverse/tools")
REVIEW_FIELDS = ("reviewed_by", "version", "valid_from", "last_reviewed")


def _flag(kind, rule_id, severity, what, evidence, action):
    return {"kind": kind, "rule_id": rule_id, "severity": severity, "what": what, "evidence": evidence,
            "owner_action": action}


def coordinator_fact_names() -> set[str]:
    """Fact names the Coordinator can check: the keys returned by coordinator._read_facts, plus the
    proposal fields it adds (amount, event). Read from the source code, so it follows code changes."""
    src = (ROOT / "callverse/coordinator/coordinator.py").read_text(encoding="utf-8")
    names = {"amount", "event"}
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == "_read_facts":
            for ret in ast.walk(node):
                if isinstance(ret, ast.Return) and isinstance(ret.value, ast.Dict):
                    names |= {k.value for k in ret.value.keys if isinstance(k, ast.Constant)}
    return names


def condition_names(cond: str) -> set[str]:
    return {n.id for n in ast.walk(ast.parse(cond, mode="eval")) if isinstance(n, ast.Name)}


def static_audit(policies=None) -> list[dict]:
    rules = policies or load_policies()
    by_id = {r["id"]: r for r in rules}
    flags = []
    cfg_text = (ROOT / "config.yaml").read_text(encoding="utf-8")

    for r in rules:
        cond = r.get("condition")
        # S1 numbers in the checked condition must appear in the wording the agents read (and vice versa
        # for thresholds such as "300 TND"): a mismatch means one of the two was updated and not the other.
        if cond:
            cond_nums = {float(x) for x in NUM.findall(cond)}
            text_nums = {float(x) for x in NUM.findall(r["text"])}
            missing = sorted(cond_nums - text_nums)
            if missing:
                flags.append(_flag("inconsistency", r["id"], "high",
                                   f"condition uses {missing}, the rule text never says it",
                                   {"condition": cond, "text_numbers": sorted(text_nums), "file": POLICIES_PATH.name},
                                   "align the rule text and its condition"))
            # S2 the Coordinator must be able to read every fact the condition uses.
            unknown = sorted(condition_names(cond) - coordinator_fact_names())
            if unknown:
                flags.append(_flag("unverifiable", r["id"], "high", f"condition uses facts {unknown} the "
                                   "Coordinator does not read", {"condition": cond}, "add the fact or fix the rule"))
        # S3 governance: AI-written wording without review metadata.
        if r.get("ai_generated") and not any(r.get(k) for k in REVIEW_FIELDS):
            flags.append(_flag("unreviewed", r["id"], "low", "AI-written wording with no review, version or "
                               "validity date", {"ai_generated": True, "missing_fields": list(REVIEW_FIELDS)},
                               "review the wording; add version and last_reviewed"))

    # S4 rule ids used in code and config must exist in the policy file.
    refs = defaultdict(list)
    for d in CODE_DIRS:
        for p in sorted((ROOT / d).rglob("*.py")):
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                for rid in RULE_ID.findall(line):
                    refs[rid].append(f"{p.relative_to(ROOT)}:{n}")
    for n, line in enumerate(cfg_text.splitlines(), 1):
        for rid in RULE_ID.findall(line):
            refs[rid].append(f"config.yaml:{n}")
    for rid, where in sorted(refs.items()):
        if rid not in by_id:
            flags.append(_flag("stale_reference", rid, "high", f"{rid} is used in code/config but is not in the "
                               "policy file", {"refs": where[:10], "n_refs": len(where)},
                               "restore the rule or update the code/config"))

    # S5 fact grid: realistic order situations no rule covers (only the conditional rules count).
    delivery_facts = {"days_late", "delivered", "days_since_delivery"}
    conds = {r["id"]: r["condition"] for r in rules
             if r.get("condition") and condition_names(r["condition"]) <= delivery_facts}
    gaps = defaultdict(list)
    for days_late, delivered, since in itertools.product(range(0, 31), (False, True), (None, 0, 7, 14, 15, 30, 60)):
        if delivered == (since is None):
            continue
        facts = {"days_late": days_late, "delivered": delivered, "days_since_delivery": since}
        hold = []
        for rid, cond in conds.items():
            try:
                if check_condition(cond, facts):
                    hold.append(rid)
            except ValueError:
                pass
        if not hold:
            key = ("delivered" if delivered else "not delivered") + (", late" if days_late else ", on time")
            gaps[key].append(facts)
    for key, cases in gaps.items():
        if key == "not delivered, on time":
            continue                                   # covered by R-DEL-01 (no condition: nothing is owed)
        flags.append(_flag("knowledge_gap", None, "medium" if "late" in key else "low",
                           f"no conditional rule covers: {key}",
                           {"n_cases": len(cases), "examples": cases[:3], "rules_checked": sorted(conds)},
                           "decide what clients in this situation are owed and write it as a rule"))
    return flags


def _boot_ci(a, b, n=2000, seed=0):
    rng = np.random.default_rng(seed)
    d = [rng.choice(a, len(a)).mean() - rng.choice(b, len(b)).mean() for _ in range(n)]
    return float(np.mean(a) - np.mean(b)), float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


def usage_audit(reviews: list[dict], convs: list[dict], scores: dict | None = None) -> list[dict]:
    """reviews: quality.review() outputs; convs: the parsed conversations; scores: {conversation_id: score}."""
    known = {r["id"] for r in load_policies()}
    flags = []

    # U1 rule ids the agents cite that are not in the policy file (the agents' knowledge is out of date).
    missing = defaultdict(list)
    for rv in reviews:
        for f in rv["flags"]:
            if f["code"] == "cited_missing_rule":
                missing[f["evidence"]["rule_id"]].append(f"{rv['conversation_id']} ({f['evidence']['ref']})")
    for rid, where in missing.items():
        flags.append(_flag("stale_reference", rid, "high" if len(where) >= MIN_SUPPORT else "medium",
                           f"agents cited {rid} {len(where)} time(s); it is not in the policy file",
                           {"conversations": where[:10], "n": len(where)},
                           "check the agents' prompts / knowledge for an old rule id"))

    # U2 per cited rule: how often its condition was false or the proposal sent back.
    cited = defaultdict(lambda: {"n": 0, "cond_fail": [], "send_back": [], "escalate": []})
    for c in convs:
        for chk in c["checks"]:
            rid = chk.get("rule_id")
            if chk.get("check") == "rule_condition" and rid in known:
                s = cited[rid]
                s["n"] += 1
                if chk.get("result") == "fail":
                    s["cond_fail"].append(f"{c['conversation_id']} ({chk['ref']})")
    for rid, s in sorted(cited.items()):
        rate = len(s["cond_fail"]) / s["n"]
        if s["n"] >= MIN_SUPPORT and rate >= 0.3:
            flags.append(_flag("usage_signal", rid, "medium", f"condition false in {len(s['cond_fail'])}/{s['n']} "
                               "checks: agents often apply it where it does not hold", {"examples": s["cond_fail"][:5],
                               "rate": round(rate, 3)}, "check whether the wording still matches how cases look"))

    # U3 policy search: the rule finally used is not what search returned first (retrieval / wording drift).
    drift = defaultdict(lambda: [0, 0, []])
    for c in convs:
        dec = c.get("decision") or {}
        rid = dec.get("rule_id")
        if dec.get("outcome") != "approve" or not rid:
            continue
        searches = [e for e in c["events"] if e["step"] == "policy_search" and e.get("results")]
        if not searches:
            continue
        drift[rid][0] += 1
        top = searches[-1]["results"][0]["id"]
        if top != rid:
            drift[rid][1] += 1
            drift[rid][2].append(f"{c['conversation_id']} top={top} ({searches[-1]['ref']})")
    for rid, (n, miss, ex) in drift.items():
        if n >= MIN_SUPPORT and miss / n >= 0.3:
            flags.append(_flag("usage_signal", rid, "low", f"policy search ranked another rule first in {miss}/{n} "
                               "approved cases", {"examples": ex[:5]}, "check the rule's wording for search"))

    # U4 rules never used (cited, approved or returned by search) over the period.
    used = set(cited) | {r.get("rule_id") for r in reviews} | {chk.get("rule_id") for c in convs for chk in c["checks"]} | {
        x["id"] for c in convs for e in c["events"] if e["step"] == "policy_search" for x in e.get("results", [])}
    if len(convs) >= 50:
        for rid in sorted(known - used):
            flags.append(_flag("usage_signal", rid, "low", f"never cited or retrieved in {len(convs)} conversations",
                               {"n_conversations": len(convs)}, "check whether the rule is still needed"))

    # U5 low PREDICTED satisfaction linked to a rule (association, not cause; scores are model predictions).
    if scores:
        by_rule = defaultdict(list)
        for rv in reviews:
            s = scores.get(rv["conversation_id"])
            if s is not None:
                by_rule[rv.get("rule_id") or "none"].append(s)
        everything = [s for v in by_rule.values() for s in v]
        for rid, v in by_rule.items():
            rest = [s for r2, vv in by_rule.items() if r2 != rid for s in vv]
            if rid == "none" or len(v) < 20 or len(rest) < 20:
                continue
            diff, lo, hi = _boot_ci(np.array(v), np.array(rest))
            if hi < 0:
                flags.append(_flag("usage_signal", rid, "medium", f"predicted satisfaction {diff:+.2f} lower than "
                                   "other conversations (95% CI excludes 0)", {"n": len(v), "ci95": [round(lo, 3),
                                   round(hi, 3)], "n_all": len(everything)},
                                   "read the flagged conversations; the rule's outcome may no longer fit clients"))
    return flags


if __name__ == "__main__":
    print(json.dumps(static_audit(), indent=1))
