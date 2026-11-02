"""Is a client's sentence a request said in the NEGATIVE? (T14c) One function for both companies' Coordinators.

    negated_request(sentence) -> True when the client says they do NOT want the action (cancel, refund, return,
                                 compensation), so the Coordinator asks first and writes nothing.

Why this file? Before T14c each Coordinator had its own check, and both were too simple:
- ShopNova looked for "not / don't / never / no longer" up to 3 words before "cancel". So "I'm not able to cancel"
  (a client who CANNOT cancel and asks us to do it) was read as "I do not want to cancel" (T14a held-out miss h08).
- Atlas blocked any sentence with a negative word in it, even "my flight was not on time, I want compensation".

The rule now, in two steps:
1. Phrases that say the client TRIED, CANNOT do it themselves, or is still WAITING for it are a request, not a
   negation. They are removed first: "can't / cannot / unable to / not able to cancel", "not getting the cancel
   option", "how do I cancel", "tried to cancel", "problems cancelling", "I was not refunded", "I didn't get my refund",
   T14d: "amount not refunded till date", "not credited for 10 days" (a time word after it = still waiting).
2. What is left is negative only when a negative word is close before the action word, with only "filler" words in
   between (want, to, a, my, the, order, ...): "do not want to return", "don't cancel", "never asked for a refund",
   "no longer want a refund", "should be rerouted NOT refunded". Other words in between break the link, so
   "didn't arrive so please cancel" stays a request ("arrive", "so", "please" are not filler words).
3. T28 (T14f follow-up): a plain "no" right before the action, said as a wish: "no refund please", "no refund
   needed", "no cancellation, thanks". Not when it is a complaint: "still no refund", "I got no refund", "no refund
   yet" (a "please" / "needed" / "thanks" must follow, and "still / got / received / yet / there is" must not come
   before; "no refund please help" stays a request).
Plain code, no model: the same sentence always gives the same answer, and each case is a unit test.

T28 also adds the confirmation of a bare "yes" (question_flags, yes_confirmation): see the end of this file.
"""

import re

# The actions a client can ask for (any ending: cancel, cancelled, cancelling, cancellation, refunded, returns ...).
# "cancle": a typo seen in real tweets.
ACTION = r"(?:cancel\w*|cancle\w*|refund\w*|return\w*|compensat\w*|money\s+back)"

# Step 1a: "I tried / I cannot / how do I / the app does not let me ..." + (up to 3 words) + the action:
# the client asks US to do it.
TRIED_OR_CANNOT = (r"(?:can't|cant|cannot|can\s+not|couldn't|couldnt|could\s+not|unable\s+to|not\s+able\s+to|"
                   r"not\s+getting|not\s+given|tried\s+to|try\s+to|trying\s+to|how\s+(?:do|can|could)\s+i|how\s+to|"
                   r"problems?|trouble|issues?|difficult\w*|(?:don't|dont|do\s+not|doesn't|does\s+not)\s+"
                   r"(?:have|see|show|let\s+me|work)|won't\s+let\s+me|will\s+not\s+let\s+me|"
                   # "I didn't get my refund", "never received the refund": still waiting for it
                   r"(?:didn't|didnt|did\s+not|haven't|havent|have\s+not|hasn't|has\s+not|never|not)\s+(?:yet\s+)?"
                   r"(?:get|got|gotten|receive|received|see|seen))")
# Step 1b: "I was not refunded", "it has not been cancelled": a complaint that it did not happen yet.
STILL_WAITING = r"(?:was|were|is|are|am|has|have|still)\s+not\s+(?:yet\s+)?(?:been\s+)?"
REQUEST_RE = re.compile(rf"\b(?:{TRIED_OR_CANNOT}(?:\s+\w+){{0,3}}?\s+|{STILL_WAITING}){ACTION}", re.IGNORECASE)
# Step 1c (T14d, held-out h04): "amount not refunded till date", "money not returned yet", "not credited for 10 days",
# "not yet refunded": a thing that did not come back, with a time word after it (yet / till / until / still / since /
# for N days / ... ago), or with "not yet" before it. A complaint that it did not happen = a request, even without
# "was / is / has" (step 1b). Without a time word it stays a negation: "should be rerouted NOT refunded".
DONE = r"(?:refunded|returned|credited|reimbursed)"
TIME_WORD = (r"(?:yet|till|until|still|since|ago|for\s+(?:\d+|a|an|one|two|three|four|five|six|several|many|few|"
             r"over|more\s+than|almost|nearly)\b|\d+\s+\w+\s+ago)")
COMPLAINT_RE = re.compile(rf"\bnot\s+(?:{DONE}(?:\s+\w+){{0,3}}?\s+{TIME_WORD}\b|yet\s+(?:been\s+)?{DONE})",
                          re.IGNORECASE)

# Step 2: a negative word, then at most 4 filler words, then the action.
NEGATIVE = r"(?:not|don't|dont|do\s+not|never|no\s+longer|didn't|didnt|doesn't|doesnt)"
FILLER = (r"(?:want|wanna|wish|need|like|would|to|get|getting|a|an|any|my|the|it|this|that|"
          r"order|booking|flight|ticket|for|me|ask|asked|asking|request|requested|requesting|looking|going)")
NEGATED_RE = re.compile(rf"\b{NEGATIVE}(?:\s+{FILLER}){{0,4}}\s+{ACTION}", re.IGNORECASE)

# Step 3 (T28): "no refund please", "no cancellation needed", "no refund, thanks". The word before "no" must not make
# it a complaint ("still no refund", "got no refund"), and a request word after it keeps it a request
# ("no refund please help").
NO_WISH_RE = re.compile(rf"(?<!still )(?<!got )(?<!received )(?<!there is )(?<!there's )(?<!yet )"
                        rf"\bno\s+{ACTION},?\s+(?:please|pls|needed|necessary|required|wanted|thanks|thank\s+you)\b"
                        rf"(?!\s+(?:help|check|look|advise|fix|tell|explain|send|refund|reply))", re.IGNORECASE)


def negated_request(sentence: str | None) -> bool:
    """True when the sentence says the client does NOT want the action (see the two steps above)."""
    text = (sentence or "").replace("’", "'").replace("/", " ")   # "return/refund" -> two words
    text = REQUEST_RE.sub(" ", text)                                    # step 1: requests are not negations
    text = COMPLAINT_RE.sub(" ", text)                                  # step 1c (T14d): "not refunded till date"
    if NO_WISH_RE.search(text):                                         # step 3 (T28): "no refund please"
        return True
    return NEGATED_RE.search(text) is not None                          # step 2


# The marks that end a sentence (the same as in both Coordinators).
SENTENCE_ENDS = ".!?\n"


def money_back_asked(message: str | None) -> bool:
    """T14e (Atlas), T14f (ShopNova too): True when one sentence of the message asks for money back in the client's
    own words (request_words.asks_for_money_back) and that sentence is not a negative one ("I do not want a refund").
    One function for both companies' Coordinators, so a refund needs the same words at ShopNova and at Atlas."""
    from callverse.intake.request_words import asks_for_money_back   # here, so this file stays light to import
    text = (message or "").lower()
    for mark in SENTENCE_ENDS[1:]:
        text = text.replace(mark, SENTENCE_ENDS[0])
    return any(asks_for_money_back(s) and not negated_request(s) for s in text.split(SENTENCE_ENDS[0]))


# ---------- T28 (step 09): the confirmation of a bare "yes" ----------
# When the Coordinator asked "Please confirm that you want a refund of 59.90 TND for order 4512." and the client answers
# only "yes", the yes has no quote and no money-back words. So the checks of the FIRST message are made by code when the
# question is asked, and stored with it (flags). The yes then counts only if those flags allow this action.

def _sentences(message: str | None) -> list[str]:
    text = (message or "").lower()
    for mark in SENTENCE_ENDS[1:]:
        text = text.replace(mark, SENTENCE_ENDS[0])
    return [s for s in text.split(SENTENCE_ENDS[0]) if s.strip()]


def question_flags(message: str | None) -> dict:
    """The facts about the client's FIRST message that a later bare "yes" needs (all by code, no model):
    money_back  : the client's own money-back words, not negative (money_back_asked, T14f);
    negated     : a sentence says they do NOT want an action ("I don't want a refund", "no refund please");
    expenses    : they ask for costs around the trip (Atlas: a compensation question, not a refund);
    cancel_order: a non-negative sentence cancels the ORDER (ShopNova, request_words.cancels_order);
    cancel_any  : a non-negative sentence has a cancel word (Atlas hotel cancellation)."""
    from callverse.intake.request_words import CANCEL_WORD_RE, asks_for_expenses, cancels_order
    sentences = _sentences(message)
    lower = (message or "").lower()
    return {"money_back": money_back_asked(message),
            "negated": any(negated_request(s) for s in sentences),
            "expenses": any(asks_for_expenses(s) for s in sentences),
            "cancel_order": any(CANCEL_WORD_RE.search(s) and not negated_request(s) and cancels_order(s, lower)
                                for s in sentences),
            "cancel_any": any(CANCEL_WORD_RE.search(s) and not negated_request(s) for s in sentences)}


def yes_confirmation(action: str | None, flags: dict | None) -> tuple[bool, str]:
    """(confirmed, reason) for a bare "yes" to the Coordinator's question about this action, from the stored flags.
    A refund still needs the client's own money-back words in the first message (T14f): a "yes" alone never makes a
    refund out of a message that did not ask for money."""
    flags = flags or {}
    if action == "refund":
        ok = bool(flags.get("money_back")) and not flags.get("expenses")
        return ok, "yes + money-back words in the first message" if ok else "the first message did not ask for money back"
    if action == "cancel":
        ok = bool(flags.get("cancel_order"))
        return ok, "yes + the first message cancels the order" if ok else "the first message does not cancel the order"
    if action == "cancel_hotel":
        ok = bool(flags.get("cancel_any")) and not flags.get("expenses")
        return ok, "yes + the first message asks to cancel" if ok else "the first message does not ask to cancel"
    if action == "compensation":
        ok = not flags.get("negated")
        return ok, "yes to the compensation question" if ok else "the first message said no"
    if action == "subscribe":
        return True, "yes to the notification question"
    return False, f"a bare yes cannot confirm '{action}'"
