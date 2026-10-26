"""M7 v5 (F9): quality checks added to M7 v4 after re-auditing it against the user's list. Deterministic, no model.

    review_v5(conv) -> review_v4(conv) + the v5 flags below (conv from v4.f.m7.conversations_v4.parse_trace_v4)

The user's list and where each item is checked (full table in v5/deliverables/F_M7_REVIEW.md):
  contradicts tool facts            v4 claim_false (structured facts the agent claimed)
  unconfirmed refund promise        NEW reply_refund_promise_unbacked
  unconfirmed delivery promise      NEW reply_delivery_promise_unsupported
  unsupported answers               v4 claim_unsupported / agent_answered_without_tools; NEW reply_number_unsupported
  leaked instructions               v4 reply_leak (internal words); NEW reply_instruction_leak (prompt / JSON words)
  wrong language                    v4 reply_language_mismatch (FR client, non-FR reply);
                                    NEW reply_language_unexpected (EN client, FR reply: the reverse direction)
  unresolved promised follow-ups    NEW followup_promise_unbacked
  business-rule violations          v4 missed_entitlement / cited_missing_rule / sent_back; NEW refund_exceeds_balance
Why these are deterministic and testable on the trace format:
  - the final reply is in `pipeline_done.final_reply`; the approved decision in `pipeline_done.decision`
    (outcome, action, facts, must_say, next_step); what was EXECUTED is in the `db_write` lines
    (create_refund, create_subscription); the Coordinator's own re-read of the facts is the `facts_from_data` check.
  - The prototype's SLM check (callverse/slm/check.py) already blocks some of these BEFORE sending, but it trusts the
    decision and it is English-only. M7 re-checks AFTER the fact, against what was actually executed, and in French
    too — a defence in depth that also catches a template / writer regression (check.py is imported, not copied,
    so both use the same English refund-promise definition).
Not checkable deterministically (documented, not faked): promises worded in free paraphrase outside the patterns,
correctness of the client's language when it is neither EN nor FR, claims in agent free text.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[5]))          # repository root (callverse)
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))          # experiments/agents_ef
from callverse.slm.check import REFUND_PROMISE, _numbers, allowed_numbers  # noqa: E402
from v3.m7.quality import FR_WORDS, SEVERITY_ORDER  # noqa: E402
from v4.f.m7.quality_v4 import CODES as CODES_V4, review_v4  # noqa: E402

NEW_CODES = ("reply_refund_promise_unbacked", "reply_delivery_promise_unsupported", "reply_number_unsupported",
             "reply_instruction_leak", "reply_language_unexpected", "followup_promise_unbacked",
             "refund_exceeds_balance")
CODES = CODES_V4 + NEW_CODES

# French refund promises (check.py covers English only).
FR_REFUND_PROMISE = re.compile(
    r"\b(?:vous serez|vous allez être) rembours\w*"
    r"|\b(?:nous allons|nous vous) rembours\w*"
    r"|\bremboursement\b(?:[^.!?]|\.\d){0,40}?\b(?:a été|est|sera) (?:approuvé|validé|effectué|accepté|confirmé)\w*"
    r"|\b(?:vous recevrez|vous allez recevoir) (?:un |votre |le )?remboursement",
    re.IGNORECASE)
# Concrete delivery-time promises. The platform has no ETA tool (get_tracking gives only promised_date /
# delivered_date), so a promise of WHEN the parcel will arrive cannot come from data unless it repeats one of those.
DELIVERY_PROMISE = re.compile(
    r"\b(?:will|should|is going to|'ll)\s+(?:arrive|be delivered|reach you|get to you)\b[^.!?]{0,40}?"
    r"\b(?:today|tonight|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|this week|next week"
    r"|within \d+|in \d+ (?:days?|hours?)|by \d|on \d)"
    r"|\bsera\s+livr\w*\s+(?:aujourd'hui|demain|lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|cette semaine"
    r"|la semaine prochaine|sous \d+|dans \d+|d'ici|le \d)",
    re.IGNORECASE)
NOTIFY_PROMISE = re.compile(
    r"\byou will (?:get|receive) a (?:message|notification|text|sms|e-?mail)"
    r"|\bwe(?: will|'ll) (?:notify|let you know|inform|alert|message) you"
    r"|\bvous (?:recevrez|allez recevoir) un (?:message|sms|e-?mail|courriel|notification)"
    r"|\bnous vous (?:préviendrons|informerons|enverrons un message)", re.IGNORECASE)
CONTACT_PROMISE = re.compile(
    r"\b(?:a colleague|someone|an agent|our team|a member of our team) will (?:take over|contact|call|get back)"
    r"|\bwe(?: will|'ll) (?:contact|call|get back to) you"
    r"|\bun collègue (?:va|vous) (?:prendre|recontacter|contacter|rappeler)\w*"
    r"|\bnous (?:vous )?(?:recontacterons|rappellerons|reviendrons vers vous)", re.IGNORECASE)
# Leaked instructions / prompt / tool-format words (v4 reply_leak covers the prototype's internal words).
INSTRUCTION_LEAK = re.compile(
    r"system prompt|my instructions|i was instructed|i am instructed|as an ai\b|language model|"
    r"\btool_calls?\b|facts_used|user_quote|must_say|next_step|allowed_tools|\"outcome\"|\{\s*\"|"
    r"\bget_(?:order|tracking|refunds|user)\b|\bpropose_\w+", re.IGNORECASE)
EN_WORDS = re.compile(r"\b(the|my|order|is|not|and|please|where|when|refund|late|you|it|was|have)\b", re.IGNORECASE)


def db_writes(conv: dict) -> list[tuple[int, dict]]:
    return [(n, d) for n, (step, d, _) in sorted((conv.get("lines") or {}).items()) if step == "db_write"]


def coordinator_reread(conv: dict) -> dict:
    """The last facts_from_data re-read by the Coordinator in this conversation (its own data read)."""
    out = {}
    for c in conv.get("checks", []):
        if c.get("check") == "facts_from_data" and isinstance(c.get("facts"), dict):
            out = c["facts"]
    return out


def new_flags(conv: dict) -> list[dict]:
    flags = []
    reply = conv.get("final_reply") or ""
    decision = conv.get("decision") or {}
    ref = conv.get("done_ref")
    writes = db_writes(conv)
    refunds = [(n, d) for n, d in writes if d.get("function") == "create_refund"]
    subs = [(n, d) for n, d in writes if d.get("function") == "create_subscription"]
    fname = conv.get("file")

    def add(code, sev, what, ev):
        flags.append({"code": code, "severity": sev, "what": what, "evidence": {**ev, "ref": ref}})

    # 1. refund promised without an approved AND executed refund
    m = REFUND_PROMISE.search(reply) or FR_REFUND_PROMISE.search(reply)
    approved = decision.get("outcome") == "approve" and decision.get("action") == "refund"
    if m and not (approved and refunds):
        add("reply_refund_promise_unbacked", "high",
            "the reply promises a refund that was not " + ("executed (no create_refund)" if approved else "approved"),
            {"phrase": m.group(0), "outcome": decision.get("outcome"), "action": decision.get("action"),
             "create_refund_refs": [f"{fname}:{n}" for n, _ in refunds]})
    # 2. concrete delivery-time promise not backed by a date from the data
    m = DELIVERY_PROMISE.search(reply)
    if m:
        facts = {**coordinator_reread(conv), **(decision.get("facts") or {})}
        dates = {str(facts.get(k)) for k in ("promised_date", "delivered_date") if facts.get(k)}
        # the exemption looks only at the SENTENCE that holds the promise: a data date elsewhere in the reply
        # ("the promised delivery date was ...") does not back "it will arrive tomorrow" (mutation test, v5).
        start = max(reply.rfind(x, 0, m.start()) for x in ".!?") + 1
        ends = [i for i in (reply.find(x, m.end()) for x in ".!?") if i >= 0]
        sentence = reply[start:min(ends) if ends else len(reply)]
        if not any(d in sentence for d in dates):
            add("reply_delivery_promise_unsupported", "medium",
                "the reply promises when the parcel will arrive; no tool gives an arrival time",
                {"phrase": m.group(0), "dates_in_data": sorted(dates)})
    # 3. numbers in the reply that are in neither the approved decision nor the client's own message
    allowed = allowed_numbers(decision) | _numbers(conv.get("client_text") or "")
    extra = sorted(n for n in _numbers(reply) if n not in allowed)
    if extra:
        add("reply_number_unsupported", "medium", "the reply states numbers that no approved fact contains",
            {"numbers": extra, "allowed": sorted(allowed)})
    # 4. leaked instructions / tool format
    leaks = sorted({x.group(0) for x in INSTRUCTION_LEAK.finditer(reply)})
    if leaks:
        add("reply_instruction_leak", "high", "prompt / tool-format words reached the client", {"words": leaks})
    # 5. English client answered in French (v4 covers French client answered in English)
    client = conv.get("client_text") or ""
    en_in, fr_in, fr_out = len(EN_WORDS.findall(client)), len(FR_WORDS.findall(client)), len(FR_WORDS.findall(reply))
    if en_in >= 3 and fr_in <= 1 and fr_out >= 3:
        add("reply_language_unexpected", "medium", "client wrote in English, the reply is in French",
            {"client_en_words": en_in, "client_fr_words": fr_in, "reply_fr_words": fr_out})
    # 6. follow-up promised but nothing in the trace will make it happen
    m = NOTIFY_PROMISE.search(reply)
    if m and not subs:
        add("followup_promise_unbacked", "medium", "the reply promises a message, but no subscription was created",
            {"phrase": m.group(0), "kind": "notification"})
    m = CONTACT_PROMISE.search(reply)
    if m and decision.get("outcome") not in ("escalate", "layer3") and not conv.get("handover"):
        add("followup_promise_unbacked", "medium",
            "the reply promises a human follow-up, but the case was not escalated or handed over",
            {"phrase": m.group(0), "kind": "contact", "outcome": decision.get("outcome")})
    # 7. executed refund larger than what the client paid minus what was already refunded
    rr = coordinator_reread(conv)
    for n, d in refunds:
        amt = (d.get("args") or {}).get("amount")
        if isinstance(amt, (int, float)) and isinstance(rr.get("paid"), (int, float)):
            bal = float(rr["paid"]) - float(rr.get("refunded_total") or 0)
            if amt > bal + 0.005:
                add("refund_exceeds_balance", "high", f"refund of {amt} executed; balance was {bal:.2f}",
                    {"amount": amt, "paid": rr["paid"], "refunded_total": rr.get("refunded_total"),
                     "write_ref": f"{fname}:{n}"})
    return flags


def review_v5(conv: dict) -> dict:
    r = review_v4(conv)
    flags = r["flags"] + new_flags(conv)
    worst = max((SEVERITY_ORDER[f["severity"]] for f in flags), default=0)
    return {**r, "flags": flags, "grade": {3: "fail", 2: "review", 1: "ok_minor", 0: "ok"}[worst],
            "checks_version": "m7-v5"}
