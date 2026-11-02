"""Reply styles (RL1, RL1b): HOW the writer says an already-decided reply. The style changes wording only.

The Coordinator's decision (outcome, amounts, rules, must_say) is never touched. RL1b: the three styles really differ:
  short           greeting + the decision (must_say + next step). Nothing else.
  warm            greeting + ONE empathy sentence written by the SLM about the client's own problem + the decision.
  warm_next_step  warm + ONE closing line chosen by code from the outcome (CLOSING_LINES, approved list).
The greeting ("Dear customer," or "Hello,") and the closing line are written by CODE, the same for every style; the model
only writes the empathy sentence (warm styles) and the decision text. The empathy sentence has its own small check
(empathy_problems): no number, no date, no promise, no decision. If it fails, the normal retry / template path is used.

How a style gets in: decision["reply_style"], else the env var CALLVERSE_REPLY_STYLE, else config.yaml
slm.reply_style (null = today's behaviour exactly). The RL policy (RL5) will set decision["reply_style"] later.
Not to be mixed up with decision["style"]: that one is Intake's profile of the client (formality, length, shouting...).
"""

import os
import re

# One entry per style, in plain words.
#   empathy: True = the reply starts (after the greeting) with one empathy sentence written by the SLM
#   closing: True = the reply ends with the closing line of CLOSING_LINES (by code), when the outcome has one
#   prompt:  what the model is told to write for this style (the greeting and the closing line are never asked from it)
REPLY_STYLES = {
    "short": {
        "empathy": False,
        "closing": False,
        "prompt": "Length: very short, at most 45 words. Write ONLY the decision: the sentences to copy and the next step. "
                  "Do NOT write a greeting, an apology, a sentence about the client's feelings or a closing sentence.",
    },
    "warm": {
        "empathy": True,
        "closing": False,
        "prompt": None,   # EMPATHY_PROMPT below
    },
    "warm_next_step": {
        "empathy": True,
        "closing": True,
        "prompt": None,   # EMPATHY_PROMPT below (the closing line is added by code after the model's text)
    },
}

# The example sentence of the warm prompt. RL1c: a reply that copies it word for word fails the empathy check (s02 had it
# for a damaged parcel: it was not about the client's own problem).
EMPATHY_EXAMPLE = "Waiting for a parcel that does not come is stressful."
EMPATHY_PROMPT = (
    "Length: at most 80 words. Do NOT write a greeting: it is added automatically.\n"
    "First write ONE short sentence that shows you understand the client's own problem, in plain words, taken from the "
    f"client's messages (for example: \"{EMPATHY_EXAMPLE}\"). That sentence must have "
    "no number, no date, no name, no promise and no decision: only the feeling about the problem.\n"
    "Then write the decision: the sentences to copy and the next step. Write no other apology and no closing sentence.")
# The last line of a warm prompt (instead of "Write the reply now."): qwen2.5:1.5b skipped the empathy sentence in most
# replies of the first RL1b run when it was only said in the middle of the prompt.
EMPATHY_LAST_LINE = ("Write the reply now. Your FIRST sentence says how the client feels about their problem "
                     "(no number, no promise). Then the sentences to copy.")

# RL1b: the closing line of warm_next_step, by outcome. Exact texts approved by the Brain / Yassine (task RL1b, step 1).
# A (outcome, action) that is not here gets NO closing line (ask_user, ask_proof, layer3_pending and send_back on purpose:
# their request or "we will reply" is already the last sentence).
CLOSING_REFUND = "If the money does not arrive, reply here and we will check it."
CLOSING_DECLINE = "If you think something is wrong, reply here with the details and we will check it."
CLOSING_INFO = "We will message you here if anything changes."
CANCEL_ACTIONS = ("cancel", "cancel_order", "cancel_hotel", "cancel_flight", "cancel_booking")


def closing_line(decision: dict) -> str | None:
    """The closing line for this decision's outcome (warm_next_step), or None (no line)."""
    outcome, action = decision.get("outcome"), decision.get("action")
    if outcome == "approve" and action == "refund":
        return CLOSING_REFUND
    if outcome == "approve" and action in CANCEL_ACTIONS:
        word = decision.get("case_word") or "order"   # Atlas says "booking"
        return f"If you need anything else for this {word}, reply here."
    if outcome == "decline":
        return CLOSING_DECLINE
    if outcome == "info" and action == "status":
        return CLOSING_INFO
    return None


def greeting(decision: dict) -> str:
    """RL1b (Q3): the same greeting for all 3 styles, by code: "Dear customer," for a formal client, else "Hello,"."""
    return "Dear customer," if (decision.get("style") or {}).get("formality") == "formal" else "Hello,"


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


def prompt_for(name: str) -> str:
    """The style lines the model is given for this style."""
    return REPLY_STYLES[name]["prompt"] or EMPATHY_PROMPT


# --- the empathy sentence check (warm styles) ---------------------------------------------------------------

# No promise ("we will", "soon", "make sure"), no date or time word, no decision word ("approved", "refused").
# Naming the problem in plain words is allowed ("Not getting your money back is frustrating.").
EMPATHY_FORBIDDEN_RE = re.compile(
    r"\b(?:will|shall|won't|going to|promise\w*|guarantee\w*|ensure|make sure|soon|asap|right away|immediately|"
    r"quickly|today|tomorrow|tonight|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"january|february|march|april|june|july|august|september|october|november|december|"
    r"approved|declined|refused|rejected|granted|processed|confirmed|"
    r"compensation|voucher|discount)\b|'ll\b",
    re.IGNORECASE)
EMPATHY_MAX_WORDS = 25
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def empathy_problems(sentence: str, decision: dict) -> list[str]:
    """Problems of the empathy sentence (empty list = fine). The rule check (check.py) still runs on the whole reply."""
    s = (sentence or "").strip()
    low = " ".join(s.lower().split())
    if not s:
        return ["the empathy sentence is missing: start with one sentence about the client's problem"]
    problems = []
    if re.search(r"\d", s):
        problems.append(f'the first sentence must have no number: "{s}"')
    if m := EMPATHY_FORBIDDEN_RE.search(s):
        problems.append(f"the first sentence must have no promise, date or decision: '{m.group(0)}'")
    if any(" ".join(str(x).lower().split()) in low for x in decision.get("must_say") or [] if str(x).strip()):
        problems.append("the first sentence must be one sentence about the client's feelings, before the sentences to copy")
    if re.search(r"\b(?:the|this|our) (?:client|customer)\b|^thank", low):
        problems.append("the first sentence must speak to the client about their problem (not 'the client', not a thank-you)")
    if _key(EMPATHY_EXAMPLE) in _key(s):
        problems.append("the first sentence copies the example of the instructions: write about this client's own problem")
    if len(s.split()) > EMPATHY_MAX_WORDS:
        problems.append(f"the first sentence is too long ({len(s.split())} words, max {EMPATHY_MAX_WORDS})")
    return problems


def _key(sentence: str) -> str:
    """Lower case, no punctuation: to compare two sentences."""
    return " ".join(re.sub(r"[^\w\s]", " ", sentence.lower()).split())


def put_last(text: str, closing: str) -> str:
    """End the text with the closing sentence, once: an earlier copy of it (same sentence) is removed first."""
    closing = closing.strip()
    if closing and closing[-1] not in ".!?":
        closing += "."
    kept = [s for s in SENTENCE_SPLIT_RE.split(text.strip()) if s and _key(s) != _key(closing)]
    return " ".join(kept + [closing]).strip()
