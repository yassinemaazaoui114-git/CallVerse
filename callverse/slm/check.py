"""Rule check for SLM replies (plain code, no model).

The SLM decides only HOW to say the Coordinator's decision. This check makes sure the reply says
nothing more than the decision: no new number, no forbidden promise, no internal rule id, no invented name.
check_reply(reply, decision) -> {"passed": bool, "problems": [str, ...]}
"""

import re

MAX_WORDS = 120

# A number in text: 59.90, 59,90, 2026, 6, 03 ... (dates "2026-10-03" give 2026, 10 and 03).
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
RULE_ID_RE = re.compile(r"\bR-[A-Z]{3}-\d{2}\b")
PLACEHOLDER_RE = re.compile(r"\[[^\]]{1,40}\]|\{[^}]{1,40}\}|<[^>]{1,40}>|\bX{3,}\b")
CURRENCY_RE = re.compile(r"[$€£]|\b(?:USD|EUR|dollars?|euros?)\b", re.IGNORECASE)
# Carrier / company names: a name in the reply that is not in the decision is an invented fact.
CARRIERS = ("aramex", "rapid-poste", "rapid poste", "fedex", "dhl", "ups", "la poste", "tnt", "chronopost", "amazon")

# Forbidden promises: (pattern, keyword). A phrase is allowed only if its keyword appears in the
# decision's own text (facts or next_step): then the Coordinator approved that idea.
FORBIDDEN = [
    (r"keep you (?:updated|informed|posted)", "keep you"),
    (r"\b(?:we are|we're|we will be|we'll be|actively)\s+monitoring\b|\bmonitor(?:ing)? (?:it|your|the)\b", "monitor"),
    (r"\bguarantee", "guarantee"),
    (r"\bwithin (?:\d+|a|an|one|two|three|four|five|six|seven|the next|a few|few)\s*"
     r"(?:\w+\s)?(?:hours?|days?|business days|working days|minutes?|weeks?)\b", "within"),
    (r"\b(?:we will|we'll|i will|i'll) (?:contact|call|chase|reach out to) the carrier", "carrier"),
    (r"\b(?:we will|we'll|i will|i'll) (?:notify|alert|inform) you\b|\byou will (?:be notified|receive a notification)",
     "notif"),
    (r"\b(?:as soon as possible|asap|right away|immediately|shortly|soon|right back|in no time)\b", "soon"),
    (r"\bkeep an eye\b|\b(?:any|further|future|more) updates?\b|\bbe in touch\b", "update"),
    (r"\b(?:compensation|voucher|discount|coupon|gift card)\b", "compensation"),
]

# Refund promises: only allowed when the Coordinator approved a refund.
REFUND_PROMISE = re.compile(
    r"\brefund\b(?:[^.!?]|\.\d){0,40}?\b(?:has been|is|was|will be) "   # "\.\d" lets "189.00" stay inside
    r"(?:approved|confirmed|processed|issued|granted|paid|sent|credited|transferred)"
    r"|\b(?:you will|you'll) (?:receive|get) (?:a |your |the |a full )?(?:full )?refund"
    r"|\b(?:we will|we'll|i will|i'll) (?:refund|reimburse)"
    r"|\b(?:we have|we've) (?:refunded|approved (?:your|the) refund)"
    r"|\bapproved for (?:a |the |your )?(?:full )?refund"
    r"|\b(?:money|amount|payment) (?:has been|will be|is being|is) "
    r"(?:refunded|returned|credited|sent back|transferred back|on its way)",
    re.IGNORECASE)


def _numbers(text: str) -> set[float]:
    """All numbers found in a text, as floats ("59,90" counts as 59.90)."""
    return {float(n.replace(",", ".")) for n in NUMBER_RE.findall(text)}


def _decision_text(decision: dict) -> str:
    """All text the Coordinator approved: facts (values) and next_step, lower case."""
    parts = [str(v) for v in (decision.get("facts") or {}).values()]
    parts.append(str(decision.get("next_step") or ""))
    return " ".join(parts).lower()


def allowed_numbers(decision: dict) -> set[float]:
    """Numbers the reply may use: from facts, order_id and next_step (all approved by the Coordinator)."""
    allowed = _numbers(_decision_text(decision))
    if decision.get("order_id") is not None:
        allowed.add(float(decision["order_id"]))
    return allowed


def check_reply(reply: str, decision: dict) -> dict:
    problems = []
    text = (reply or "").strip()
    if not text:
        return {"passed": False, "problems": ["the reply is empty"]}
    low = text.lower()

    words = len(text.split())
    if words > MAX_WORDS:
        problems.append(f"too long: {words} words (max {MAX_WORDS})")

    allowed = allowed_numbers(decision)
    extra = sorted({n for n in _numbers(text) if n not in allowed})
    if extra:
        shown = ", ".join(f"{n:g}" for n in extra)
        problems.append(f"numbers not in the decision: {shown} (use only the numbers given in the facts)")

    if decision.get("order_id") is not None and str(decision["order_id"]) not in text:
        problems.append(f"the order number {decision['order_id']} is not mentioned")

    approved_text = _decision_text(decision)
    for pattern, keyword in FORBIDDEN:
        match = re.search(pattern, low)
        if match and keyword not in approved_text:
            problems.append(f"forbidden promise: '{match.group(0)}'")

    refund_ok = decision.get("outcome") == "approve" and decision.get("action") == "refund"
    if not refund_ok and (m := REFUND_PROMISE.search(text)):
        problems.append(f"promises a refund that is not approved: '{m.group(0)}'")

    for name in CARRIERS:
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", low) and name not in approved_text:
            problems.append(f"name not in the decision: '{name}'")

    sentences = [x.strip().lower() for x in re.split(r"(?<=[.!?])\s+", text) if len(x.split()) >= 4]
    if len(sentences) != len(set(sentences)):
        problems.append("a sentence is repeated")

    if m := CURRENCY_RE.search(text):
        problems.append(f"wrong currency '{m.group(0)}': amounts are in TND")
    if m := RULE_ID_RE.search(text):
        problems.append(f"internal rule id in the reply: {m.group(0)}")
    if m := PLACEHOLDER_RE.search(text):
        problems.append(f"placeholder in the reply: {m.group(0)}")

    return {"passed": not problems, "problems": problems}
