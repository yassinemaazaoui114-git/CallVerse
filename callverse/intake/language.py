"""Language of the client's message (T14b): "en", "fr", "es", "it", "de" or "ar". Plain code, no model, no new package.

Why: since T10 the reply writer does not see the client's text, so it lost the hint to answer in the client's language.
Intake already reads the text, so it also says the language, and the writer gets one prompt line when it is not English.

How: Arabic script is found by its letters. For the Latin languages we count stop-words (very common small words) of
each language; the language with the most hits wins, but only with at least MIN_HITS hits and strictly more than English.
When unsure the answer is "en" (the safe default: the writer's prompt is then unchanged).
"""

import re

MIN_HITS = 2   # one shared word ("a", "me", "no") is not enough to change the language

# Very common words per language. Words that are also common English words are left out ("a", "me", "no", "son", "pie"...).
STOP_WORDS = {
    "en": "the is are was were my i you your it this that and or not have has had with for to of in on at on be been "
          "when where what why how please order package parcel refund still".split(),
    "fr": "le la les un une des du de et est sont je j tu vous votre vos mon ma mes nous pas ne pour dans avec sur "
          "que qui ce cette commande colis bonjour merci toujours depuis reçu recu ai suis".split(),
    "es": "el los las un una unos unas del y es son yo mi mis tu su para con por que pedido paquete hola "
          "gracias todavía todavia aún aun recibido quiero estoy".split(),
    "it": "il lo gli le un uno una dei delle di del e è sono io mio mia mie non per con che nel nella ordine pacco "
          "ciao grazie ancora ricevuto voglio sto ho".split(),
    "de": "der die das ein eine einen und ist sind ich mein meine mir mich nicht für mit auf bei dass bestellung paket "
          "hallo danke noch immer erhalten möchte habe bin".split(),
}
STOP_SETS = {lang: set(words) for lang, words in STOP_WORDS.items()}
WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
ARABIC_RE = re.compile(r"[؀-ۿ]")   # the Arabic block


def detect(text: str | None) -> str:
    """The language code of a message; "en" when unsure."""
    text = text or ""
    letters = [c for c in text if c.isalpha()]
    if letters and len(ARABIC_RE.findall(text)) > len(letters) / 2:
        return "ar"
    words = [w.lower() for w in WORD_RE.findall(text)]
    hits = {lang: sum(w in stop for w in words) for lang, stop in STOP_SETS.items()}
    best = max((lang for lang in hits if lang != "en"), key=hits.get)
    return best if hits[best] >= MIN_HITS and hits[best] > hits["en"] else "en"
