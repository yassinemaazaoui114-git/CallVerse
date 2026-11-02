"""Conversation memory (T28, step 09): what CallVerse remembers INSIDE one conversation (one ticket of one user).

Design note: docs/step09_design.md. Three small jobs, all plain code (no model decides anything from memory):

1. The earlier order / booking id. "And what about it?" names no order. If the message refers back (it, that, the
   order ...), the newest id the USER typed in the last HISTORY_SIZE messages of this ticket is used. The channel then
   checks it like a typed one (identity check: it must be this user's). Assistant texts are never read.
2. The ONE pending question. When a turn ends with "Please confirm ..." (the Coordinator's ask_user on a recorded
   proposal of A, B or C), a row is saved in the tickets DB (store.pending_questions) with the proposal id and flags
   computed by code from that first message (negation.question_flags: money-back words, negative, ...). It ends at
   the next user message, or after EXPIRY_MINUTES.
   A bare "yes" to a question of A or B: resume() reads the proposal back from the company DB (by id: the amount and
   the order come from there, never from a text) and sends a copy through the NORMAL Coordinator (all checks, Layer 3,
   the write). A bare "no": the question is closed and nothing changes.
3. Several requests in one message: one decision per message (split_requests / other_parts_sentences). Two or more
   different ids = several requests; the money one goes through the pipeline, the others get one sentence by code.
"""

import re
from datetime import datetime, timedelta

from callverse import companies, pipeline, trace
from callverse.coordinator.coordinator import new_case, status_words
from callverse.coordinator.negation import question_flags
from callverse.intake import extract
from callverse.intake.request_words import CANCEL_WORD_RE, asks_for_money_back
from callverse.tickets import store

HISTORY_SIZE = 6       # the last 6 messages of the ticket (user and assistant; only the user's are read for ids)
EXPIRY_MINUTES = 30    # a pending question older than this is not answered by a bare yes / no

# A bare answer = the whole message, without punctuation, is one of these. Intake knows no French or Arabic yes words
# today, so none are added (task T28 step 4: "if any").
YES_WORDS = {"yes", "yeah", "yep", "yup", "y", "ok", "okay", "sure", "confirm", "i confirm", "confirmed", "please do",
             "yes please", "yes please do", "go ahead", "yes go ahead", "do it", "yes i confirm",
             "yes thanks", "yes thank you", "ok please", "okay please", "sure please"}
NO_WORDS = {"no", "nope", "nah", "n", "cancel", "no thanks", "no thank you", "never mind", "nevermind",
            "no never mind", "dont", "don't", "do not", "no dont", "no don't", "stop", "forget it"}

CLOSED_REPLY = "Okay, I will not change anything. Is there anything else I can help you with?"
ONE_DECISION_SENTENCE = ("Please send your request about {word} {order_id} as a new message: I can handle one decision "
                         "per message.")
NOT_YOURS_SENTENCE = "{Word} {order_id} is not on your account."

# Words that point back to something said before (an order, a booking, a parcel).
REFERS_BACK_RE = re.compile(r"\b(?:it|its|it's|that|this|same|them|they|the (?:order|booking|package|parcel|item|"
                            r"refund|flight|hotel|reservation)|my (?:order|booking|package|parcel|refund|flight|hotel|"
                            r"reservation))\b", re.IGNORECASE)

# Questions a bare yes can continue through the Coordinator (A's or B's proposal), per company.
RESUMABLE = {"shopnova": ("refund", "cancel", "subscribe"), "atlas": ("refund", "compensation", "cancel_hotel")}
C_ACTIONS = {"shopnova": ("replace", "hold", "assistance"), "atlas": ("rebook", "assistance")}


def _words(text: str) -> str:
    """Lower case, no punctuation, single spaces ("Yes, please!" -> "yes please")."""
    return " ".join(re.sub(r"[^\w\s']", " ", (text or "").lower().replace("’", "'")).split())


def bare_answer(text: str) -> str | None:
    """"yes" or "no" when the message is ONLY a yes / no word (see the lists), else None."""
    words = _words(text)
    if words in YES_WORDS:
        return "yes"
    if words in NO_WORDS:
        return "no"
    return None


# ---------- 1. the earlier order / booking id ----------

def refers_back(text: str) -> bool:
    return bool(REFERS_BACK_RE.search(text or ""))


def earlier_order_id(ticket_id: str, company: str, before_message_id: int | None = None) -> int | None:
    """The newest order / booking id the USER typed in the last HISTORY_SIZE messages of this ticket (before
    before_message_id = the message being handled), or None. The caller checks that it is this user's."""
    history = [m for m in store.messages(ticket_id) if before_message_id is None or m["id"] < before_message_id]
    for message in reversed(history[-HISTORY_SIZE:]):
        if message["sender"] != "user":
            continue
        found = extract.extract(message["text"], company)["order_id"]
        if found is not None:
            return found
    return None


# ---------- 2. the pending question ----------

def _age_minutes(question: dict, now: datetime | None) -> float:
    created = datetime.fromisoformat(question["created_real"])
    return ((now or datetime.now()) - created) / timedelta(minutes=1)


def open_question(ticket_id: str, user_id: int, company: str, now: datetime | None = None) -> dict | None:
    """The ticket's open question if it may be answered now: same user, same company, at most EXPIRY_MINUTES old
    (an older one is marked expired). None otherwise."""
    question = store.open_pending_question(ticket_id)
    if question is None or question["user_id"] != int(user_id) or question["company"] != company:
        return None
    if _age_minutes(question, now) > EXPIRY_MINUTES:
        store.end_pending_question(question["id"], "expired")
        trace.log("pending_question", "channel", {"ticket_id": ticket_id, "question_id": question["id"],
                                                   "status": "expired"})
        return None
    return question


def end_question(question: dict, status: str) -> bool:
    """Close the open question (used / closed / cleared). False if another message already did it."""
    ended = store.end_pending_question(question["id"], status)
    trace.log("pending_question", "channel", {"ticket_id": question["ticket_id"], "question_id": question["id"],
                                               "status": status if ended else f"{status}: already ended"})
    return ended


def remember_question(ticket_id: str, user_id: int, company: str, decision: dict, lead: str | None,
                      intake_ticket: dict, message_id: int | None) -> dict | None:
    """Save the question when this turn ended with ask_user on a recorded proposal (A or B: a resumable action;
    C: its offer). The flags come from the client's message by code. Returns the row, or None (nothing asked)."""
    action = decision.get("action")
    if decision.get("outcome") != "ask_user" or not decision.get("proposal_id"):
        return None
    if action in C_ACTIONS.get(company, ()):
        asked_by = "C"
    elif action in RESUMABLE.get(company, ()):
        asked_by = lead if lead in ("A", "B") else "B"
    else:
        return None
    flags = question_flags(intake_ticket.get("text"))
    row = store.add_pending_question(ticket_id, user_id, company, asked_by, decision.get("order_id"),
                                     decision.get("booking_type") or intake_ticket.get("booking_type"),
                                     decision["proposal_id"], action, intake_ticket.get("main_reason"), flags,
                                     message_id)
    trace.log("pending_question", "channel", {"ticket_id": ticket_id, "question_id": row["id"], "status": "open",
                                               "asked_by": asked_by, "action": action, "proposal_id": row["proposal_id"],
                                               "order_id": row["order_id"], "flags": flags})
    return row


def _company_writes(company: str):
    if company == "atlas":
        from callverse.data.atlas import writes
    else:
        from callverse.data import writes
    return writes


def resume(question: dict, text: str, ticket_id: str, slm_chat_fn=None) -> dict:
    """A bare "yes" to A's or B's question: the stored proposal goes through the normal Coordinator once more, as a
    NEW proposal with user_confirmed true (a decided proposal is never decided twice). The case carries the stored
    flags (yes_answer): the Coordinator's confirmation step uses them, every other check is the same.
    Returns {"ticket", "decision" (said to the user), "final_reply", "reply_source"}."""
    company = question["company"]
    ticket = {"ticket_id": ticket_id, "company": company, "order_id": question["order_id"],
              "booking_type": question["booking_type"], "main_reason": question["main_reason"], "text": text}
    gate = pipeline.gate(ticket)
    stored = _company_writes(company).get_proposal(question["proposal_id"])
    if stored is None or stored["action"] != question["action"]:
        decision = gate.escalate_decision(question["order_id"], "the proposal of the pending question was not found")
    else:
        proposal = {"agent": stored["agent"], "action": stored["action"], "params": stored["params"],
                    "rule_id": stored["rule_id"], "facts_used": stored["facts_used"], "user_confirmed": True,
                    "user_quote": text}
        case = new_case(ticket_id)
        case.update(order_id=question["order_id"], main_reason=question["main_reason"], user_message=text,
                    yes_answer=question["flags"], proof_received=bool(stored.get("proof_received")))
        if company != companies.DEFAULT:
            case.update(booking_type=question["booking_type"])
        trace.log("yes_answer", "channel", {"ticket_id": ticket_id, "question_id": question["id"],
                                            "from_proposal": question["proposal_id"], "action": stored["action"],
                                            "flags": question["flags"]})
        decision = gate.review(proposal, case)
    said, reply, source = pipeline.final_reply(ticket, decision, slm_chat_fn)
    return {"ticket": ticket, "decision": said, "final_reply": reply, "reply_source": source}


# ---------- 3. several requests in one message ----------

# Where a message is cut into parts: sentence ends, ";", ", ", and the joining words between two requests.
CUT_RE = re.compile(r"[.!?\n;]+\s*|,\s+|\s+(?:and also|and then|and|also|plus|but)\s+", re.IGNORECASE)


def _exists(number: int, company: str) -> bool:
    """True when the number is an order (ShopNova) or a booking (Atlas) in the company's data. A read only."""
    if company == "atlas":
        from callverse.data.atlas.reads import find_booking
        return "error" not in find_booking(number)
    from callverse.tools.shopnova_tools import get_order
    return "error" not in get_order(number)


def _ids(text: str, company: str) -> list[int]:
    """Every order / booking number in the text, in order, without repeats (amounts and dates are skipped, as in
    Intake's extractor). A number WITHOUT an order word before it ("order", "booking", "#", ...) counts only if it is
    not a year (1900-2099: "May 2018 flights", found in the T28 regression, practice a05) and it exists in the data."""
    context = extract.CONTEXT_WORDS.get(company, extract.ORDER_CONTEXT_RE)
    found = []
    for m in extract.ORDER_RE.finditer(text):
        if extract.CURRENCY_AFTER_RE.match(text[m.end():]):
            continue
        number = int(m.group(1))
        announced = m.group(0).startswith("#") or bool(context.search(text[:m.start()]))
        if not announced and (1900 <= number <= 2099 or not _exists(number, company)):
            continue
        if number not in found:
            found.append(number)
    return found


def is_money_part(text: str) -> bool:
    """A part that asks for money back or a cancellation (the action that needs a decision)."""
    return asks_for_money_back(text) or bool(CANCEL_WORD_RE.search(text))


def split_requests(text: str, company: str) -> list[dict]:
    """[] when the message has fewer than 2 different ids (one request: nothing changes). Otherwise one part per id:
    [{"order_id", "text", "money"}], in message order. A piece without an id joins the part before it (or the
    first one): "Refund order 4512, it arrived broken, and where is 4511?" -> two parts."""
    if len(_ids(text, company)) < 2:
        return []
    pieces, start = [], 0
    for m in CUT_RE.finditer(text):
        pieces.append((start, m.start()))
        start = m.end()
    pieces.append((start, len(text)))
    parts: list[list] = []   # [start, end, ids]
    for a, b in pieces:
        ids = _ids(text[a:b], company)
        if ids or not parts:
            parts.append([a, b, ids])
        else:
            parts[-1][1] = b
    if len(parts) > 1 and not parts[0][2]:   # a first piece without an id joins the next part
        parts[1][0] = parts[0][0]
        parts.pop(0)
    out = []
    for a, b, ids in parts:
        piece = text[a:b].strip(" ,;")
        for number in ids or []:
            if number not in [p["order_id"] for p in out]:
                out.append({"order_id": number, "text": piece, "money": is_money_part(piece)})
    return out if len(out) > 1 else []


def main_part(parts: list[dict]) -> dict:
    """The part handled by the pipeline: the first money part (a decision first), else the first part."""
    return next((p for p in parts if p["money"]), parts[0])


def _status_sentence(order_id: int, company: str) -> str:
    """One sentence with the status, read from the company's data (never from a model)."""
    if company == "atlas":
        from callverse.data.atlas.reads import find_booking
        booking = find_booking(order_id)
        return f"Your {booking['booking_type']} booking {order_id} is {str(booking.get('status')).replace('_', ' ')}."
    from callverse.tools.shopnova_tools import get_order
    return f"Order {order_id} is {status_words(get_order(order_id).get('status'))}."


def other_parts_sentences(parts: list[dict], main: dict, is_users, company: str) -> list[str]:
    """The sentences added after the main reply, one per other part: not this user's id -> "not on your account";
    a money part -> send it as a new message; an information part -> its status from the data.
    is_users(order_id) -> bool: the channel's identity check."""
    word = "booking" if company == "atlas" else "order"
    sentences = []
    for part in parts:
        if part is main or part["order_id"] == main["order_id"]:
            continue
        if not is_users(part["order_id"]):
            sentences.append(NOT_YOURS_SENTENCE.format(Word=word.capitalize(), order_id=part["order_id"]))
        elif part["money"]:
            sentences.append(ONE_DECISION_SENTENCE.format(word=word, order_id=part["order_id"]))
        else:
            sentences.append(_status_sentence(part["order_id"], company))
    # The fixed "one decision per message" sentence comes last (task T28 step 5).
    return sorted(sentences, key=lambda s: s.startswith("Please send"))
