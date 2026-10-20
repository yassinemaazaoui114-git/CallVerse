"""Find the order number, email and phone in a client message, with regular expressions.

No model is needed here: these are fixed formats, so rules are faster, cheaper and 100% predictable.
The order number is only a CLAIM from the user; intake.py checks it with the get_order tool.
"""

import re

# An order number = 4 to 6 digits, optionally written "#4512".
# (?<![\d.,/+-]) and (?![\d.,/-]\d): the digits must stand alone, so we do not take a piece of
# an amount ("1500.50"), a date ("09/10/2026") or a phone number ("+216 20 111 222" has no 4-digit block).
ORDER_RE = re.compile(r"(?<![\d.,/+-])#?(\d{4,6})(?![\d]|[.,/-]\d)")

# Words that, just before the number, make us sure it is an order number ("order 4512", "#4512", "commande 4512").
ORDER_CONTEXT_RE = re.compile(r"(order|commande|parcel|package|n°|no\.?|number|#)\s*#?\s*$", re.IGNORECASE)

# A number followed by a currency is an amount, never an order number ("1500 TND").
CURRENCY_AFTER_RE = re.compile(r"^\s*(tnd|dt|dinars?|eur|€|\$)", re.IGNORECASE)

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

# Tunisian phone: optional +216 / 00216, then 8 digits, possibly grouped "20 111 222" or "20-111-222".
# Without the prefix, the 8 digits must not be glued to other digits ((?<!\d) ... (?!\d)).
PHONE_RE = re.compile(r"(?:(?:\+|00)216[\s.-]?|(?<!\d))\d{2}[\s.-]?\d{3}[\s.-]?\d{3}(?!\d)")


def find_order_id(text: str) -> int | None:
    """Return the order number in the text, or None.

    If several numbers match, one with an order word just before it ("order 4512", "#4512") wins;
    otherwise the first one. Numbers followed by a currency are skipped (they are amounts).
    """
    candidates = []
    for m in ORDER_RE.finditer(text):
        if CURRENCY_AFTER_RE.match(text[m.end():]):
            continue
        has_context = m.group(0).startswith("#") or bool(ORDER_CONTEXT_RE.search(text[:m.start()]))
        candidates.append((has_context, int(m.group(1))))
    if not candidates:
        return None
    with_context = [number for has_context, number in candidates if has_context]
    return with_context[0] if with_context else candidates[0][1]


def find_email(text: str) -> str | None:
    """Return the first email address in the text (lower case), or None."""
    m = EMAIL_RE.search(text)
    return m.group(0).lower() if m else None


def find_phone(text: str) -> str | None:
    """Return the first phone number in the text, written like the database ("+216 20 111 222"), or None."""
    m = PHONE_RE.search(text)
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(0))[-8:]   # keep the 8 local digits
    return f"+216 {digits[:2]} {digits[2:5]} {digits[5:]}"


def extract(text: str) -> dict:
    """All three at once: {"order_id", "email", "phone"} (None when not found)."""
    return {"order_id": find_order_id(text), "email": find_email(text), "phone": find_phone(text)}
