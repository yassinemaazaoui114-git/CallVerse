"""Agent F dual reward: satisfaction (predicted) + correctness (rules) -> RL reward. Semah's lane (RL3).

    evaluate_response(record) -> {"satisfaction": float, "correctness": "PASS"|"FAIL"|"UNKNOWN",
                                  "reward": 1 | -1 | None, "train": bool, "evidence": [str, ...]}

record = the spec "Conversation record" (ticket_id, company, messages, situation, style) plus, for the
correctness check, "decision": the Coordinator's decision dict (docs/decision_format.md). The reply that is
checked is record["reply"] or the last assistant message.

Correctness reuses existing plain-code checks, no LLM:
- tenant isolation: decision.rule_id must exist in THIS company's policy file (kb.policies.get_policy);
- policy compliance: the rule's condition must hold for decision.facts (kb.policies.check_condition);
- facts / promises: slm.check.check_reply (numbers only from facts, no forbidden or unapproved refund promise,
  must_say present, no rule id, no placeholder). The facts come from the Coordinator's tool reads.
UNKNOWN whenever evidence is missing (no decision, no reply, unknown company, condition not checkable).
Reward: PASS and satisfaction >= 4 -> +1; PASS and < 4 -> -1; FAIL -> -1; UNKNOWN -> None (not trained on).
A friendly but wrong reply can never get +1.
"""
from __future__ import annotations

from callverse import companies
from callverse.kb.policies import check_condition, get_policy
from callverse.quality.satisfaction import predict_satisfaction
from callverse.slm.check import check_reply

OUTCOMES = {"approve", "send_back", "ask_user", "ask_proof", "layer3", "escalate", "info"}
GOOD = 4.0   # satisfaction at or above this counts as a satisfied customer


def reply_text(record: dict) -> str:
    if record.get("reply"):
        return str(record["reply"]).strip()
    msgs = [m for m in record.get("messages") or [] if m.get("role") == "assistant"]
    return (msgs[-1].get("text") or "").strip() if msgs else ""


def check_correctness(record: dict) -> dict:
    """Return {"status": PASS|FAIL|UNKNOWN, "evidence": [str]}."""
    evidence, fail = [], False
    decision, reply, company = record.get("decision"), reply_text(record), record.get("company")
    if not isinstance(decision, dict):
        return {"status": "UNKNOWN", "evidence": ["no Coordinator decision in the record"]}
    if not reply:
        return {"status": "UNKNOWN", "evidence": ["no assistant reply to check"]}
    if decision.get("outcome") not in OUTCOMES:
        return {"status": "UNKNOWN", "evidence": [f"unknown outcome {decision.get('outcome')!r}"]}
    if decision.get("company") and decision["company"] != company:
        return {"status": "FAIL", "evidence": [f"decision made for {decision['company']!r}, record is {company!r}"]}

    rule_id = decision.get("rule_id")
    if rule_id:
        try:
            rule = get_policy(rule_id, company)
        except Exception as e:  # noqa: BLE001  (unknown company: no policy file)
            return {"status": "UNKNOWN", "evidence": [f"cannot read policies of {company!r}: {e}"]}
        if rule is None:
            fail = True
            evidence.append(f"rule {rule_id} is not in {company}'s policies (tenant isolation)")
        elif rule.get("condition") and decision.get("facts") is not None:
            try:
                if check_condition(rule["condition"], decision["facts"]):
                    evidence.append(f"rule {rule_id} condition holds")
                else:
                    fail = True
                    evidence.append(f"rule {rule_id} condition does not hold for the facts")
            except ValueError as e:
                evidence.append(f"rule {rule_id} condition not checkable: {e}")
    elif decision.get("outcome") == "approve":
        evidence.append("approve without rule_id: not checkable")

    checked = check_reply(reply, decision)
    if checked["passed"]:
        evidence.append("reply check passed (facts, promises, must_say)")
    else:
        fail = True
        evidence += [f"reply check: {p}" for p in checked["problems"]]

    if fail:
        return {"status": "FAIL", "evidence": evidence}
    if not decision.get("facts") and decision.get("outcome") != "ask_user":
        return {"status": "UNKNOWN", "evidence": evidence + ["no facts in the decision: fact grounding unknown"]}
    return {"status": "PASS", "evidence": evidence}


def reward_of(correctness: str, satisfaction: float):
    if correctness == "PASS":
        return 1 if satisfaction >= GOOD else -1
    if correctness == "FAIL":
        return -1
    return None


def evaluate_response(record: dict, **kw) -> dict:
    """Satisfaction + correctness + reward for one conversation record (kw go to predict_satisfaction)."""
    satisfaction = predict_satisfaction(record, **kw)["score"]
    corr = check_correctness(record)
    reward = reward_of(corr["status"], satisfaction)
    return {"satisfaction": satisfaction, "correctness": corr["status"], "reward": reward,
            "train": reward is not None, "evidence": corr["evidence"]}
