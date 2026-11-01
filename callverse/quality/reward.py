"""Agent F dual reward: satisfaction (predicted) + correctness (rules) -> RL reward. Semah's lane (RL3).

    evaluate_response(record) -> {"satisfaction": float, "correctness": "PASS"|"FAIL"|"UNKNOWN",
                                  "reward": 1 | -1 | None, "train": bool, "evidence": [str, ...]}

record = the spec "Conversation record" (ticket_id, company, messages, situation, style) plus, for the
correctness check, "decision": the Coordinator's decision dict (docs/decision_format.md). The reply that is
checked is record["reply"] or the last assistant message.

Correctness reuses existing plain-code checks, no LLM:
- tenant isolation: decision.rule_id must exist in THIS company's policy file (kb.policies.get_policy);
- policy compliance: for an approve, the rule's condition must hold for decision.facts (check_condition);
- connector facts: decision.facts are re-read from the company's own tools (ShopNova get_tracking / get_order /
  get_refunds, Atlas get_hotel_booking / get_flight_booking / get_refunds) and must match; a refund may not
  exceed paid - refunded_total. Facts that only come from the record are "trusted", never "verified";
- facts / promises: slm.check.check_reply (numbers only from facts, no forbidden or unapproved refund promise,
  must_say present, no rule id, no placeholder) + no fabricated completed action, no delivery promise.
UNKNOWN whenever evidence is missing (no decision, no reply, unknown company, connector unavailable).
Reward: PASS and satisfaction >= 4 -> +1; PASS and < 4 -> -1; FAIL -> -1; UNKNOWN -> None (not trained on).
A friendly but wrong reply can never get +1.
"""
from __future__ import annotations

import re

from callverse import companies
from callverse.kb.policies import check_condition, get_policy
from callverse.quality.satisfaction import predict_satisfaction
from callverse.slm.check import check_reply

OUTCOMES = {"approve", "send_back", "ask_user", "ask_proof", "layer3", "escalate", "info"}
GOOD = 4.0   # satisfaction at or above this counts as a satisfied customer
# A completed action the reply claims, allowed only when the Coordinator approved that action.
COMPLETED_ACTION = re.compile(
    r"\b(?:we have|we've|has been|have been|is now|was) (?:already )?"
    r"(?:re-?booked|re-?shipped|re-?sent|cancelled|canceled|replaced|exchanged|changed|upgraded|compensated)\b",
    re.IGNORECASE)
# Approve + refusal in the same reply (or the reverse) contradicts the decision.
REFUSAL = re.compile(r"\b(?:we )?cannot (?:approve|refund|accept)|\bnot possible to (?:refund|approve)|\bis refused\b", re.IGNORECASE)
# A fact VALUE stated in the reply must equal the decision's value for that fact (a number allowed elsewhere in the
# decision, e.g. "more than 5 days" in the next step, must not be passed off as the order's own delay).
STATED_DAYS_LATE = re.compile(r"\bit is (\d+) days? late\b", re.IGNORECASE)
STATED_AMOUNT = re.compile(r"\b(?:refund|amount|refunded|credited)\b[^.]{0,30}?\b(\d+(?:[.,]\d+)?) ?TND", re.IGNORECASE)
DELIVERY_PROMISE = re.compile(r"\b(?:will|should) (?:arrive|be delivered|be there)\b", re.IGNORECASE)
ACTION_WORDS = {"rebook": "book", "reship": "ship", "cancel_hotel": "cancel", "replace": "replac", "refund": "refund"}


def verify_facts(record: dict) -> dict:
    """Re-read the decision's facts from the company's tools. {"status": verified|mismatch|unavailable, "notes"}.

    verified = every fact we can re-read matches; mismatch = a fact or amount contradicts the connector;
    unavailable = no connector / no reference / unknown company (facts are then only TRUSTED, not verified).
    """
    decision, company = record.get("decision") or {}, record.get("company")
    facts, ref = decision.get("facts") or {}, decision.get("order_id")
    if ref is None or not facts:
        return {"status": "unavailable", "notes": ["no reference or no facts to verify"]}
    try:
        if company == "shopnova":
            from callverse.tools import shopnova_tools as t
            tr, od, rf = t.get_tracking(ref), t.get_order(ref), t.get_refunds(ref)
            if "error" in tr or "error" in od:
                return {"status": "mismatch", "notes": [f"order {ref} not found"]}
            live = {"days_late": tr["days_late"], "delivered": tr["delivered"], "order_status": tr["status"],
                    "days_since_delivery": tr["days_since_delivery"], "paid": float(od["paid"]),
                    "refunded_total": rf["refunded_total"]}
            payable = float(od["paid"]) - rf["refunded_total"]
        elif company == "atlas":
            from callverse.data.atlas import reads as r
            h = r.get_hotel_booking(ref)
            x, kind = (h, "hotel") if "error" not in h else (r.get_flight_booking(ref), "flight")
            if "error" in x:
                return {"status": "mismatch", "notes": [f"booking {ref} not found"]}
            refunded = r.get_refunds(kind, ref)["refunded_total"]
            live = {k: x.get(k) for k in ("status", "deposit_type", "days_before_arrival", "cancelled", "flight_status",
                                           "departure_delay_min", "cancellation_reason", "main_delay_cause",
                                           "room_changed") if k in x}
            live.update({"booking_type": kind, "paid_tnd": float(x["paid_tnd"]), "refunded_total": refunded})
            payable = float(x["paid_tnd"]) - refunded
        else:
            return {"status": "unavailable", "notes": [f"no connector for company {company!r}"]}
    except Exception as e:  # noqa: BLE001  (no database, no file: evidence missing)
        return {"status": "unavailable", "notes": [f"connector unavailable: {type(e).__name__}"]}
    notes, bad = [], []
    for k, v in facts.items():
        if k in live and live[k] != v and not (isinstance(v, (int, float)) and isinstance(live[k], (int, float))
                                                and abs(float(v) - float(live[k])) < 0.005):
            bad.append(f"{k}: decision says {v!r}, connector says {live[k]!r}")
    amount = facts.get("amount_tnd", facts.get("amount"))
    if amount is not None and decision.get("outcome") == "approve" and float(amount) > payable + 0.005:
        bad.append(f"amount {amount} exceeds payable {payable:.2f}")
    if bad:
        return {"status": "mismatch", "notes": bad}
    checked = sorted(k for k in facts if k in live)
    return {"status": "verified", "notes": [f"facts re-read from the {company} connector: {', '.join(checked) or 'reference only'}"]}


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
        elif rule.get("condition") and decision.get("outcome") == "approve" and decision.get("facts") is not None:
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

    facts_check = verify_facts(record)
    evidence += facts_check["notes"]
    if facts_check["status"] == "mismatch":
        fail = True

    low = reply.lower()
    if (m := COMPLETED_ACTION.search(low)) and not (decision.get("outcome") == "approve" and
                                                    ACTION_WORDS.get(decision.get("action"), "\0") in m.group(0)):
        fail = True
        evidence.append(f"claims a completed action that was not approved: '{m.group(0)}'")
    approved_text = " ".join([str(decision.get("next_step") or "")] + [str(x) for x in decision.get("must_say") or []]).lower()
    refusal_decided = any(w in approved_text for w in ("cannot", "not possible", "nothing to refund", "no refund", "refused", "no compensation"))
    if (m := REFUSAL.search(low)) and (decision.get("outcome") == "approve" or not refusal_decided):
        fail = True
        evidence.append(f"refuses something the Coordinator did not refuse: '{m.group(0)}'")
    if decision.get("outcome") != "approve" and re.search(r"\bhas been approved\b", low):
        fail = True
        evidence.append("says 'approved' for a decision that is not an approval")
    facts = decision.get("facts") or {}
    if facts.get("days_late") is not None:
        for m in STATED_DAYS_LATE.finditer(low):
            if int(m.group(1)) != int(facts["days_late"]):
                fail = True
                evidence.append(f"states '{m.group(0)}' but the facts say {facts['days_late']} days late")
    amount = facts.get("amount_tnd", facts.get("amount"))
    for m in STATED_AMOUNT.finditer(low):
        v = float(m.group(1).replace(",", "."))
        if amount is None or abs(v - float(amount)) > 0.005:
            fail = True
            evidence.append(f"states an amount of {v:g} TND that is not the decision's amount ({amount})")
    if (m := DELIVERY_PROMISE.search(low)) and not decision.get("facts", {}).get("promised_date"):
        fail = True
        evidence.append(f"delivery promise without a promised date in the facts: '{m.group(0)}'")

    checked = check_reply(reply, decision)
    if checked["passed"]:
        evidence.append("reply check passed (facts, promises, must_say)")
    else:
        fail = True
        evidence += [f"reply check: {p}" for p in checked["problems"]]

    if fail:
        return {"status": "FAIL", "evidence": evidence}
    if facts_check["status"] != "verified":
        return {"status": "UNKNOWN", "evidence": evidence + ["facts not verified by a connector: no PASS"]}
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
