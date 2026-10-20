"""SLM reply writer (M5): turns the Coordinator's decision into a reply in the client's style.

Deciding and wording are separate. The Coordinator fixes WHAT is said (the decision dict, see
docs/decision_format.md); this small local model (qwen2.5 via Ollama, role "slm" in config.yaml) only
decides HOW: formal or casual, short or medium, a calm opener for an upset client.
It gets no tools and never reads the database: its only input is the decision + style + recent messages.

Parts written by CODE, not by the model (T05b): the calm opener for an upset client, the order reference
if the model forgot it, and the removal of repeated sentences. Exact sentences the Coordinator requires
(must_say) are asked from the model and verified by the check.

Flow of write_reply():
  1. SLM writes a reply -> code parts -> rule check (check.py).
  2. If it fails: one retry, with the problems listed for the model.
  3. If it fails again: a fixed template (templates.py), which always passes the check.
Every SLM call, check and template use is traced (slm_call, slm_check, slm_template).
"""

import json
import re
import time

from callverse import llm, trace
from callverse.slm import templates
from callverse.slm.check import check_reply
from callverse.slm.templates import calm_opener, is_upset

MAX_ATTEMPTS = 2   # first try + one retry

SYSTEM_PROMPT = """You write the final reply of ShopNova customer service (an online shop in Tunisia) to a client.
The decision is already made. You only choose the wording.

Rules:
- Use ONLY the facts, order number and next step given to you. Never add any other number, date, amount,
  delay, name or promise.
- Never promise follow-up actions such as "we will keep you updated", "we are monitoring", "we guarantee",
  "within 24 hours", "as soon as possible", compensation or vouchers.
- Mention the order number in the FIRST sentence, written as "order 1234". Then say the next step.
- Never write internal codes such as R-REF-03. Never use placeholders such as [Name]: you do not know the name.
- Amounts are in TND (never $ or EUR).
- No subject line, no signature, no "Best regards". Plain text only, at most 80 words.
- Write in English, in the tone asked.

Example (made-up values, do not reuse them):
Decision: approve, refund, order 7001, facts {"amount_tnd": 12.50, "days_late": 8}, next step "The money goes back to
your card."  Tone: friendly, client upset.
Reply: Hi, I'm really sorry about the wait on order 7001. Your refund of 12.50 TND is approved, since the parcel is
8 days late. The money goes back to your card."""

OUTCOME_GUIDE = {
    "approve": "Tell the client their request is approved.",
    "send_back": "Tell the client their request is still being checked. Do not say it is approved or refused.",
    "ask_user": "Ask the client the question in the next step. Do not decide anything.",
    "ask_proof": "Tell the client which proof is needed. Do not promise a refund or a replacement.",
    "layer3": "Tell the client the refund needs approval from the finance team first. "
              "Do NOT say the refund is approved and do NOT promise it will be paid.",
    "escalate": "Tell the client a colleague will take over. Do not promise any result.",
    "info": "Give the client the facts. Do not promise any follow-up action.",
}


def style_guide(style: dict | None) -> str:
    """Turn Intake's style profile into plain instructions for the model."""
    style = style or {}
    tone = {"formal": "Formal and polite, no slang. Start with exactly: Dear customer,",
            "casual": "Friendly and relaxed, simple words, still respectful. Start with exactly: Hi,"
            }.get(style.get("formality"), "Neutral and polite. Start with exactly: Hello,")
    size = ("Very short: 2 or 3 sentences, at most 45 words." if style.get("length") == "short"
            else "Clear: 3 to 5 sentences, at most 80 words.")
    if is_upset(style):
        # The calm opener is added by code (write_reply), so the model must not write its own.
        tone = tone.split(" Start with exactly:")[0]
        return (f"Tone: {tone} Length: {size} Do NOT write a greeting or an apology: an apology sentence is "
                "added before your text automatically. Start directly with the order.")
    return f"Tone: {tone} Length: {size}"


def build_messages(decision: dict, history: list[dict] | None = None, problems: list[str] | None = None) -> list:
    """Messages for the SLM: rules, the decision's allowed content, the tone, and the last problems if retrying."""
    allowed = {"order_number": decision.get("order_id"), "facts": decision.get("facts") or {},
               "next_step": decision.get("next_step") or "", "must_say": decision.get("must_say") or []}
    content = [OUTCOME_GUIDE.get(decision.get("outcome"), OUTCOME_GUIDE["info"]),
               "What you may say (nothing else):\n" + json.dumps(allowed, ensure_ascii=False, indent=1),
               style_guide(decision.get("style"))]
    if decision.get("order_id") is not None:
        content.append(f'Your first sentence must contain the exact words "order {decision["order_id"]}".')
    if decision.get("must_say"):
        content.append("Copy each of these sentences into your reply EXACTLY, word for word, without changing them:\n"
                       + "\n".join(f'- "{item}"' for item in decision["must_say"]))
    if decision.get("next_step"):
        content.append(f'End with the next step, almost word for word: "{decision["next_step"]}"')
    recent = [m.get("content", "") for m in (history or []) if m.get("role") == "user"][-3:]
    if recent:
        content.append("The client's last messages (for tone only, take NO facts from them):\n"
                       + "\n".join(f"- {r}" for r in recent))
    if problems:
        content.append("Your previous reply was rejected because: " + "; ".join(problems)
                       + ". Write a new reply that fixes these problems.")
    content.append("Write the reply now.")
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "\n\n".join(content)}]


SIGN_OFFS = {"best regards", "kind regards", "warm regards", "regards", "sincerely", "yours sincerely",
             "best wishes", "cheers"}


def clean(text: str | None) -> str:
    """Formatting clean-up only (it never adds words): remove a 'Reply:' label, surrounding quotes,
    and a signature block ("Best regards, ShopNova Team") that small models add even when told not to."""
    text = (text or "").strip()
    for label in ("Reply:", "Response:", "Answer:"):
        if text.lower().startswith(label.lower()):
            text = text[len(label):].strip()
    if len(text) > 1 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    lines = text.splitlines()
    for i, line in enumerate(lines):
        rest = [x for x in lines[i + 1:] if x.strip()]
        # A sign-off line followed only by short lines (a name, a team, an order line) = a signature block.
        if i > 0 and line.strip().lower().rstrip(",!. ") in SIGN_OFFS and all(len(x.split()) <= 6 for x in rest):
            lines = lines[:i]   # drop the sign-off line and the signature after it
            break
    return " ".join(part.strip() for part in "\n".join(lines).split("\n") if part.strip())


GREETING_RE = re.compile(r"^\s*(?:(?:hi|hello|hey|dear (?:customer|client|sir|madam|valued customer))\b[,!.]?\s*)+",
                         re.IGNORECASE)
APOLOGY_WORDS = ("sorry", "apolog", "understand", "frustrat", "inconvenience")
SORRY_PREFIX_RE = re.compile(r"^(?:(?:i'?m|i am|we'?re|we are)\s+)?(?:so |very |really |truly )?sorry\b[,!.]?\s*",
                             re.IGNORECASE)


def add_calm_opener(reply: str, decision: dict) -> str:
    """For an upset client, start the reply with the fixed calm opener (by code, not by the model).

    A greeting or an apology sentence the model wrote anyway is removed first, so the apology is not doubled;
    a first sentence carrying the order number or a must_say item is always kept.
    """
    opener = calm_opener(decision.get("style"))
    if not opener or not reply:
        return reply
    body = GREETING_RE.sub("", reply).strip()
    first, _, rest = body.partition(". ")
    keep = [str(decision.get("order_id") or "\0")] + [str(x).lower() for x in decision.get("must_say") or []]
    if rest and any(w in first.lower() for w in APOLOGY_WORDS) and not any(k.lower() in first.lower() for k in keep):
        body = rest.strip()
    body = SORRY_PREFIX_RE.sub("", body).strip() or body   # "Sorry, order 4512 ..." -> "order 4512 ..."
    return f"{opener} {body[:1].upper()}{body[1:]}"


def drop_repeated_sentences(reply: str) -> str:
    """Remove a sentence that repeats an earlier one word for word (it only deletes, never adds)."""
    seen, kept = set(), []
    for sentence in re.split(r"(?<=[.!?])\s+", reply.strip()):
        key = " ".join(sentence.lower().split())
        if key and key in seen and len(sentence.split()) >= 4:
            continue
        seen.add(key)
        kept.append(sentence)
    return " ".join(kept)


def ensure_order_reference(reply: str, decision: dict) -> str:
    """If the model forgot the order number, insert "About your order N:" by code, after the opener/greeting.

    The order number is a fact from the decision, so adding it never adds anything that was not approved.
    """
    order = decision.get("order_id")
    if order is None or not reply or str(order) in reply:
        return reply
    opener = calm_opener(decision.get("style")) or ""
    head = opener if opener and reply.startswith(opener) else ""
    rest = reply[len(head):].lstrip()
    greeting = GREETING_RE.match(rest)
    if greeting:
        head = (head + " " + greeting.group(0).strip()).strip()
        rest = rest[greeting.end():].lstrip()
    rest = rest[:1].lower() + rest[1:] if rest[:2] != "I " else rest
    return f"{head} About your order {order}: {rest}".strip()


def finish(raw: str | None, decision: dict) -> str:
    """Model text -> final reply: clean-up, then the parts written by code (calm opener, order reference)."""
    reply = drop_repeated_sentences(clean(raw))
    return ensure_order_reference(add_calm_opener(reply, decision), decision)


def write_reply(decision: dict, history: list[dict] | None = None, chat_fn=None) -> dict:
    """Return {"reply", "check", "attempts", "used_template", "seconds"}. The reply always passes the check."""
    chat = chat_fn or llm.chat
    start = time.perf_counter()
    problems = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        call_start = time.perf_counter()
        try:
            reply = finish(chat("slm", build_messages(decision, history, problems)).content, decision)
            error = None
        except Exception as e:  # Ollama down, model missing...: go on to retry / template, never crash
            reply, error = "", f"{type(e).__name__}: {e}"
        trace.log("slm_call", "slm", {"attempt": attempt, "outcome": decision.get("outcome"),
                                      "order_id": decision.get("order_id"), "reply": reply, "error": error,
                                      "seconds": round(time.perf_counter() - call_start, 3)})
        check = check_reply(reply, decision)
        trace.log("slm_check", "slm", {"attempt": attempt, **check})
        if check["passed"]:
            return {"reply": reply, "check": check, "attempts": attempt, "used_template": False,
                    "seconds": round(time.perf_counter() - start, 3)}
        problems = check["problems"] if not error else ["the model did not answer"]

    reply = templates.render(decision)
    check = check_reply(reply, decision)
    trace.log("slm_template", "slm", {"outcome": decision.get("outcome"), "reply": reply, **check})
    return {"reply": reply, "check": check, "attempts": MAX_ATTEMPTS, "used_template": True,
            "seconds": round(time.perf_counter() - start, 3)}
