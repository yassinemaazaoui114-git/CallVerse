"""The bridge between the web channel and CallVerse: handle_turn(session, text) -> reply.

Text and voice call the SAME function, so both channels get exactly the same answer and rules.

Two modes, never mixed:
- REAL: Agent A (Status & Tracking) answers with its read tools and the shared LLM (M2). Agent A is the
  only agent that exists today; the full chain (Intake -> Queues -> Agents -> Coordinator -> SLM) is not
  built yet. When it is, only real_reply() changes; the web app and the browser stay the same.
- MOCK: a fixed demo reply that says it is a demo. No agent, no LLM, no database read. It exists to test
  the speech features without an API key. A MOCK reply never looks like a real decision.

Identity guard (REAL only). Agent A can read ANY order, but a website visitor must only see their own.
So before an order is looked up, the customer must give the email of the account that owns it. This is
a check of the channel, done with the existing READ tools; it decides nothing about the order itself.
After the agent answers, we also check which orders and clients its tools touched: if it read anything
outside what this customer proved, the answer is withheld.
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
# Fixed texts of the channel (not agent answers)
# ---------------------------------------------------------------------------
TEXTS = {
    "en": {
        "ask_email": "To protect your account, please type the email address used for order {orders}.",
        "mismatch": "This email does not match our records for order {orders}. Please check the email "
                    "address and the order number.",
        "need_question": "Thank you, your identity is confirmed for order {orders}. How can I help you with it?",
        "blocked": "For your security, I can only share information about orders linked to your verified "
                   "email address.",
        "unavailable": "CallVerse is temporarily unavailable. Please try again in a moment.",
        "mock": "Demo mode: no CallVerse agent was called and no order data was read. I received your "
                "message{about}. In real mode, CallVerse first checks your identity, then Agent A "
                "(Status and Tracking) looks the order up with its read tools.",
        "about": " about order {orders}",
    },
    "fr": {
        "ask_email": "Pour protéger votre compte, veuillez écrire l'adresse e-mail utilisée pour la commande {orders}.",
        "mismatch": "Cette adresse e-mail ne correspond pas à nos données pour la commande {orders}. "
                    "Veuillez vérifier l'adresse et le numéro de commande.",
        "need_question": "Merci, votre identité est confirmée pour la commande {orders}. Comment puis-je vous aider ?",
        "blocked": "Pour votre sécurité, je ne peux donner des informations que sur les commandes liées à votre "
                   "adresse e-mail vérifiée.",
        "unavailable": "CallVerse est momentanément indisponible. Veuillez réessayer dans un instant.",
        "mock": "Mode démo : aucun agent CallVerse n'a été appelé et aucune donnée de commande n'a été lue. "
                "J'ai bien reçu votre message{about}. En mode réel, CallVerse vérifie d'abord votre identité, "
                "puis l'agent A (Suivi des commandes) consulte la commande avec ses outils de lecture.",
        "about": " concernant la commande {orders}",
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
# One turn
# ---------------------------------------------------------------------------
def _reply(mode: str, text: str, kind: str, lang: str, **extra) -> dict:
    """kind: what produced the text. "agent" = an agent's answer; "channel" = a fixed text of this
    channel (identity check, errors); "mock" = demo text."""
    return {"mode": mode, "text": text, "kind": kind, "language": lang, "agent": extra.pop("agent", None),
            "handover": extra.pop("handover", None), "tools_used": extra.pop("tools_used", []), **extra}


def mock_reply(session: Session, text: str, lang: str) -> dict:
    orders = find_order_ids(text)
    about = _text(lang, "about", orders=_orders_label(orders)) if orders else ""
    return _reply("mock", _text(lang, "mock", about=about), "mock", lang)


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


def _out_of_scope(session: Session, tool_calls: list[dict]) -> list[str]:
    """Tool calls of the agent that read an order or client the customer did not prove."""
    bad = []
    for call in tool_calls:
        args = call.get("args") or {}
        if call["tool"] in ("get_order", "get_tracking"):
            try:
                if int(args.get("order_id")) not in session.verified_orders:
                    bad.append(f"{call['tool']}({args.get('order_id')})")
            except (TypeError, ValueError):
                pass  # the tool itself refused bad arguments; nothing was read
        elif call["tool"] == "get_user":
            result = call.get("result") or {}
            if "error" not in result and result.get("id") != session.verified_user_id:
                bad.append("get_user")
    return bad


def real_reply(session: Session, text: str, lang: str, chat_fn=None) -> dict:
    from openai import APIError

    from callverse.agents.agent_a import AgentA
    from callverse.llm import AllModelsFailed

    orders = find_order_ids(text)
    email = find_email(text)

    # 1. Identity check: an email answers the pending question (or comes with the question itself).
    if email:
        to_check = list(dict.fromkeys(orders + session.pending_orders))
        if to_check:
            if not _verify(session, email, to_check):
                trace.log("identity", "web", {"result": "mismatch", "orders": to_check})
                return _reply("real", _text(lang, "mismatch", orders=_orders_label(to_check)), "channel", lang)
            trace.log("identity", "web", {"result": "verified", "orders": to_check})
            if session.pending_text and not orders:
                # The message was only the email: now answer the question that was waiting.
                text, session.pending_text, session.pending_orders = session.pending_text, None, []
            elif not orders and not session.pending_text:
                return _reply("real", _text(lang, "need_question", orders=_orders_label(to_check)), "channel", lang)
            session.pending_text, session.pending_orders = None, []
            orders = find_order_ids(text)

    # 2. An order the customer has not proved yet: ask for the email, call nothing.
    unproved = [o for o in orders if o not in session.verified_orders]
    if unproved:
        session.pending_text, session.pending_orders = text, unproved
        trace.log("identity", "web", {"result": "asked", "orders": unproved})
        return _reply("real", _text(lang, "ask_email", orders=_orders_label(unproved)), "channel", lang)

    # 3. The agent answers, with the conversation so far as context.
    try:
        result = AgentA(chat_fn=chat_fn).run(text, history=session.history)
    except (AllModelsFailed, APIError) as e:
        # AllModelsFailed: every model of the chain is down. APIError: e.g. a wrong key (401), which
        # llm.py does not treat as "try the next model". Either way the customer gets a clear message.
        trace.log("agent_unavailable", "web", {"error": type(e).__name__})
        return _reply("real", _text(lang, "unavailable"), "channel", lang, error="agent_unavailable")
    tools_used = [c["tool"] for c in result["tool_calls"]]

    # 4. Check what the agent read before showing its answer.
    bad = _out_of_scope(session, result["tool_calls"])
    if bad:
        trace.log("identity_block", "web", {"tool_calls": bad})
        return _reply("real", _text(lang, "blocked"), "channel", lang, tools_used=tools_used)

    handover = result.get("handover")
    extra = {"notice": "Agent B (Payment and Refund) is not built yet; the request was not forwarded."} \
        if handover else {}
    return _reply("real", result["answer"], "agent", lang, agent="A", handover=handover,
                  tools_used=tools_used, stopped_by=result["stopped_by"], **extra)


def handle_turn(session: Session, text: str, lang: str | None = None, channel: str = "text",
                mode: str | None = None, chat_fn=None) -> dict:
    """Process one customer message and return the reply to show AND speak.

    lang: "en"/"fr" (from the UI or speech-to-text); None = guessed from the words.
    """
    start = time.perf_counter()
    supported = load_config()["voice"]["languages"]
    lang = lang if lang in supported else guess_language(text)
    if lang not in supported:
        lang = "en"
    mode = mode or resolve_mode()

    reply = mock_reply(session, text, lang) if mode == "mock" else real_reply(session, text, lang, chat_fn)

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
