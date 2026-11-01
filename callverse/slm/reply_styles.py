"""Reply styles (RL1): HOW the writer says an already-decided reply. The style changes wording only.

The Coordinator's decision (outcome, amounts, rules, must_say) is never touched. A style only says
whether the reply apologises, how long it is, and whether it ends with a next-step sentence.
The parts that must be exact (the apology opener, the closing sentence) are written by CODE, like the
calm opener since T05b; the model only writes the middle.

How a style gets in: decision["reply_style"], else the env var CALLVERSE_REPLY_STYLE, else config.yaml
slm.reply_style (null = today's behaviour exactly). The RL policy (RL5) will set decision["reply_style"] later.
Not to be mixed up with decision["style"]: that one is Intake's profile of the client (formality, length, shouting...).
"""

import os
import re

# One entry per style, in plain words.
#   apology: "never"  = no apology and no calm opener at all
#            "always" = the calm opener (config.yaml slm.calm_openers) comes first, even for a calm client
#   closing: True = the reply ends with ONE closing sentence written by code
#   length:  the length line the model is given (instead of Intake's length)
REPLY_STYLES = {
    "short": {
        "apology": "never",
        "closing": False,
        "length": "Very short: 2 or 3 sentences, at most 45 words. Say the decision and the next step only. "
                  "Do NOT apologise and do NOT write a calming sentence.",
    },
    "apology_first": {
        "apology": "always",
        "closing": False,
        "length": "Clear: 3 to 5 sentences, at most 80 words.",
    },
    "apology_next_step": {
        "apology": "always",
        "closing": True,
        "length": "Clear: 3 to 5 sentences, at most 80 words. Do NOT write the final next-step sentence: "
                  "it is added after your text automatically.",
    },
}

# Closing sentence when the decision has no next_step and no question/request in must_say. It invites a reply;
# it promises nothing (the rule check has a list of forbidden promises: this line passes it).
FIXED_CLOSING = "You can reply here if you have a question."

# Outcomes whose must_say sentence IS the next step (a question or a request to the client).
ASK_OUTCOMES = ("ask_user", "ask_proof")

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
GREETING_WORDS_RE = re.compile(r"^(?:(?:hi|hello|hey|dear customer)\s+)+")


def of(decision: dict) -> str | None:
    """The reply style for this decision, or None (= today's behaviour). An unknown name is an error, not a silent default."""
    name = decision.get("reply_style")
    if name is None:
        name = os.environ.get("CALLVERSE_REPLY_STYLE") or None
    if name is None:
        from callverse.config import load_config   # local import: config is read only when no style is set on the decision
        name = load_config().get("slm", {}).get("reply_style")
    if name is not None and name not in REPLY_STYLES:
        raise ValueError(f"unknown reply_style {name!r}: use one of {sorted(REPLY_STYLES)} or None")
    return name


def closing_for(decision: dict) -> str:
    """The closing sentence of apology_next_step: the next step if there is one, else the request/question in must_say
    (ask_user / ask_proof), else the fixed line."""
    next_step = str(decision.get("next_step") or "").strip()
    if next_step:
        return next_step
    must_say = [str(x).strip() for x in decision.get("must_say") or [] if str(x).strip()]
    if decision.get("outcome") in ASK_OUTCOMES and must_say:
        return must_say[-1]
    return FIXED_CLOSING


def _key(sentence: str) -> str:
    """Lower case, no punctuation, no greeting: to compare two sentences."""
    s = " ".join(re.sub(r"[^\w\s]", " ", sentence.lower()).split())
    return GREETING_WORDS_RE.sub("", s + " ").strip()


def put_last(text: str, closing: str) -> str:
    """End the text with the closing sentence, once: an earlier copy of it (same sentence) is removed first."""
    closing = closing.strip()
    if closing and closing[-1] not in ".!?":
        closing += "."
    kept = [s for s in SENTENCE_SPLIT_RE.split(text.strip()) if s and _key(s) != _key(closing)]
    return " ".join(kept + [closing]).strip()
