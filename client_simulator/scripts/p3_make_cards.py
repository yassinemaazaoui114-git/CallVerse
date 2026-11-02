"""Write the YAML role cards (simulator/role_cards/<company>/*.yaml) used by Test 2 and shipped in the kit.
Cards marked scenario: GS-.. reuse the persona, mood and scripted case of PI Platforms/scenarios."""
import yaml

from common import ROOT

OUT = ROOT / "simulator" / "role_cards"

# id, company, reason, mood, typo, persona description, goal, facts, scenario
CARDS = [
    # ShopNova - from golden scenarios
    ("SN-01", "shopnova", "late_delivery", "frustrated but polite", "low", "A student in Germany who ordered a laptop and a sleeve for her studies.",
     "Your laptop has not arrived: it was due on 8 October and the tracking has not moved for a week. You want to know where it is and whether you get compensation.",
     {"order_id": 4512, "ordered_on": "1 October", "due_on": "8 October", "carrier": "DHL"}, "GS-SN-01"),
    ("SN-02", "shopnova", "refund_request", "calm, decided", "low", "Lives in a small flat; bought an air purifier a week ago.",
     "The Smart Air Purifier Mini is far too loud for your bedroom. You want to send it back and get a refund of 104.99 EUR.",
     {"order_id": 4513, "delivered_on": "8 October", "price": "104.99 EUR"}, "GS-SN-02"),
    ("SN-03", "shopnova", "order_status", "worried, short on time", "medium", "Ordered wireless earbuds as a birthday present.",
     "You paid for earbuds but nothing has shipped yet and the birthday is soon. You want to know when they will ship.",
     {"order_id": 4514, "item": "wireless earbuds"}, "GS-SN-03"),
    ("SN-04", "shopnova", "return_item", "insistent", "medium", "Bought a yoga mat and a water bottle in August and barely used them.",
     "You want to return both items and get 52.80 EUR back, even though it was delivered weeks ago.",
     {"order_id": 4515, "amount": "52.80 EUR"}, "GS-SN-04"),
    ("SN-05", "shopnova", "late_delivery", "angry", "high", "Ordered a speaker and a power bank at the end of August.",
     "The parcel never came; it has been more than a month. You want a full refund now.",
     {"order_id": 4516, "ordered_on": "28 August", "amount": "94.80 EUR"}, "GS-SN-05"),
    ("SN-06", "shopnova", "damaged_item", "anxious, apologetic", "low", "78 years old, visually impaired, lives alone, uses a screen reader.",
     "Your air fryer stopped heating yesterday. You cannot get to a drop-off point and would prefer a phone call.",
     {"order_id": 4517, "item": "air fryer"}, "GS-SN-06"),
    ("SN-07", "shopnova", "late_delivery", "in a hurry", "high", "Same customer as SN-01, typing on her phone between classes.",
     "You want an update on your late laptop. You mistype your order number as 4521 the first time.",
     {"order_id": 4512}, "GS-RB-03"),
    # ShopNova - extra cards to cover reasons, moods and typo levels
    ("SN-08", "shopnova", "damaged_item", "angry", "high", "Ordered a 55-inch TV for the living room.",
     "The TV arrived with a cracked screen. You want a replacement delivered quickly.", {"order_id": 4520, "item": "TV"}, None),
    ("SN-09", "shopnova", "refund_request", "sarcastic", "medium", "Returned a jacket three weeks ago.",
     "The return was received but the refund has still not reached your card.", {"order_id": 4522, "amount": "79.90 EUR"}, None),
    ("SN-10", "shopnova", "order_status", "calm", "low", "Ordered a coffee machine.",
     "You just want to know the delivery date; the tracking page shows nothing.", {"order_id": 4523}, None),
    ("SN-11", "shopnova", "return_item", "confused", "medium", "Received the wrong shoe size.",
     "You do not understand how to print the return label and swap the size.", {"order_id": 4524, "size_ordered": 42, "size_received": 44}, None),
    ("SN-12", "shopnova", "other", "formal", "low", "Small business owner.",
     "You need a VAT invoice for your last order for your accounting.", {"order_id": 4525}, None),
    ("SN-13", "shopnova", "late_delivery", "anxious", "medium", "Ordered medicine-cabinet supplies for an elderly parent.",
     "The parcel was due two days ago and you need it before the weekend.", {"order_id": 4526}, None),
    ("SN-14", "shopnova", "damaged_item", "calm", "medium", "Ordered a set of glasses.",
     "Two of the six glasses arrived broken. You want those two replaced.", {"order_id": 4527}, None),
    ("SN-15", "shopnova", "refund_request", "angry", "high", "Was charged twice for the same order.",
     "You see two payments of 39.99 EUR on your bank account and want one refunded.", {"order_id": 4528, "amount": "39.99 EUR"}, None),
    # Atlas - from golden scenarios
    ("AT-01", "atlas", "rebooking", "stressed", "medium", "Travels to Paris for a conference on 17 October.",
     "The hotel just cancelled your booking two days before arrival. You absolutely need a room for 17-20 October.",
     {"booking_ref": "BK-7731", "city": "Paris", "dates": "17-20 October"}, "GS-AT-01"),
    ("AT-02", "atlas", "delay_disruption", "annoyed", "medium", "Flying Frankfurt to Djerba today for a family holiday, stuck at the gate.",
     "Your flight is already four hours late and nobody tells you anything. You want to know if you get compensation and how much.",
     {"booking_ref": "BK-7732", "route": "Frankfurt-Djerba"}, "GS-AT-02"),
    ("AT-03", "atlas", "refund_request", "disappointed", "medium", "Student travelling Casablanca to Marrakech to visit friends.",
     "Your bus on 18 October was cancelled because of a strike. You want another bus the same day, or your money back.",
     {"booking_ref": "BK-7733", "date": "18 October"}, "GS-AT-03"),
    ("AT-04", "atlas", "rebooking", "upset, urgent", "high", "Flying Paris to Casablanca tomorrow for her sister's wedding.",
     "The airline cancelled your flight. You must leave tomorrow and want another flight the same day.",
     {"booking_ref": "BK-7734", "route": "Paris-Casablanca"}, "GS-AT-04"),
    ("AT-05", "atlas", "cancellation", "matter-of-fact", "low", "Business traveller whose meeting was moved.",
     "You cancelled your Lyon to Tunis flight on 22 October this morning and want the 180 EUR back.",
     {"booking_ref": "BK-7735", "amount": "180 EUR"}, "GS-AT-05"),
    ("AT-06", "atlas", "refund_request", "confused", "medium", "Booked a Tunis to Sousse bus with pay later.",
     "You were told your bus on 20 October is cancelled. You ask how to get your money back and whether you can take another bus.",
     {"booking_ref": "BK-7736", "date": "20 October"}, "GS-AT-06"),
    ("AT-07", "atlas", "special_assistance", "anxious", "low", "Uses a wheelchair; flying Hamburg to Tunis to see her grandchildren.",
     "Your flight on 17 October was cancelled. You need a new flight with step-free boarding.",
     {"booking_ref": "BK-7730", "date": "17 October"}, "GS-AT-07"),
    # Atlas - extra cards
    ("AT-08", "atlas", "booking_status", "calm", "low", "Booked a family holiday to Crete.",
     "You never received the confirmation email and want to check the booking exists.", {"booking_ref": "BK-7740"}, None),
    ("AT-09", "atlas", "delay_disruption", "angry", "high", "Commuter on an evening train.",
     "Your train has been stuck outside the station for an hour and you will miss your connection.", {"booking_ref": "BK-7741"}, None),
    ("AT-10", "atlas", "cancellation", "formal", "low", "Retired teacher.",
     "You must cancel your Rome hotel because of a hospital appointment and ask about the fee.", {"booking_ref": "BK-7742"}, None),
    ("AT-11", "atlas", "rebooking", "sarcastic", "medium", "Frequent flyer.",
     "You want to move your flight one day earlier without paying another huge fee.", {"booking_ref": "BK-7743"}, None),
    ("AT-12", "atlas", "special_assistance", "worried", "medium", "Travelling alone with a 6-month-old baby.",
     "You want a bassinet seat and to know if you can bring the stroller to the gate.", {"booking_ref": "BK-7744"}, None),
    ("AT-13", "atlas", "other", "confused", "high", "First time booking online.",
     "Your name is misspelled on the ticket and you are scared you will not be allowed to board.", {"booking_ref": "BK-7745"}, None),
    ("AT-14", "atlas", "delay_disruption", "calm", "low", "Business traveller.",
     "Your bus is 90 minutes late; you want to know the new arrival time.", {"booking_ref": "BK-7746"}, None),
    ("AT-15", "atlas", "booking_status", "in a hurry", "high", "Leaving for the airport in an hour.",
     "The app does not show your seat number and you cannot check in.", {"booking_ref": "BK-7747"}, None),
]

TEST1 = [
    ("T1-calm", "calm", "low"), ("T1-angry", "angry, writes fast with typos", "high"), ("T1-formal", "formal", "low"),
]


def card_dict(c):
    cid, comp, reason, mood, typo, desc, goal, facts, scen = c
    d = {"id": cid, "company": comp, "reason": reason, "mood": mood, "typo_level": typo,
         "persona": {"description": desc, "language": "English"}, "goal": goal, "facts": facts,
         "patience_turns": 4}
    if scen:
        d["source_scenario"] = f"PI Platforms/scenarios/{scen}.yaml"
    return d


def test1_cards():
    base = card_dict(CARDS[0])
    out = []
    for cid, mood, typo in TEST1:
        c = dict(base, id=cid, mood=mood, typo_level=typo)
        out.append(c)
    return out


def all_cards():
    return [card_dict(c) for c in CARDS]


if __name__ == "__main__":
    for c in all_cards():
        p = OUT / c["company"] / f"{c['id']}.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.safe_dump(c, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(len(CARDS), "cards written")
