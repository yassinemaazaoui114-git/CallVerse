"""Agent F (M7 "Quality & Knowledge") — one callable interface over the v4 pieces. F reads and reports; it never acts.

    f = AgentF.load({"scorer": "tfidf:<f_v3>/ckpt/tfidf_ridge_tail256"})      # or a path to a .json / .yaml config
    out = f.process("<traces>/run_x.jsonl")      # a trace file (or a v4 record from m7.conversations_v4)
    rep = f.owner_report([out, ...])             # {"json": {...}, "markdown": "..."}
    f.learn_from_reviews(review_records, outs)   # fit the review calibrator on REAL reviews (contract records)

process() returns, for ONE closed conversation (a list if the trace file holds several):
  conversation_id, ticket_id, order_id, outcome, resolution, grade
  predicted_satisfaction    number or None (None when the language is not validated or no model is configured)
  satisfaction_validity     model id + SHA256, label type, language, language/domain validated, validity, reasons
  quality_flags             deterministic checks (m7/quality_v4.py), each with evidence refs "file:line"
  evidence_check            every ref re-read from the trace: n refs, n ok, the failing ones
  rule_knowledge_warnings   static rule flags for the rule(s) this conversation used + "no rule covers these
                            facts" when the order situation is in a coverage gap + cited missing rules
  e_reward_eligible         {"eligible": bool, "reasons": [...]} — False unless the V3 gate passes AND the score
                            is validated for this conversation
Config keys (all optional): scorer ("tfidf:<dir>" | "f:<dir>" | "none"), card (path to a validation card JSON,
default: the card matching the scorer in v4/f/results/), sim_today (default: the prototype's config.yaml),
score_unvalidated_languages (default False), policies (path to a policy JSON, default: the prototype's file).
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))                     # experiments/agents_ef
REPO = HERE.parents[3]

from v3.m7.rule_audit import check_condition, condition_names, load_policies, static_audit  # noqa: E402
from v4.f.m7 import feedback_v4, quality_v4, rule_audit_v4, satisfaction_v4  # noqa: E402
from v4.f.m7.conversations_v4 import load_conversations_v4, parse_trace_v4  # noqa: E402

DEFAULT_CARDS = {"tfidf_ridge_tail256": "card_tfidf_ridge_tail256.json",
                 "e5small_trim_ft_L6_frac0.5_len256": "card_e5small_trim_ft_L6_frac0.5_len256.json",
                 "tinybert_ft_en_frac0.5_len128": "card_tinybert_ft_en_frac0.5_len128.json"}
DELIVERY_FACTS = {"days_late", "delivered", "days_since_delivery"}


def _read_config(config) -> dict:
    if config is None:
        return {}
    if isinstance(config, dict):
        return dict(config)
    p = Path(config)
    if p.suffix in (".yaml", ".yml"):
        import yaml
        return yaml.safe_load(p.read_text()) or {}
    return json.loads(p.read_text())


def _sim_today() -> str:
    import yaml
    return str(yaml.safe_load((REPO / "config.yaml").read_text())["sim_today"])


class AgentF:
    def __init__(self, scorer, card, sim_today, policies, score_unvalidated_languages=False, config=None):
        self.scorer, self.card, self.sim_today = scorer, card, sim_today
        self.policies, self.score_unvalidated = policies, score_unvalidated_languages
        self.config = config or {}
        self._static = static_audit(policies)
        self.calibrator, self.calibration_report = None, None

    @classmethod
    def load(cls, config=None):
        cfg = _read_config(config)
        scorer = satisfaction_v4.load_scorer_v4(cfg.get("scorer", "none"))
        card = None
        card_path = cfg.get("card")
        if card_path is None and scorer is not None:
            name = DEFAULT_CARDS.get(scorer.meta.get("model"))
            card_path = HERE / "results" / name if name else None
        if card_path and Path(card_path).exists():
            card = json.loads(Path(card_path).read_text())
        policies = load_policies(cfg["policies"]) if cfg.get("policies") else load_policies()
        return cls(scorer, card, str(cfg.get("sim_today") or _sim_today()), policies,
                   bool(cfg.get("score_unvalidated_languages", False)), cfg)

    # ---------------- one conversation ----------------
    def _records(self, x) -> list[dict]:
        if isinstance(x, (str, Path)):
            return parse_trace_v4(Path(x))
        if isinstance(x, dict):
            return [x]
        raise TypeError("process() takes a trace file path or a conversation record")

    def _rule_warnings(self, conv: dict, review: dict) -> list[dict]:
        out = []
        used = {review.get("rule_id")} | {c.get("rule_id") for c in conv["checks"]}
        used.discard(None)
        for f in self._static:
            # global facts (knowledge_gap grid, unreviewed wording) are in the owner report, not per conversation
            if f["rule_id"] in used and f["kind"] not in ("knowledge_gap", "unreviewed"):
                out.append({"kind": f["kind"], "rule_id": f["rule_id"], "what": f["what"],
                            "severity": f["severity"], "source": "static audit"})
        for f in review["flags"]:
            if f["code"] == "cited_missing_rule":
                out.append({"kind": "stale_reference", "rule_id": f["evidence"]["rule_id"], "what": f["what"],
                            "severity": "medium", "source": "this conversation", "ref": f["evidence"]["ref"]})
        # coverage: the order's own facts, as the platform's tools returned them in this conversation
        facts = {k: v[0] for k, v in quality_v4.q3.known_facts(conv).items()}
        if DELIVERY_FACTS <= set(facts) and facts.get("delivered") is not None:
            conds = {r["id"]: r["condition"] for r in self.policies
                     if r.get("condition") and condition_names(r["condition"]) <= DELIVERY_FACTS}
            holds = []
            for rid, cond in conds.items():
                try:
                    if check_condition(cond, {k: facts[k] for k in DELIVERY_FACTS}):
                        holds.append(rid)
                except (ValueError, TypeError):
                    pass
            covered_by_default = not facts["delivered"] and not facts["days_late"]     # R-DEL-01, nothing owed
            if not holds and not covered_by_default:
                out.append({"kind": "knowledge_gap", "rule_id": None, "severity": "medium" if facts["days_late"]
                            else "low", "what": "no conditional rule covers this order's situation "
                            f"(days_late {facts['days_late']}, delivered {facts['delivered']}, days_since_delivery "
                            f"{facts['days_since_delivery']})", "source": "this conversation",
                            "rules_checked": sorted(conds)})
        return out

    def e_reward_decision(self, sat_records=None) -> dict:
        return feedback_v4.e_reward_decision(self.card, sat_records or [])

    def process(self, x):
        convs = self._records(x)
        sat = satisfaction_v4.score_with_validity(convs, self.scorer, self.card, self.score_unvalidated)
        if self.calibrator is not None:                       # learned from real reviews (learn_from_reviews)
            for s in sat:
                if s["predicted_satisfaction"] is not None:
                    s["raw_model_score"] = s["predicted_satisfaction"]
                    s["predicted_satisfaction"] = round(float(self.calibrator.apply([s["raw_model_score"]])[0]), 3)
                    s["reasons"].append(f"calibrated on {self.calibrator.report['n_reviews']} reviews (isotonic; CV MAE "
                                        f"{self.calibrator.report['cv_mae_raw']} -> "
                                        f"{self.calibrator.report['cv_mae_calibrated']})")
        decision = feedback_v4.e_reward_decision(self.card, sat)
        outs = []
        for conv, s in zip(convs, sat):
            rv = quality_v4.review_v4(conv)
            refs = quality_v4.verify_refs(conv, rv) if conv.get("lines") else None
            row = feedback_v4.per_conversation_v4([rv], [s], {conv["conversation_id"]: conv.get("end")}, decision)[0]
            outs.append({
                "conversation_id": conv["conversation_id"], "file": conv.get("file"),
                "ticket_id": rv.get("ticket_id"), "order_id": rv.get("order_id"), "route": rv.get("route"),
                "priority": rv.get("priority"), "main_reason": rv.get("main_reason"), "outcome": rv.get("outcome"),
                "rule_id": rv.get("rule_id"), "resolution": rv.get("resolution"), "grade": rv["grade"],
                "closed_at": conv.get("end"), "seconds": rv.get("seconds"), "reply_source": rv.get("reply_source"),
                "predicted_satisfaction": s["predicted_satisfaction"],
                "raw_model_score": s.get("raw_model_score", s["predicted_satisfaction"]),
                "satisfaction_validity": {k: s[k] for k in ("model_id", "model_sha256", "label_type", "language",
                                                            "language_validated", "languages_validated",
                                                            "domain_validated", "validity", "usable_for", "reasons",
                                                            "input_turns", "training_median_turns")},
                "quality_flags": rv["flags"],
                "evidence_check": None if refs is None else {"n_refs": len(refs), "n_ok": sum(r["ok"] for r in refs),
                                                             "failed": [r for r in refs if not r["ok"]]},
                "rule_knowledge_warnings": self._rule_warnings(conv, rv),
                "e_reward_eligible": {"eligible": row["e_reward_eligible"], "reasons": row["reasons"],
                                      "shortfall_if_used": row["shortfall"]},
                "_conv": conv, "_review": rv})
        return outs[0] if len(outs) == 1 else outs

    def learn_from_reviews(self, records: list[dict], results: list[dict], allow_synthetic: bool = False) -> dict:
        """M7 "learns from real reviews": fit V3's ReviewCalibrator (isotonic map raw score -> measured rating,
        5-fold cross-validated, kept only if it beats the raw score and there are >= 50 reviews) on the
        conversations that HAVE a measured rating, and measure how unusual the reviewed conversations are
        (review_bias). Records must follow the reviews contract; only usable measured ratings are used
        (customer_submitted / annotator; ai_predicted never). Calibration does NOT make the score validated:
        validation needs the held-out evaluation (v4/f/annotation/eval_labels.py)."""
        import numpy as np
        from v3.m7.satisfaction import ReviewCalibrator, review_bias
        from v4.f.contracts.validate_reviews import validate
        ratings = {}
        skipped = 0
        for r in records:
            ok = not validate(r) and r["rating_source"] in ("customer_submitted", "annotator") \
                and "model_validation" in r["consent"]["scope"] and not r["data_quality"]["is_duplicate"] \
                and (allow_synthetic or not r["data_quality"]["is_test_or_synthetic"])
            if ok:
                ratings.setdefault(r["conversation_id"], []).append(float(r["rating"]))
            else:
                skipped += 1
        raw = {x["conversation_id"]: x.get("raw_model_score", x["predicted_satisfaction"]) for x in results}
        ids = [c for c in ratings if raw.get(c) is not None]
        cal = ReviewCalibrator(min_reviews=50)
        rep = cal.fit(np.array([raw[c] for c in ids]), np.array([np.mean(ratings[c]) for c in ids]))
        self.calibrator = cal if rep.get("used") else None
        bias = review_bias({c: ratings[c] for c in ratings}, [x["_review"] for x in results if "_review" in x],
                           [x["_conv"] for x in results if "_conv" in x])
        self.calibration_report = {"calibrator": rep, "n_records_skipped": skipped, "n_reviewed_and_scored": len(ids),
                                   "review_bias": bias, "synthetic_allowed": allow_synthetic}
        return self.calibration_report

    def process_folder(self, folder) -> list[dict]:
        out = []
        for p in sorted(Path(folder).glob("*.jsonl")):
            r = self.process(p)
            out += r if isinstance(r, list) else [r]
        return out

    # ---------------- many conversations ----------------
    def owner_report(self, results: list[dict], corpus_label: str = "") -> dict:
        from v4.f.m7.report_v4 import build_owner_report
        return build_owner_report(self, results, corpus_label)


def strip_private(result: dict) -> dict:
    """The process() output without the internal parsed record (for JSON files)."""
    return {k: v for k, v in result.items() if not k.startswith("_")}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("trace")
    ap.add_argument("--scorer", default="none")
    a = ap.parse_args()
    f = AgentF.load({"scorer": a.scorer})
    r = f.process(a.trace)
    print(json.dumps([strip_private(x) for x in (r if isinstance(r, list) else [r])], indent=1, default=str))
