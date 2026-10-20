"""Style profile of the client's message: HOW they write (not what they want).

Later, the reply writer (SLM) can answer in a matching tone: formal to a formal client, short to a
short message, extra calm to someone shouting. Simple, readable rules are enough here; no model needed.
"""

import re

# Words that show a formal or a casual tone (lower case). A message is formal/casual when it has more
# markers of one kind than of the other; otherwise neutral.
FORMAL_MARKERS = ["dear", "sir", "madam", "kindly", "regards", "sincerely", "i would like",
                  "could you please", "would you please", "thank you in advance", "please find"]
# ("hi" / "hello" are NOT casual markers: almost every message starts with them.)
CASUAL_MARKERS = ["hey", "lol", "pls", "plz", "thx", "thanks!", "gonna", "wanna", "u ", "ur ",
                  "asap", "btw", "omg", "ok", "yo", "guys", ":)", ":("]

# Message length in words.
SHORT_MAX_WORDS = 15     # up to 15 words = short
MEDIUM_MAX_WORDS = 50    # 16 to 50 words = medium, more = long

# Shouting = writing in capitals. Common abbreviations are not shouting.
ABBREVIATIONS = {"TND", "DT", "DHL", "SMS", "OK", "ID", "USB", "FAQ", "ASAP"}


def _count_markers(text: str, markers: list[str]) -> int:
    """How many markers appear as whole words/phrases ("hi" in "this" does not count)."""
    padded = f" {text.lower()} "
    return sum(1 for m in markers if re.search(rf"(?<!\w){re.escape(m.strip())}(?!\w)", padded))


def formality(text: str) -> str:
    formal = _count_markers(text, FORMAL_MARKERS)
    casual = _count_markers(text, CASUAL_MARKERS)
    if formal > casual:
        return "formal"
    if casual > formal:
        return "casual"
    return "neutral"


def length(text: str) -> str:
    words = len(text.split())
    if words <= SHORT_MAX_WORDS:
        return "short"
    if words <= MEDIUM_MAX_WORDS:
        return "medium"
    return "long"


def is_shouting(text: str) -> bool:
    """Shouting when at least 2 words of 3+ letters are fully in capitals (abbreviations excluded),
    or when more than half of all letters are capitals (with at least 10 letters)."""
    caps_words = [w for w in re.findall(r"[A-Za-z]{3,}", text) if w.isupper() and w not in ABBREVIATIONS]
    letters = [c for c in text if c.isalpha()]
    caps_ratio = sum(c.isupper() for c in letters) / len(letters) if letters else 0.0
    return len(caps_words) >= 2 or (len(letters) >= 10 and caps_ratio > 0.5)


def profile(text: str) -> dict:
    """{"formality", "length", "exclamation" (bool), "exclamation_count", "shouting" (bool)}."""
    count = text.count("!")
    return {"formality": formality(text), "length": length(text),
            "exclamation": count > 0, "exclamation_count": count, "shouting": is_shouting(text)}
