"""SLM reply writer (M5): turns the Coordinator's decision into a reply in the client's style.

Deciding and wording are separate. The Coordinator fixes WHAT is said (the decision dict, see
docs/decision_format.md); this small local model (qwen2.5 via Ollama, role "slm" in config.yaml) only
decides HOW: formal or casual, short or medium, a calm opener for an upset client.
It gets no tools and never reads the database: its only input is the decision + style + recent messages.

Parts written by CODE, not by the model (T05b): the calm opener for an upset client, the order reference
if the model forgot it, and the removal of repeated sentences. Exact sentences the Coordinator requires
(must_say) are asked from the model and verified by the check.
T08 adds three more code fixes (polish): no ", Your ..." (comma + capital) and a capital at every sentence
start; each must_say sentence only once; "Dear customer," first for a formal client. They are applied to
the SLM's reply and to the template reply.

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
    # T10: short and without comments (the dev set showed invented remarks such as "not met", "mix-up").
    "info": "Give the client the facts in at most two short sentences. Do not comment on them or guess "
            "(no 'not met', 'mix-up', 'on schedule'). Do not promise any follow-up action.",
    # T10: an approved notification gets one friendly sentence around the exact sentence.
    "approve_subscribe": "Tell the client, in one friendly sentence (for example starting with 'Sure,'), "
                         "that the message is set up. Do not promise anything else.",
    # T09
    "layer3_refused": "Tell the client the refund cannot be approved: the finance team did not approve it. "
                      "Do NOT promise a refund, another check or any later action.",
    "notify": "Tell the client the news about their order (the event). Do not promise anything else.",
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
    guide_key = ("approve_subscribe" if decision.get("outcome") == "approve" and decision.get("action") == "subscribe"
                 else decision.get("outcome"))
    content = [OUTCOME_GUIDE.get(guide_key, OUTCOME_GUIDE["info"]),
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
    text = " ".join(part.strip() for part in "\n".join(lines).split("\n") if part.strip())
    # T09: a sign-off at the END of the text on the same line ("... on its way. Kind regards"), often
    # copied from the client's own message, is removed too.
    return SIGN_OFF_TAIL_RE.sub("", text).strip()


# A sign-off after the last sentence, with an optional short name after it ("Kind regards, ShopNova Team").
SIGN_OFF_TAIL_RE = re.compile(
    r"(?<=[.!?])\s+(?:(?:(?:best|kind|warm|warmest)\s+regards|regards|yours sincerely|sincerely|best wishes|"
    r"cheers)[,.!]?|(?:many\s+)?thanks(?:,|(?=\s*$)))(?:\s+[\w ]{1,30})?\s*$", re.IGNORECASE)
# ("Thank you." as a closing sentence is kept: it is a sentence, not a sign-off.)


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


# --- T08: three small fixes by code (Dali's review of T05b) -------------------------------------------

# ", Your refund ..." -> ". Your refund ...": a comma followed by a capital starts a new sentence.
# Not for "I" ("..., I am"). A greeting at the start ("Hi, Your") is handled apart (lower case instead).
COMMA_CAPITAL_RE = re.compile(r",\s+(?!I\b|I')(?=[A-Z][a-z])")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _lower_first_word(text: str) -> str:
    """Lower-case the first letter after a greeting, unless it is "I" or a name such as "ShopNova"."""
    word = text.split(" ", 1)[0]
    if word in ("I", "I'm", "I've", "I'll") or not word[1:].islower():
        return text
    return text[:1].lower() + text[1:]


# T09: shouted words copied from the client. "ORDER 4512 Your refund" -> "Order 4512: your refund".
# The same fragment without capitals ("Order 4515 Your refund", seen in S4) is fixed the same way.
SHOUTED_FRAGMENT_RE = re.compile(r"\b([A-Z]{2,}(?:\s+[A-Z]{2,})*|[Oo]rder)\s+(\d+)\s+([A-Z][a-z]+)")
ALL_CAPS_WORD_RE = re.compile(r"\b[A-Z]{2,}\b")
KEEP_CAPS = {"TND", "OK", "SMS", "ID", "PDF"}   # real abbreviations stay in capitals


def unshout(reply: str) -> str:
    """Never leave the client's all-caps words in the reply (numbers, e.g. the order number, are kept)."""
    reply = SHOUTED_FRAGMENT_RE.sub(
        lambda m: f"{m.group(1).capitalize()} {m.group(2)}: {m.group(3).lower()}", reply)
    return ALL_CAPS_WORD_RE.sub(lambda m: m.group(0) if m.group(0) in KEEP_CAPS else m.group(0).lower(), reply)


def fix_punctuation(reply: str) -> str:
    """No ", Your ..." (comma + capital): split into two sentences; every sentence starts with a capital.
    T09: no shouted (all-caps) words from the client."""
    reply = unshout(reply.strip())
    greeting = GREETING_RE.match(reply)
    head, body = (greeting.group(0).strip(), reply[greeting.end():].lstrip()) if greeting else ("", reply)
    body = COMMA_CAPITAL_RE.sub(". ", body)
    body = body.replace(".. ", ". ")
    body = " ".join(s[:1].upper() + s[1:] for s in SENTENCE_SPLIT_RE.split(body) if s)
    if head and head.endswith(","):
        body = _lower_first_word(body)   # "Hi, your refund ..." stays one sentence
    return f"{head} {body}".strip()


def _norm(sentence: str) -> str:
    """Lower case, no greeting, no "your", no punctuation: to compare a sentence with a must_say sentence."""
    s = GREETING_RE.sub("", sentence).lower()
    s = re.sub(r"\byour\b", " ", s)
    return " ".join(re.sub(r"[^\w\s]", " ", s).split())


def drop_must_say_echoes(reply: str, decision: dict) -> str:
    """T10: drop a sentence that only repeats part of a must_say sentence
    ("Hello, order 4510 is on its way. Your order 4510 is on its way." -> keep the second)."""
    sentences = SENTENCE_SPLIT_RE.split(reply.strip())
    low = " ".join(reply.lower().split())
    kept = []
    for s in sentences:
        n = _norm(s)
        for item in decision.get("must_say") or []:
            exact = " ".join(str(item).lower().split())
            # drop s if it is a part of a must_say sentence, is not that sentence itself, and the exact
            # sentence is also in the reply (so nothing is lost)
            if n and n in _norm(item) and exact not in " ".join(s.lower().split()) and exact in low:
                break
        else:
            kept.append(s)
    return " ".join(kept)


def must_say_once(reply: str, decision: dict) -> str:
    """Each must_say sentence appears once: later exact copies are removed (case-insensitive)."""
    reply = drop_must_say_echoes(reply, decision)
    for item in decision.get("must_say") or []:
        words = str(item).split()
        if not words:
            continue
        pattern = re.compile(r"\s+".join(re.escape(w) for w in words), re.IGNORECASE)
        matches = list(pattern.finditer(reply))
        for match in reversed(matches[1:]):
            reply = reply[:match.start()] + reply[match.end():]
        if matches:
            # T09: the one copy keeps the Coordinator's exact wording, as its own sentence
            # ("Order 4507, please send us a photo" -> "Order 4507. Please send us a photo").
            first = matches[0]
            before = reply[:first.start()].rstrip()
            only_greeting = GREETING_RE.fullmatch(before + " ") is not None
            if only_greeting:   # "Hello, your order ..." stays one sentence after a greeting
                exact = words[0][:1].lower() + " ".join(words)[1:] if words[0][1:].islower() else " ".join(words)
            else:
                if before.endswith(","):
                    before = before[:-1] + "."
                exact = " ".join(words)
            reply = f"{before} {exact}{reply[first.end():]}".strip()
    return " ".join(reply.split())


def add_formal_greeting(reply: str, decision: dict) -> str:
    """Formal client: the reply starts with "Dear customer," (by code, before the calm opener if any).
    Casual / neutral: no fixed greeting is added."""
    if ((decision.get("style") or {}).get("formality")) != "formal" or not reply:
        return reply
    body = GREETING_RE.sub("", reply).strip()
    return f"Dear customer, {_lower_first_word(body)}"


def polish(reply: str, decision: dict) -> str:
    """The T08 fixes, used on SLM replies AND on template replies: punctuation, must_say once, greeting."""
    return add_formal_greeting(must_say_once(fix_punctuation(reply), decision), decision)


def finish(raw: str | None, decision: dict) -> str:
    """Model text -> final reply: clean-up, then the parts written by code (calm opener, order reference,
    T08 fixes: punctuation, must_say once, formal greeting)."""
    reply = drop_repeated_sentences(clean(raw))
    reply = must_say_once(fix_punctuation(reply), decision) if reply else reply
    reply = ensure_order_reference(add_calm_opener(reply, decision), decision)
    return add_formal_greeting(reply, decision)


def warm_up(chat_fn=None) -> dict:
    """Load the SLM into memory with one tiny call (T09), so the first real reply is fast.

    Uses the longer timeout slm.warmup_timeout_s from config.yaml. Never raises: if Ollama is off,
    it returns ok False with a warning (the pipeline then answers with templates)."""
    from callverse.config import load_config
    timeout = load_config()["slm"].get("warmup_timeout_s", 120)
    start = time.perf_counter()
    try:
        if chat_fn:
            chat_fn("slm", [{"role": "user", "content": "Say OK."}])
        else:
            llm.chat("slm", [{"role": "user", "content": "Say OK."}], timeout=timeout)
        result = {"ok": True, "error": None}
    except Exception as e:  # Ollama off, model missing...: a warning, never a crash
        result = {"ok": False, "error": f"{type(e).__name__}: {e}",
                  "warning": "SLM not available: replies will use the templates"}
    result["seconds"] = round(time.perf_counter() - start, 3)
    trace.log("slm_warmup", "slm", result)
    return result


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

    reply = polish(templates.render(decision), decision)
    check = check_reply(reply, decision)
    trace.log("slm_template", "slm", {"outcome": decision.get("outcome"), "reply": reply, **check})
    return {"reply": reply, "check": check, "attempts": MAX_ATTEMPTS, "used_template": True,
            "seconds": round(time.perf_counter() - start, 3)}
