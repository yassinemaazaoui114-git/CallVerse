"""Does the client's sentence ask for THIS action? Word checks, no model (T14d). Used by Intake and by both Coordinators.

Why this file? In T14c's held-out run two writes happened that the client did not ask for:
- h12 (ShopNova): "... Prime membership is appearing at my Visa statement ... please cancel this payment Order 4514."
  The sentence says "cancel", so the T14a word rule said cancel_order, and order 4514 was cancelled. The client wanted
  a CHARGE stopped, not the order.
- h03 (Atlas): "reimbursement (hotel stay) for the cancelled VS20 flight". By meaning this was refund_request, and a
  690 TND ticket refund was paid. The client asked for their hotel costs (an expense = a compensation question).

So two rules, by whole words (the same style as the cancel word of T14a and the damage word of T14c):

cancels_order(sentence, message) - ShopNova: the "cancel" of this sentence is about the ORDER. Not when:
  1. the sentence is about a subscription / membership / account / plan (T14a rule, kept);
  2. the thing cancelled is money: "cancel this payment", "cancel the charge", "cancel my subscription";
  3. the client pressed a cancel button by accident ("I pressed cancel by accident, how do I fix this");
  4. the message talks about money (payment, charge, statement, membership, prime ...) and the sentence does not say
     WHICH order to cancel: "I was charged for Prime ... please cancel it" -> ask first.
  "cancel my order 4511" (the order named right after the word) still wins over 3 and 4.

asks_for_expenses(sentence) - Atlas: the client asks to be paid back for costs AROUND the trip (hotel costs after a
  cancelled flight, meals, a taxi, "reimbursement of my expenses"): that is a compensation question, not a ticket refund.
  "reimburse my ticket / my booking" is still a refund.
"""

import re

# The cancel word (same as reasons.CANCEL_WORD_RE, T14a; "cancle" is a typo seen in real tweets).
CANCEL_WORD_RE = re.compile(r"\b(?:cancel|cancle|cancell?ing)\b", re.IGNORECASE)
# T14a: cancelling a subscription or an account is not cancelling an order (the whole sentence).
NOT_AN_ORDER_RE = re.compile(r"\b(?:subscriptions?|memberships?|prime|accounts?|plans?)\b", re.IGNORECASE)

# Money words: a charge, not an order. "prime" = the Prime membership service.
MONEY_WORDS = (r"(?:payments?|charges?|charged|billing|bills?|statements?|memberships?|subscriptions?|prime|"
               r"transactions?|fees?|debits?|debited)")
# Small words that may stand between "cancel" and its object ("cancel this payment", "cancel the whole order").
SMALL = r"(?:this|that|these|those|the|my|a|an|our|its|whole|entire|full|of|all)"
# 2. "cancel (this) payment": the thing cancelled is money.
CANCEL_MONEY_RE = re.compile(rf"\b(?:cancel|cancle)\w*\s+(?:{SMALL}\s+){{0,2}}{MONEY_WORDS}\b", re.IGNORECASE)
# "cancel my order", "cancel order 4511", "cancel #4511": the order is named as the thing cancelled.
CANCEL_ORDER_RE = re.compile(rf"\b(?:cancel|cancle)\w*\s+(?:{SMALL}\s+){{0,2}}(?:orders?|purchases?|items?|#?\d{{3,}})\b",
                             re.IGNORECASE)
# 3. A cancel BUTTON pressed BY ACCIDENT: "pressed cancel by accident", "accidentally hit cancel", "accidentally
# cancel". Both parts are needed: "I tap on cancel and nothing happens" (practice s03) is a client TRYING to cancel.
BUTTON_RE = re.compile(r"\b(?:press(?:ed|ing)?|hit(?:ting)?|click(?:ed|ing)?|tap(?:ped|ping)?|push(?:ed|ing)?)\s+"
                       r"(?:on\s+)?(?:the\s+)?[\"'“]?(?:cancel|cancle)\b|\baccidentally\s+(?:cancel|cancle)\w*",
                       re.IGNORECASE)
ACCIDENT_RE = re.compile(r"\b(?:accident\w*|by\s+mistake|mistakenly|unintentionally)\b", re.IGNORECASE)
# 4. Money words anywhere in the message.
MONEY_RE = re.compile(rf"\b{MONEY_WORDS}\b", re.IGNORECASE)


def cancels_order(sentence: str, message: str | None = None) -> bool:
    """True when this sentence asks to cancel the ORDER (rules 1-4 at the top). `message` = the whole message
    (rule 4); without it only the sentence is read."""
    text = (sentence or "").replace("’", "'")
    if not CANCEL_WORD_RE.search(text) or NOT_AN_ORDER_RE.search(text):
        return False                                   # no cancel word, or a subscription / account (rule 1)
    if CANCEL_MONEY_RE.search(text):
        return False                                   # rule 2: "cancel this payment"
    if CANCEL_ORDER_RE.search(text):
        return True                                    # "cancel my order 4511": the order is named
    if BUTTON_RE.search(text) and ACCIDENT_RE.search(text):
        return False                                   # rule 3: a button pressed by accident
    return MONEY_RE.search(message or text) is None    # rule 4: money talk, and the order is not named


# Costs around the trip. "reimburs..." alone counts (h03: "reimbursement (hotel stay)"), unless the thing reimbursed is
# the ticket / booking itself (then it is a refund). "hotel stay" alone does not count: at Atlas a hotel stay can be
# the booking itself ("refund my hotel stay" on a hotel booking is a refund).
EXPENSE_RE = re.compile(
    r"\b(?:reimburs\w*|expenses?|out[- ]of[- ]pocket|meals?|taxis?|cabs?|accommodation)\b"
    r"|\bhotel\s+(?:costs?|bills?|expenses?|vouchers?|charges?)\b"
    r"|\b(?:pay|pays|paid|paying|cover|covers|covering|compensat\w*)\s+(?:me\s+|us\s+)?(?:for\s+)?(?:the\s+|my\s+|a\s+|our\s+)?hotel\b",
    re.IGNORECASE)
# "reimburse my ticket", "reimbursement of the booking": the ticket itself, so a refund.
REIMBURSE_TICKET_RE = re.compile(r"\breimburs\w*\s+(?:(?:me|us|for|of|the|my|our|a)\s+){0,2}"
                                 r"(?:tickets?|fares?|bookings?|flights?|deposits?|reservations?)\b", re.IGNORECASE)


def asks_for_expenses(sentence: str) -> bool:
    """True when the sentence asks for costs around the trip (hotel costs, meals, taxi, expenses), see the top."""
    text = (sentence or "").replace("’", "'")
    return EXPENSE_RE.search(text) is not None and REIMBURSE_TICKET_RE.search(text) is None
