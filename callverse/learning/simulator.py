"""Lightweight feedback simulator for the style RL (SIMULATED data: never real human ratings).

Why plain code: no LLM / Ollama / paid API is available in the build environment, and the reward model must be
trainable and testable offline. Every record it produces carries "source": "simulated".

make_personas(n, seed)              -> personas (patience, style preference, emotion, notices errors)
make_situations()                   -> the scripted ShopNova orders 4505-4515 and Atlas bookings 7001-7012, with a
                                       Coordinator-like decision made BY CODE from the live tool reads (no agents)
corrupt(reply, decision, kind)      -> a wrong reply (invented amount, unapproved refund, false delivery promise,
                                       fabricated completed action), to teach / test the verifier
react(situation, reply, persona, corruption, rng) -> {"rating": 1..5, "comment": str}
build_dataset(personas, seed, corruption_rate)    -> list of spec conversation records + rating + labels
Persona sets with different seeds: TRAIN (seed 101), VAL (202), EVAL (303). Never mix them.
First messages: the AI-generated reason examples of the Intake build set (flagged), with the real order number.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from callverse import companies
from callverse.kb.policies import layer3_threshold
from callverse.learning.style_writer import STYLES, write

ROOT = Path(__file__).resolve().parents[2]
UPSET = {"anger", "disgust", "sadness", "fear"}
ARCHETYPES = {   # style preference (added to the rating) by persona type
    "warm": {"short": -0.4, "apology_first": 0.5, "apology_next_step": 0.2},
    "busy": {"short": 0.5, "apology_first": -0.4, "apology_next_step": -0.1},
    "practical": {"short": 0.0, "apology_first": -0.2, "apology_next_step": 0.5},
    "neutral": {"short": 0.1, "apology_first": 0.0, "apology_next_step": 0.1},
}
BASE = {"approve": 4.3, "info": 3.3, "ask_proof": 3.1, "ask_user": 3.0, "layer3": 2.9, "send_back": 2.8, "escalate": 2.6}
CORRUPTIONS = ["invented_amount", "unapproved_refund", "false_delivery_promise", "fabricated_action"]


# ----------------------------------------------------------------------------- personas
def make_personas(n: int, seed: int, tag: str) -> list[dict]:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        arch = rng.choice(list(ARCHETYPES))
        emotion = rng.choices(["anger", "sadness", "neutral", "joy", "fear"], [0.35, 0.15, 0.3, 0.12, 0.08])[0]
        out.append({"id": f"{tag}-{i:03d}", "archetype": arch, "style_pref": ARCHETYPES[arch],
                    "patience": round(rng.uniform(0.1, 0.9), 2), "emotion": emotion,
                    "sentiment": "negative" if emotion in UPSET else ("positive" if emotion == "joy" else "neutral"),
                    "formality": rng.choice(["casual", "neutral", "formal"]),
                    "notices_errors": round(rng.uniform(0.4, 0.95), 2), "source": "simulated"})
    return out


# ----------------------------------------------------------------------------- situations (decisions by code)
def _first_message(company: str, reason: str, ref: int, rng: random.Random) -> str:
    path = ROOT / "callverse/intake/data" / ("reason_examples.json" if company == "shopnova" else "reason_examples_atlas.json")
    pool = json.loads(path.read_text(encoding="utf-8")).get(reason) or ["Hi, I need help with my case."]
    text = rng.choice(pool)
    import re
    text = re.sub(r"\b\d{4,5}\b", str(ref), text, count=1)
    return text if str(ref) in text else f"{text} ({'Order' if company == 'shopnova' else 'Booking'} {ref})"


def _shopnova_situations() -> list[dict]:
    from callverse.tools import shopnova_tools as t
    sits = []

    def add(order_id, reason, outcome, action, rule_id, facts, next_step, must_say=None):
        sits.append({"company": "shopnova", "reason": reason, "ref": order_id,
                     "decision": {"company": "shopnova", "outcome": outcome, "action": action, "order_id": order_id,
                                  "rule_id": rule_id, "facts": facts, "next_step": next_step,
                                  "must_say": must_say or []}})

    thr = layer3_threshold()
    for o in range(4505, 4516):
        tr, od, rf = t.get_tracking(o), t.get_order(o), t.get_refunds(o)
        late, delivered, paid, refunded = tr["days_late"], tr["delivered"], float(od["paid"]), rf["refunded_total"]
        base = {"days_late": late, "delivered": delivered, "order_status": tr["status"]}
        add(o, "order_status", "info", "status", "R-DEL-01", base, "You can check the tracking page any time.")
        if not delivered and late > 5 and paid - refunded > 0:
            money = {**base, "amount_tnd": paid, "amount": paid, "paid": paid, "refunded_total": refunded}
            if paid > thr:
                add(o, "refund_request", "layer3", "refund", "R-ESC-01", {**money, "threshold_tnd": thr},
                    "Our finance team answers within the next working days.".replace("within the next working days", "on their next review"))
            else:
                add(o, "refund_request", "approve", "refund", "R-REF-03", money,
                    "The money goes back to the card you paid with.", [f"Your refund of {paid:.2f} TND is approved."])
        elif not delivered and 1 <= late <= 5:
            add(o, "late_delivery", "info", "status", "R-DEL-02", base, "We can send you a message when it ships.")
        elif refunded > 0:
            add(o, "refund_request", "info", "refund", None, {**base, "refunded_total": refunded, "paid": paid},
                "This order was already refunded in full.")
        elif paid == 0:
            add(o, "refund_request", "info", "refund", None, {**base, "paid": paid}, "Nothing was paid yet, so there is nothing to refund.")
        else:
            add(o, "refund_request", "info", "refund", None, base, "A refund is only possible for an order more than 5 days late.")
        if delivered:
            dsd = tr["days_since_delivery"]
            if dsd is not None and dsd <= 14:
                add(o, "return_item", "approve", "return", "R-RET-01", {**base, "days_since_delivery": dsd},
                    "Please drop the parcel at any Rapid-Poste office with the return label.")
            else:
                add(o, "return_item", "info", "return", None, {**base, "days_since_delivery": dsd}, "The 14-day return window has closed.")
            add(o, "damaged_item", "ask_proof", "replace", "R-DMG-01", {**base, "needed": "a photo of the damaged item"},
                "Please send us a photo of the damaged item.")
        else:
            add(o, "other", "escalate", "stock", None, base, "A colleague will contact you about the stock of this item.")
        if not delivered:
            add(o, "order_status", "approve", "subscribe", "R-NOT-01", {**base, "event": "shipped"},
                "You will get one message when it ships.")
    return sits


def _atlas_situations() -> list[dict]:
    from callverse.data.atlas import reads as r
    sits = []

    def add(bid, reason, outcome, action, rule_id, facts, next_step, must_say=None):
        sits.append({"company": "atlas", "reason": reason, "ref": bid,
                     "decision": {"company": "atlas", "outcome": outcome, "action": action, "order_id": bid,
                                  "case_word": "booking", "rule_id": rule_id, "facts": facts,
                                  "next_step": next_step, "must_say": must_say or []}})

    for b in range(7001, 7013):
        h = r.get_hotel_booking(b)
        x, kind = (h, "hotel") if "error" not in h else (r.get_flight_booking(b), "flight")
        paid, refunded = float(x["paid_tnd"]), r.get_refunds(kind, b)["refunded_total"]
        base = {"booking_type": kind, "status": x["status"]}
        add(b, "booking_status", "info", "status", None, base, "Your booking details are in your account.")
        if kind == "hotel":
            f = {**base, "deposit_type": x["deposit_type"], "days_before_arrival": x["days_before_arrival"],
                 "paid_tnd": paid, "refunded_total": refunded, "room_changed": x["room_changed"]}
            if x["status"] == "cancelled" and x["deposit_type"] == "refundable" and x["days_before_arrival"] >= 2 and paid > 0:
                add(b, "refund_request", "approve", "cancel_hotel", "AT-HOT-02", {**f, "amount_tnd": paid, "amount": paid},
                    "The money goes back to the card you paid with.", [f"Your refund of {paid:.2f} TND is approved."])
            elif x["status"] == "cancelled" and x["deposit_type"] == "non_refundable":
                add(b, "refund_request", "info", "refund", "AT-HOT-03", f, "A non-refundable booking cannot be refunded.")
            elif x["status"] == "cancelled":
                add(b, "cancellation", "info", "cancel_hotel", "AT-HOT-01", f, "No deposit was paid, so there is nothing to refund.")
            elif x["status"] == "stayed" and x["room_changed"]:
                add(b, "compensation_request", "layer3", "compensation", "AT-ESC-01", {**f, "action": "compensation", "amount": 0},
                    "Our finance team decides on compensation.")
            else:
                add(b, "rebooking", "escalate", "rebook", None, f, "A colleague will handle the change of dates.")
        else:
            f = {**base, "cancelled": x["cancelled"], "flight_status": x["flight_status"],
                 "departure_delay_min": x["departure_delay_min"], "cancellation_reason": x["cancellation_reason"],
                 "main_delay_cause": x["main_delay_cause"], "paid_tnd": paid, "refunded_total": refunded}
            if x["cancelled"] == 1 and paid - refunded > 0:
                add(b, "refund_request", "approve", "refund", "AT-FLT-01", {**f, "amount_tnd": paid, "amount": paid},
                    "The money goes back to the card you paid with.", [f"Your refund of {paid:.2f} TND is approved."])
            if x["flight_status"] == "delayed" and x["main_delay_cause"] in ("weather", "air_system", "security"):
                add(b, "compensation_request", "info", "compensation", "AT-FLT-06", f,
                    "Delays caused by weather or air traffic control give no compensation.")
            elif x["flight_status"] == "delayed":
                add(b, "compensation_request", "layer3", "compensation", "AT-ESC-01", {**f, "action": "compensation", "amount": 0},
                    "Our finance team decides on compensation.")
            if x["status"] == "confirmed":
                add(b, "rebooking", "escalate", "rebook", None, f, "A colleague will look at the new flight with you.")
                add(b, "special_assistance", "escalate", "assist", None, f, "A colleague will arrange the assistance.")
    return sits


def make_situations() -> list[dict]:
    """All scripted situations, with a stable scenario_id. Needs the seeded ShopNova + Atlas databases."""
    sits = _shopnova_situations() + _atlas_situations()
    for i, s in enumerate(sits):
        s["scenario_id"] = f"S{i:03d}-{s['company']}-{s['ref']}-{s['reason']}"
    return sits


# ----------------------------------------------------------------------------- wrong replies
def corrupt(reply: str, decision: dict, kind: str) -> str:
    extra = {"invented_amount": " You will also get 20 TND as a goodwill gesture.",
             "unapproved_refund": " Your refund has been approved and the money is on its way.",
             "false_delivery_promise": " It will arrive within 2 days, guaranteed.",
             "fabricated_action": (" We have already rebooked you on the next flight." if decision.get("company") == "atlas"
                                   else " We have already reshipped your order.")}
    return reply + extra[kind]


# ----------------------------------------------------------------------------- reaction
def react(situation: dict, reply: str, persona: dict, corruption: str | None, rng: random.Random) -> dict:
    """A simulated 1-5 rating + comment. Simulated: encodes assumptions, not real customers."""
    d = situation["decision"]
    x = BASE[d["outcome"]]
    late = float(d["facts"].get("days_late") or 0)
    x -= min(1.5, 0.15 * late) * (1.2 - persona["patience"])
    style = situation["style"]
    x += persona["style_pref"][style]
    if persona["emotion"] in UPSET:
        x += {"short": -0.3, "apology_first": 0.3, "apology_next_step": 0.2}[style]
    else:
        x += {"short": 0.2, "apology_first": -0.2, "apology_next_step": 0.0}[style]
    if d["outcome"] == "approve" and d["facts"].get("amount_tnd"):
        x += 0.3
    noticed = corruption is not None and rng.random() < persona["notices_errors"]
    if corruption and not noticed:
        x += 0.4      # a false promise sounds nice when the customer does not notice: this is why correctness is checked
    if noticed:
        x -= 1.8
    x += rng.gauss(0, 0.45)
    rating = int(min(5, max(1, round(x))))
    comment = {1: "This did not help at all.", 2: "Not happy with this answer.", 3: "Okay, I guess.",
               4: "Thanks, that is clear.", 5: "Great, thank you!"}[rating]
    if noticed:
        comment = "That is not what you promised before. " + comment
    return {"rating": rating, "comment": comment, "noticed_error": noticed}


def record_for(situation: dict, persona: dict, style: str, corruption: str | None, rng: random.Random) -> dict:
    """One spec conversation record (plus simulated rating and labels) for a situation x persona x style."""
    d = situation["decision"]
    reply = write(d, style)
    if corruption:
        reply = corrupt(reply, d, corruption)
    sit = {"company": situation["company"], "reason": situation["reason"], "outcome": d["outcome"],
           "action": d["action"], "rule_id": d.get("rule_id"), "emotion": persona["emotion"],
           "sentiment": persona["sentiment"], "priority": "high" if persona["emotion"] in UPSET else "normal",
           "days_late": d["facts"].get("days_late")}
    rec = {"ticket_id": f"SIM-{situation['scenario_id']}-{persona['id']}-{style}", "company": situation["company"],
           "messages": [{"role": "user", "text": _first_message(situation["company"], situation["reason"], situation["ref"], rng)},
                        {"role": "assistant", "text": reply}],
           "situation": sit, "style": style, "decision": d, "scenario_id": situation["scenario_id"],
           "persona_id": persona["id"], "source": "simulated", "corruption": corruption,
           "first_message_source": "ai_generated_intake_examples"}
    reaction = react({**situation, "style": style}, reply, persona, corruption, rng)
    return {**rec, "rating": reaction["rating"], "comment": reaction["comment"], "noticed_error": reaction["noticed_error"]}


def build_dataset(personas: list[dict], seed: int, corruption_rate: float = 0.25, situations=None) -> list[dict]:
    rng = random.Random(seed)
    situations = situations or make_situations()
    rows = []
    for p in personas:
        for s in situations:
            for style in STYLES:
                c = rng.choice(CORRUPTIONS) if rng.random() < corruption_rate else None
                rows.append(record_for(s, p, style, c, rng))
    return rows


def write_jsonl(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
