"""Atlas hotel capacity READS for Agent D (P20). Read only.

The Atlas data (Hotel Booking Demand, real) has bookings but NO room count per hotel. Nothing is invented here: the
capacity is DERIVED from the data itself.
    rooms occupied on a night = bookings that hold a room that night (arrival_date <= night < arrival + nights);
        past nights: "stayed" and "no_show" bookings (a no-show still held the room); coming nights: "confirmed"
    capacity of a hotel       = the most rooms it ever had occupied on one past night (observed peak). A real hotel
                                has at least that many rooms, so this is a safe, data-based lower bound.
    occupancy_pct             = rooms occupied / capacity x 100, for the coming nights (HORIZON_DAYS)
Rules (policies_atlas.json): AT-CAP-01 overbooking risk (a coming night is fuller than the capacity), AT-DEAL-01 a
deal for a hotel with nights at 30 % occupancy or less (the owner approves).
"""

from contextlib import closing
from datetime import date, timedelta

from callverse.config import sim_today
from callverse.data.atlas.db import connect

HORIZON_DAYS = 30
PAST_STATUSES = ("stayed", "no_show")
COMING_STATUSES = ("confirmed",)


def _nights(arrival: str, nights: int):
    first = date.fromisoformat(arrival)
    return (first + timedelta(days=i) for i in range(int(nights)))


def occupancy(con, hotel_id: int) -> tuple[dict[date, int], dict[date, int]]:
    """(rooms occupied per PAST night, rooms booked per COMING night) of one hotel."""
    today = sim_today()
    past, coming = {}, {}
    for r in con.execute("SELECT arrival_date, nights, status FROM hotel_bookings WHERE hotel_id = ?", (hotel_id,)):
        for night in _nights(r["arrival_date"], r["nights"]):
            if night < today and r["status"] in PAST_STATUSES:
                past[night] = past.get(night, 0) + 1
            elif today <= night < today + timedelta(days=HORIZON_DAYS) and r["status"] in COMING_STATUSES:
                coming[night] = coming.get(night, 0) + 1
    return past, coming


def hotel_capacity_report() -> list[dict]:
    """Per hotel: derived capacity and the coming nights' occupancy (Agent D's Atlas scan)."""
    today = sim_today()
    out = []
    with closing(connect()) as con:
        hotels = [dict(r) for r in con.execute("SELECT id, name FROM hotels ORDER BY id")]
        for h in hotels:
            past, coming = occupancy(con, h["id"])
            capacity = max(past.values(), default=0)
            nights = [{"night": (today + timedelta(days=i)).isoformat(),
                       "rooms_booked": coming.get(today + timedelta(days=i), 0)} for i in range(HORIZON_DAYS)]
            for n in nights:
                n["occupancy_pct"] = round(100 * n["rooms_booked"] / capacity, 1) if capacity else None
            out.append({"hotel_id": h["id"], "name": h["name"], "capacity": capacity,
                        "capacity_source": "peak rooms occupied on one past night (derived from the bookings)",
                        "nights": nights,
                        "overbooked_nights": [n["night"] for n in nights if capacity and n["rooms_booked"] > capacity],
                        "low_nights": [n["night"] for n in nights if n["occupancy_pct"] is not None
                                       and n["occupancy_pct"] <= 30],
                        "min_occupancy_pct": min((n["occupancy_pct"] for n in nights if n["occupancy_pct"] is not None),
                                                 default=None),
                        "max_rooms_booked": max((n["rooms_booked"] for n in nights), default=0)})
    return out


def hotel_facts(hotel_id: int) -> dict:
    """The capacity facts of one hotel, or {"error": ...}."""
    for h in hotel_capacity_report():
        if h["hotel_id"] == hotel_id:
            return h
    return {"error": f"hotel {hotel_id} not found"}
