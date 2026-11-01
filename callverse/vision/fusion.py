"""Late fusion: the customer's TEXT (Intake ticket) and PHOTO (visual evidence) are checked separately, then joined.

Rules (no model, no LLM: every routing decision stays explainable):
1. Text with a clear reason: the text decides the reason. The photo never changes it
   ("where is my order?" + a broken phone stays order_status). The photo is attached as evidence.
2. Text without a clear reason ("other") + a photo showing damage, at ShopNova: reason damaged_item
   (ShopNova has a reason for "this arrived damaged"; it describes the problem, not a wish).
   At Atlas no reason describes "damage" alone, so the reason stays as the text says (an agent asks what the
   customer wants): intent is never invented from a photo.
3. Photo only (no text): the same as 2, on a minimal ticket. Emotion and sentiment are NOT guessed from a photo:
   they are set to neutral and marked as not measured.
4. Proof (ShopNova rule R-DMG-01, "a photo of the damage"): proof_received = a photo was received AND the photo
   check sees damage. A photo without visible damage, a doubtful photo or a failed check is NOT proof: a colleague
   looks at it. The Coordinator still checks every other rule (amounts, finance limit, order facts); the photo
   check alone never approves anything.
5. Conflicts are flagged for review: the text says "damaged" but the photo shows none, or the photo is unclear.
"""
from callverse import companies, trace
from callverse.intake import language, priority, style

NOT_MEASURED = "not_measured_photo_only"
# Same shape as Intake's {"label", "score"}: neutral for the reply style, and marked as not measured.
NOT_MEASURED_FEELING = {"label": "neutral", "score": None, "source": NOT_MEASURED}


def photo_block(result: dict | None, error: str | None = None) -> dict:
    """What the ticket keeps about the photo. result = vision.model.analyze(...) output; error = VisionError code."""
    if result is None:
        return {"received": True, "checked": False, "error": error, "assessment": None, "backend": None,
                "verified": False, "source": "vision_model"}
    return {"received": True, "checked": True, "error": None, "assessment": result["assessment"],
            "backend": result["backend"], "adapter": result.get("adapter"), "valid_output": result["valid_output"],
            "verified": False,          # model output, never a business fact
            "source": "vision_model"}


def shows_damage(photo: dict | None) -> bool:
    a = (photo or {}).get("assessment")
    return bool(a) and a["visible_damage"] is True


def image_only_ticket(ticket_id: str, company: str, order_id=None) -> dict:
    """A ticket for a photo sent without text. No text model runs: nothing about feelings is guessed."""
    found = ["other"]
    facts_none = ({"status": None, "paid": None, "hours_to_start": None} if company == "atlas"
                  else {"days_late": None, "delivered": None, "paid": None})
    ticket = {"ticket_id": ticket_id, "company": company, "text": "", "order_id": order_id, "email": None,
              "phone": None, "reasons": [{"reason": "other", "score": None, "sentence": None}], "main_reason": "other",
              "emotion": dict(NOT_MEASURED_FEELING), "sentiment": dict(NOT_MEASURED_FEELING), "facts": facts_none,
              **priority.compute(found, facts_none, 0.0, company), "style": style.profile(""),
              "language": language.detect(""), "needs_llm": False, "seconds": 0.0}
    if company == "atlas":
        ticket["booking_type"] = None
    return ticket


def fuse(ticket: dict, photo: dict | None) -> dict:
    """Return the ticket with photo + fusion fields. ticket = Intake's ticket (or image_only_ticket)."""
    company = companies.of(ticket)
    if photo is None:
        return {**ticket, "photo": None, "fusion": {"reason_source": "text", "conflict": None,
                                                    "proof_received": False, "requires_review": False}}
    a = photo.get("assessment")
    damage = shows_damage(photo)
    text_reason = ticket["main_reason"]
    has_text = bool((ticket.get("text") or "").strip())
    main, source = text_reason, "text" if has_text else "none"
    if text_reason == "other" and damage and company == companies.DEFAULT:
        main, source = "damaged_item", ("text+photo" if has_text else "photo")
    conflict = None
    if not photo["checked"]:
        conflict = "photo_not_checked"
    elif a["issue_type"] == "unclear":
        conflict = "photo_unclear"
    elif text_reason == "damaged_item" and a["visible_damage"] is False:
        conflict = "text_says_damage_photo_shows_none"
    out = dict(ticket)
    if main != text_reason:
        out["main_reason"] = main
        out["reasons"] = [{"reason": main, "score": None, "sentence": None, "source": "photo"}] + \
            [r for r in ticket["reasons"] if r["reason"] != "other"]
        # same priority formula as Intake, with the new reason (emotion_intensity = Intake's clamped negative score)
        prio = priority.compute([main], ticket["facts"], ticket.get("emotion_intensity", 0.0), company)
        out.update(prio)
    fusion = {"reason_source": source, "text_reason": text_reason, "conflict": conflict,
              "proof_received": damage,   # rule 4: a photo AND visible damage (R-DMG-01)
              "requires_review": bool(conflict) or bool(a and a["requires_review"])}
    out.update(photo=photo, fusion=fusion)
    trace.log("vision_fusion", "fusion", {"ticket_id": ticket["ticket_id"], "company": company,
                                          "issue_type": a["issue_type"] if a else None, **fusion,
                                          "main_reason": main})
    return out


def describe(a: dict, proof: bool | None) -> str:
    """The photo check in one line, clearly marked as model output (not a fact)."""
    tail = "" if proof is None else f" Photo proof for R-DMG-01 = {'yes' if proof else 'no'}."
    return (f"[Photo check (model, unverified): object = {a['object']}, issue = {a['issue_type']}, "
            f"visible damage = {a['visible_damage']}, confidence = {a['confidence_level']}. "
            f"\"{a['description']}\"{tail}]")


def note(ticket: dict) -> str:
    """One line for the agents: what the photo check saw, clearly marked as unverified."""
    p = ticket.get("photo")
    if not p:
        return ""
    if not p["checked"]:
        return "[Photo: received, but it could not be checked automatically. Do not assume what it shows.]"
    return describe(p["assessment"], ticket["fusion"]["proof_received"])
