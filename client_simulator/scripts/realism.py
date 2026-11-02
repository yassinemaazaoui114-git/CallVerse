"""Realism profile of customer messages (used for real data in Phase 2 and model output in Phase 3),
plus the documented keyword rules that map a message to ShopNova / Atlas contact reasons."""
import re

import emoji
import numpy as np
from spellchecker import SpellChecker

_SPELL = SpellChecker()
_PLACEHOLDER = re.compile(r"<[A-Z_]+>")
_WORD = re.compile(r"[A-Za-z][A-Za-z']*")
# brand / domain words pyspellchecker does not know; they are not spelling errors
IGNORE = {w.lower() for w in """
amazon ups usps fedex dhl argos ebay target walmart delta americanair southwest jetblue alaska british airways
virgin atlantic airasia gwr airbnb shopnova atlas prime kindle alexa wifi app apps ok okay pls plz thx dm dms
lol omg btw tbh asap fyi bk eur usd gbp hrs mins im ive dont cant wont didnt doesnt isnt wasnt havent hasnt
youre theyre thats whats ill id hes shes lets aint gonna wanna gotta email emails online customer refund refunded
""".split()}
# common acronyms that are not "shouting"
ACRONYMS = {"I", "OK", "UK", "US", "USA", "EU", "UPS", "USPS", "DHL", "BA", "AA", "DM", "DMS", "ID", "PIN", "SMS",
            "TV", "PC", "GPS", "ETA", "ASAP", "FYI", "LOL", "OMG", "EUR", "USD", "GBP", "NYC", "LAX", "JFK", "LHR",
            "ATL", "PM", "AM", "BK", "PDF", "FAQ", "CEO", "TSA", "MCO", "DFW", "ORD", "SFO", "LGA", "IT", "HR", "API"}

SHOPNOVA_RULES = [  # (label, regex) - first match is the primary reason; all matches count for "several reasons"
    ("damaged_item", r"damag|broken|broke\b|crack|smash|defective|faulty|\bdent|shattered|torn|leak|stopped working|not working|doesn'?t work|does not work"),
    ("refund_request", r"refund|money back|reimburs|charged (me )?twice|double charged|overcharg|chargeback|been charged|charged (me )?for"),
    ("return_item", r"\breturn|exchange|send (it|them) back|wrong (item|size|product|order)|replacement"),
    ("late_delivery", r"\blate\b|delay|still (not|hasn'?t|haven'?t)|(hasn'?t|haven'?t|never|not yet) (arrived|been delivered|come|received|turned up|shown up)|missed delivery|overdue|was due|supposed to (arrive|be delivered)|stuck in transit|waiting (on|for) (my|the|a) (package|parcel|order|delivery|item)|lost (my )?(package|parcel|order)|been waiting"),
    ("order_status", r"track|status|where('?s| is|.{0,12}is) my|when will (my|it|i)|shipped|dispatch|out for delivery|order (number|#)|delivery date|my (order|package|parcel)"),
]
ATLAS_RULES = [
    ("special_assistance", r"wheelchair|disab|special assistance|assistance|mobility|blind|deaf|medical|pregnan|infant|stroller|service (dog|animal)|unaccompanied"),
    ("refund_request", r"refund|money back|reimburs|compensat|voucher|charged"),
    ("cancellation", r"cancel"),
    ("rebooking", r"rebook|re-book|change (my|the) (flight|booking|ticket|reservation)|reschedul|standby|earlier flight|later flight|another flight|different flight|switch (my )?flight|missed (my )?connect"),
    ("delay_disruption", r"delay|late\b|stuck|stranded|diverted|turned around|on the tarmac|been waiting|grounded|weather|missed (my|the) (flight|train|connection)|schedule change|gate (closed|change)"),
    ("booking_status", r"booking|reservation|confirm|seat|itinerary|check.?in|ticket|upgrade|boarding pass|my trip"),
]


def map_reason(text, company):
    rules = SHOPNOVA_RULES if company == "shopnova" else ATLAS_RULES
    t = text.lower().replace("’", "'")
    hits = [lab for lab, rx in rules if re.search(rx, t)]
    return (hits[0] if hits else "other"), hits


def is_english(text, min_known=0.6):
    """Heuristic language filter: share of words known to the English spell checker."""
    ws = [w.lower() for w in _WORD.findall(clean_for_profile(text)) if len(w) > 1]
    if len(ws) < 2:
        return False
    ws = set(ws)
    return len(_SPELL.known(ws)) / len(ws) >= min_known


def clean_for_profile(text):
    t = _PLACEHOLDER.sub(" ", text)
    return re.sub(r"\s+", " ", t).strip()


def message_features(text, company=None):
    t = clean_for_profile(text)
    words = t.split()
    alpha = [w for w in _WORD.findall(t)]
    check = [w.lower().strip("'") for w in alpha if w.lower().strip("'") not in IGNORE and len(w) > 1
             and not (w[0].isupper() and w[1:].islower())  # skip Capitalised words (names, places, brands)
             and not w.isupper()]  # skip ALL-CAPS tokens (airport codes, acronyms)
    misspelled = _SPELL.unknown(check) if check else set()
    letters = [c for c in t if c.isalpha()]
    caps_words = [w for w in alpha if len(w) >= 3 and w.isupper() and w not in ACRONYMS]
    f = {
        "words": len(words),
        "has_spelling_error": len(misspelled) > 0,
        "all_lowercase": bool(letters) and all(c.islower() for c in letters),
        "has_exclaim": "!" in t,
        "has_question": "?" in t,
        "has_caps_word": len(caps_words) > 0,
        "has_emoji": emoji.emoji_count(t) > 0,
    }
    if company:
        f["several_reasons"] = len(map_reason(t, company)[1]) >= 2
    return f


PROFILE_KEYS = ["words_median", "words_iqr", "share_spelling_error", "share_all_lowercase", "share_exclaim",
                "share_question", "share_caps_word", "share_emoji", "share_several_reasons"]


def profile(texts, companies=None):
    """Aggregate realism profile over a list of messages."""
    companies = companies or [None] * len(texts)
    fs = [message_features(t, c) for t, c in zip(texts, companies)]
    if not fs:
        return {}
    w = np.array([f["words"] for f in fs])
    q1, q3 = np.percentile(w, [25, 75])
    p = {
        "n": len(fs), "words_median": float(np.median(w)), "words_q1": float(q1), "words_q3": float(q3),
        "words_iqr": float(q3 - q1),
        "share_spelling_error": float(np.mean([f["has_spelling_error"] for f in fs])),
        "share_all_lowercase": float(np.mean([f["all_lowercase"] for f in fs])),
        "share_exclaim": float(np.mean([f["has_exclaim"] for f in fs])),
        "share_question": float(np.mean([f["has_question"] for f in fs])),
        "share_caps_word": float(np.mean([f["has_caps_word"] for f in fs])),
        "share_emoji": float(np.mean([f["has_emoji"] for f in fs])),
    }
    sr = [f["several_reasons"] for f in fs if "several_reasons" in f]
    p["share_several_reasons"] = float(np.mean(sr)) if sr else None
    return p


def realism_distance(p_model, p_real):
    """Mean absolute gap over the shares, plus the median-length gap scaled by the real IQR (capped at 1).
    0 = identical profile; larger = less realistic. Every component is in [0, 1]."""
    parts = {}
    for k in PROFILE_KEYS:
        if k in ("words_median", "words_iqr"):
            continue
        if p_model.get(k) is None or p_real.get(k) is None:
            continue
        parts[k] = abs(p_model[k] - p_real[k])
    scale = max(p_real["words_iqr"], 1.0)
    parts["length"] = min(abs(p_model["words_median"] - p_real["words_median"]) / scale, 1.0)
    return float(np.mean(list(parts.values()))), parts
