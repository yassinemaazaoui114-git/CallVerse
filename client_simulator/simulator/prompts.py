"""Prompts for the CallVerse Client Simulator. The Phase 3 tests import these exact builders,
so the kit ships the prompts that were measured against real data."""
import json

COMPANY_DESC = {
    "shopnova": "ShopNova, an online shop (electronics, home, fashion) that delivers parcels",
    "atlas": "Atlas Travel, a travel agency that sells flights, hotels, trains and buses",
}
TYPO_STYLE = {
    "low": "You write correctly, with normal spelling and punctuation.",
    "medium": "You write casually on your phone: an occasional typo, loose punctuation, sometimes no capital letters.",
    "high": "You type fast on your phone: lowercase, several typos, missing apostrophes, little punctuation.",
}
ASSISTANT_PHRASES = [
    "how can i help", "how may i help", "how can i assist", "as an ai", "language model", "i'm an ai",
    "i am an ai", "is there anything else", "happy to help", "glad to help", "i'd be happy to assist",
    "thank you for contacting", "thank you for reaching out", "i understand your frustration",
    "i apologize for the inconvenience", "let me look into", "let me check that for you",
]
POLITE_MARKERS = ["please", "thank you", "thanks", "kindly", "i appreciate", "i hope this message finds you",
                  "dear", "sincerely", "regards", "would you be so kind", "grateful"]


def role_card_text(card):
    facts = card.get("facts") or {}
    lines = [f"Company: {COMPANY_DESC[card['company']]}.",
             f"Who you are: {card.get('persona', {}).get('description', 'a customer')}",
             f"Your mood: {card.get('mood', 'calm')}.",
             f"Your problem and goal: {card['goal']}"]
    if facts:
        lines.append("Facts you know: " + "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in facts.items()))
    return "\n".join(lines)


def roleplay_system(card, examples=None):
    """System prompt for simulate_turn (prompt version rp1)."""
    style = TYPO_STYLE.get(card.get("typo_level", "medium"), TYPO_STYLE["medium"])
    s = (
        "You are role-playing a real CUSTOMER who is chatting with a customer-service agent. "
        "You are NOT an assistant: you need help, you do not give it.\n\n"
        f"{role_card_text(card)}\n\nHow you write: {style}\n\n"
        "Rules:\n"
        "- Write ONLY your next chat message as the customer, in English, in first person.\n"
        "- Keep it short like a real chat message: usually 1-3 sentences, 8-30 words.\n"
        "- Stay in your mood. Give a fact (order number, booking reference, date) only when it is asked for or natural.\n"
        "- Never write the agent's lines, never offer help, never say you are an AI, no quotation marks, no notes."
    )
    if examples:
        s += "\n\nReal customers write like this (copy the style, not the content):\n" + "\n".join(f"- {e}" for e in examples)
    return s


def roleplay_messages(card, history, examples=None):
    """history: list of {"role": "customer"|"agent", "text": str}. The model plays the customer, so the
    customer's earlier turns are 'assistant' and the agent's turns are 'user'."""
    msgs = [{"role": "system", "content": roleplay_system(card, examples)}]
    if not history or history[0]["role"] == "customer":
        msgs.append({"role": "user", "content": "(The support chat has opened. Write your first message.)"})
    for h in history:
        msgs.append({"role": "assistant" if h["role"] == "customer" else "user", "content": h["text"]})
    return msgs


# ------------------------------------------------------------------ scoring
JSON_SPEC = 'Answer with JSON only, exactly: {"score": <integer 1-5>, "comment": "<one short line in your own words>"}'


def transcript_text(transcript, max_turns=None):
    t = transcript[-max_turns:] if max_turns else transcript
    return "\n".join(("Customer: " if x["role"] in ("customer", "user") else "Agent: ") + x["text"] for x in t)


def rubric_text(rubric):
    """rubric: dict built from the real TRAIN statistics (see scripts/p3_tests.py: build_rubrics)."""
    return "How real customers score (from real data):\n" + "\n".join(f"- {r}" for r in rubric["lines"])


def score_messages(card_text, transcript, version="v1", rubric=None, shots=None):
    """version v1 = plain prompt; v2 = rubric from real statistics + balanced real few-shot examples."""
    sys = ("You are the customer described below. Your contact with customer service is over. "
           "Rate how satisfied you are with the service, from 1 (very dissatisfied) to 5 (very satisfied), "
           "and write a one-line comment as the customer.")
    if version == "v2" and rubric:
        sys += "\n\n" + rubric_text(rubric)
    msgs = [{"role": "system", "content": sys}]
    if version == "v2" and shots:
        for ex in shots:
            msgs.append({"role": "user", "content": ex["prompt"]})
            msgs.append({"role": "assistant", "content": json.dumps({"score": ex["score"], "comment": ex["comment"]})})
    body = card_text
    if transcript:
        body += "\n\nThe conversation:\n" + transcript_text(transcript)
    msgs.append({"role": "user", "content": body + "\n\n" + JSON_SPEC})
    return msgs


SCORE_SCHEMA = {"type": "object", "properties": {"score": {"type": "integer", "minimum": 1, "maximum": 5},
                                                  "comment": {"type": "string"}}, "required": ["score", "comment"]}


def breaks_role(text):
    t = (text or "").lower()
    return any(p in t for p in ASSISTANT_PHRASES)


REASON_TEXT = {"order_status": "the status of an order", "late_delivery": "a late delivery", "refund_request": "a refund",
               "return_item": "returning an item", "damaged_item": "a damaged or wrong item", "booking_status": "a booking",
               "cancellation": "a cancellation", "rebooking": "changing a booking", "delay_disruption": "a delay or disruption",
               "special_assistance": "special assistance", "other": "another problem"}


def compact_roleplay_system(card):
    """Short role card used to fine-tune the small writer (prompt version ft1) and to run it in the kit."""
    comp = "ShopNova (online shop)" if card["company"] == "shopnova" else "Atlas Travel (travel agency)"
    s = (f"You are a customer of {comp} writing to customer support. Contact reason: "
         f"{REASON_TEXT.get(card.get('reason', 'other'), 'another problem')}. Mood: {card.get('mood', 'calm')}. "
         f"Typos: {card.get('typo_level', 'medium')}.")
    if card.get("goal"):
        s += f" Situation: {card['goal']}"
    facts = card.get("facts") or {}
    if facts:
        s += " Facts: " + "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in facts.items()) + "."
    return s + " Write only your next message."
