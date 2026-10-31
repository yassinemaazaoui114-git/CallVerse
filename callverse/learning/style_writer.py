"""Style-aware reply writer (RL1 minimal version, plain code, no LLM).

write(decision, style) -> reply text.  The three styles say the SAME decision (same facts, same must_say,
same next step) in a different order / tone:
  short              greeting + decision + facts + next step
  apology_first      apology sentence first, then the decision
  apology_next_step  apology, decision, then "Next step:" + the next step at the end
Built on the fixed template pieces of callverse/slm/templates.py, so every reply passes slm.check.check_reply:
no number outside the facts, must_say word for word, order/booking number mentioned.
"""
from __future__ import annotations

from callverse.slm.templates import FACT_PHRASES, OPENING, case_word

STYLES = ["short", "apology_first", "apology_next_step"]


def _sentences(decision: dict) -> tuple[str, str | None, str | None, list[str]]:
    outcome = decision.get("outcome") if decision.get("outcome") in OPENING else "info"
    facts = decision.get("facts") or {}
    ref = decision.get("order_id")
    about = f" about your {case_word(decision)} {ref}" if ref is not None else ""
    first = f"{OPENING[outcome].capitalize()}{about}."
    if outcome == "approve" and decision.get("action") == "subscribe":
        first = f"Sure, we can do that{' for your ' + case_word(decision) + ' ' + str(ref) if ref is not None else ''}."
    details = [FACT_PHRASES[k](v) for k, v in facts.items() if k in FACT_PHRASES and v is not None]
    if outcome == "ask_proof" and facts.get("needed"):
        details.append(f"please send us: {facts['needed']}")
    if outcome == "layer3" and facts.get("threshold_tnd") is not None:
        details.append(f"refunds above {float(facts['threshold_tnd']):.2f} TND need this approval")
    detail = ("; ".join(details)[0].upper() + "; ".join(details)[1:] + ".") if details else None
    next_step = str(decision["next_step"]).strip() if decision.get("next_step") else None
    return first, detail, next_step, [str(x).strip() for x in decision.get("must_say") or []]


def write(decision: dict, style: str) -> str:
    if style not in STYLES:
        raise ValueError(f"unknown style {style!r}")
    first, detail, next_step, must_say = _sentences(decision)
    thing = f"your {case_word(decision)} {decision['order_id']}" if decision.get("order_id") is not None else "this"
    apology = f"I am sorry for the trouble with {thing}."
    if style == "short":
        parts = ["Hello, " + first[0].lower() + first[1:], detail, next_step]
    elif style == "apology_first":
        parts = [apology, first, detail, next_step]
    else:
        parts = [apology, first, detail, ("Next step: " + next_step) if next_step else None]
    text = " ".join(p for p in parts if p)
    for item in must_say:   # exact sentences the Coordinator requires, once
        if " ".join(item.lower().split()) not in " ".join(text.lower().split()):
            text += " " + item
    return text
