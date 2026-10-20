"""The bridge between the web channel and CallVerse: handle_turn(session, text) -> reply.

Text and voice call the SAME function, so both channels get exactly the same answer and rules.

1. Identity gate (this file): a website visitor must only see their own orders. When a message names an
   order, the customer must first give the email of the account that owns it, checked with the READ tools.
   It decides nothing about the order itself.
2. The unified workflow (callverse/integration/workflow.py): Intake -> Router -> agent -> Coordinator ->
   response writer, each stage marked real / interim / mock / not built in the reply's `steps`.

Modes: REAL = the LLM agents run (needs GROQ_API_KEY). MOCK = everything runs for real EXCEPT the LLM agent,
whose answer is replaced by a labelled demo text; a MOCK reply never looks like a real decision.
"""

import re
import time

from callverse import trace
from callverse.config import load_config
from callverse.web.sessions import Session

# ---------------------------------------------------------------------------
# Reading order numbers and emails in a message (typed or transcribed)
# ---------------------------------------------------------------------------
# Speech-to-text often writes "4512" as "4,512" (English) or "4.512" / "4 512" (French).
_THOUSANDS = re.compile(r"(?<![\d.,])(\d{1,3})[,.   ](\d{3})(?![\d]|[.,]\d)")
_ORDER = re.compile(r"(?<![\d.,/+-])#?(\d{4,6})(?![\d]|[.,/-]\d)")
_CURRENCY_AFTER = re.compile(r"^\s*(tnd|dt|dinars?|eur|euros?|€|\$)", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


# A number read digit by digit or in pairs comes back as "4, 5, 1, 2" or "45 12".
# (Not "-": "10-09" is usually a date.)
_DIGIT_GROUPS = re.compile(r"(?<![\d.,/-])(\d{1,2}(?:(?:,\s*|\s+)\d{1,2}){1,5})(?![\d]|[.,/-]\d)")


def _join_groups(m: re.Match) -> str:
    digits = re.sub(r"\D", "", m.group(1))
    return digits if 4 <= len(digits) <= 6 else m.group(1)


def normalize_numbers(text: str) -> str:
    """'order 4,512' / '4, 5, 1, 2' / '45 12' -> 'order 4512'. Amounts (59.90) and dates are left alone.

    A wrong join can only make the identity check ask for an email about an order that does not match,
    so it never reveals data; that is why this simple rule is good enough.
    """
    text = _THOUSANDS.sub(lambda m: m.group(1) + m.group(2), text)
    return _DIGIT_GROUPS.sub(_join_groups, text)


def find_order_ids(text: str) -> list[int]:
    """Order numbers (4-6 digits) in the text, without amounts ('1500 TND'). First seen first, no repeats."""
    text = normalize_numbers(text)
    found = []
    for m in _ORDER.finditer(text):
        if _CURRENCY_AFTER.match(text[m.end():]):
            continue
        number = int(m.group(1))
        if number not in found:
            found.append(number)
    return found


def find_email(text: str) -> str | None:
    m = _EMAIL.search(text)
    return m.group(0).lower() if m else None


_FRENCH_WORDS = {"bonjour", "commande", "est", "où", "ou", "ma", "mon", "mes", "je", "vous", "suis", "pas",
                 "colis", "livraison", "remboursement", "merci", "le", "la", "les", "une", "des", "pour", "retard"}
_ENGLISH_WORDS = {"hello", "hi", "order", "where", "is", "my", "the", "i", "you", "refund", "please", "late",
                  "delivery", "package", "thanks", "what", "when", "a", "and", "it"}


def guess_language(text: str) -> str:
    """'fr' or 'en' from common words (only for typed messages; speech-to-text detects the language itself)."""
    words = re.findall(r"[a-zàâçéèêëîïôûùüÿœ']+", text.lower())
    fr = sum(w in _FRENCH_WORDS for w in words)
    en = sum(w in _ENGLISH_WORDS for w in words)
    return "fr" if fr > en else "en"


# ---------------------------------------------------------------------------
# Fixed texts of the identity gate (not agent answers)
# ---------------------------------------------------------------------------
TEXTS = {
    "en": {
        "ask_email": "To protect your account, please type the email address used for order {orders}.",
        "mismatch": "This email does not match our records for order {orders}. Please check the email "
                    "address and the order number.",
        "need_question": "Thank you, your identity is confirmed for order {orders}. How can I help you with it?",
    },
    "fr": {
        "ask_email": "Pour protéger votre compte, veuillez écrire l'adresse e-mail utilisée pour la commande {orders}.",
        "mismatch": "Cette adresse e-mail ne correspond pas à nos données pour la commande {orders}. "
                    "Veuillez vérifier l'adresse et le numéro de commande.",
        "need_question": "Merci, votre identité est confirmée pour la commande {orders}. Comment puis-je vous aider ?",
    },
}


def _text(lang: str, key: str, **kw) -> str:
    return TEXTS.get(lang, TEXTS["en"])[key].format(**kw)


def _orders_label(orders: list[int]) -> str:
    return ", ".join(str(o) for o in orders)


# ---------------------------------------------------------------------------
# Mode
# ---------------------------------------------------------------------------
def resolve_mode() -> str:
    """'real' or 'mock' from config.yaml voice.mode (auto = real only when the agents' API key is set)."""
    import os

    from callverse import llm  # noqa: F401  (importing llm loads .env, where the key lives)

    mode = load_config()["voice"]["mode"]
    if mode in ("real", "mock"):
        return mode
    cfg = load_config()
    first = cfg["models"]["agents"][0]
    return "real" if os.getenv(cfg["providers"][first["provider"]]["key_env"]) else "mock"


# ---------------------------------------------------------------------------
# Identity gate
# ---------------------------------------------------------------------------
def _gate_reply(mode: str, text: str, lang: str) -> dict:
    step = {"name": "identity", "status": "real", "detail": {"result": "waiting for the email"}}
    return {"mode": mode, "text": text, "kind": "channel", "language": lang, "agent": None, "handover": None,
            "tools_used": [], "steps": [step]}


def _verify(session: Session, email: str, orders: list[int]) -> bool:
    """True if every order in `orders` belongs to the client with this email (read tools only)."""
    from callverse.tools.shopnova_tools import get_order, get_user

    user = get_user(email=email)
    trace.log("tool_call", "web_identity", {"tool": "get_user", "args": {"email": email},
                                            "found": "error" not in user})
    if "error" in user:
        return False
    for order_id in orders:
        order = get_order(order_id)
        trace.log("tool_call", "web_identity", {"tool": "get_order", "args": {"order_id": order_id},
                                                "found": "error" not in order})
        if "error" in order or order["user_id"] != user["id"]:
            return False
    session.verified_user_id = user["id"]
    session.verified_orders.update(orders)
    return True


def identity_gate(session: Session, text: str, lang: str, mode: str) -> tuple[str, dict | None]:
    """Return (text to process, None) when the turn may go on, or (text, reply) when the gate answers itself."""
    orders = find_order_ids(text)
    email = find_email(text)

    # An email answers the pending question (or comes with the question itself).
    if email:
        to_check = list(dict.fromkeys(orders + session.pending_orders))
        if to_check:
            if not _verify(session, email, to_check):
                trace.log("identity", "web", {"result": "mismatch", "orders": to_check})
                return text, _gate_reply(mode, _text(lang, "mismatch", orders=_orders_label(to_check)), lang)
            trace.log("identity", "web", {"result": "verified", "orders": to_check})
            if session.pending_text and not orders:
                # The message was only the email: now answer the question that was waiting.
                text = session.pending_text
            elif not orders and not session.pending_text:
                return text, _gate_reply(mode, _text(lang, "need_question", orders=_orders_label(to_check)), lang)
            session.pending_text, session.pending_orders = None, []
            orders = find_order_ids(text)

    # An order the customer has not proved yet: ask for the email, nothing else runs.
    unproved = [o for o in orders if o not in session.verified_orders]
    if unproved:
        session.pending_text, session.pending_orders = text, unproved
        trace.log("identity", "web", {"result": "asked", "orders": unproved})
        return text, _gate_reply(mode, _text(lang, "ask_email", orders=_orders_label(unproved)), lang)
    return text, None


# ---------------------------------------------------------------------------
# One turn
# ---------------------------------------------------------------------------
def handle_turn(session: Session, text: str, lang: str | None = None, channel: str = "text",
                mode: str | None = None, chat_fn=None) -> dict:
    """Process one customer message and return the reply to show AND speak.

    lang: "en"/"fr" (from the UI or speech-to-text); None = guessed from the words.
    """
    from callverse.integration import workflow

    start = time.perf_counter()
    supported = load_config()["voice"]["languages"]
    lang = lang if lang in supported else guess_language(text)
    if lang not in supported:
        lang = "en"
    mode = mode or resolve_mode()

    question, reply = identity_gate(session, text, lang, mode)
    if reply is None:
        reply = workflow.run(session, question, lang, mode, chat_fn=chat_fn)

    # Conversation context for the next turns: only what the customer said and what was shown.
    max_turns = load_config()["voice"]["limits"]["max_history_turns"]
    session.history += [{"role": "user", "content": text}, {"role": "assistant", "content": reply["text"]}]
    session.history = session.history[-2 * max_turns:]
    session.turns += 1

    reply["seconds"] = round(time.perf_counter() - start, 3)
    trace.log("web_turn", "web", {"channel": channel, "mode": reply["mode"], "kind": reply["kind"],
                                  "language": lang, "input": text, "output": reply["text"],
                                  "tools_used": reply["tools_used"], "seconds": reply["seconds"]})
    return reply
