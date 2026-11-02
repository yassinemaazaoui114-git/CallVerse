"""Atlas Travel customer reads for the API (step 5): wrappers around the functions the Streamlit "My bookings"
page uses. Like shop_reads.py for ShopNova.

- the list: callverse.data.atlas.atlas_app_reads.my_bookings(user_id) (flights and hotel stays in plain words,
  each with its refunds and compensations) — the user id comes from the accounts file, never from the browser;
- one booking: the same list filtered on the TYPE and the id, so a booking of another client, a wrong type or a
  missing id are all "not found" (nothing tells a client whether a number exists);
- then, for an owned booking only, the agents' read (reads.get_flight_booking / get_hotel_booking, which already
  hide the internal fields) for the facts the rules use, and the money reads.
No SQL and no business rule here; statuses, causes and dates pass through as the database holds them.
"""

from callverse.config import sim_today
from callverse.data.atlas import atlas_app_reads, reads

KINDS = ("flight", "hotel")


def bookings(user_id: int) -> dict:
    """The customer's bookings: {flights, hotels, sim_today}. Each row = atlas_app_reads.my_bookings as it is."""
    found = atlas_app_reads.my_bookings(user_id)
    return {"flights": found["flights"], "hotels": found["hotels"],
            "count": len(found["flights"]) + len(found["hotels"]), "sim_today": sim_today().isoformat()}


def owned(user_id: int, kind: str, booking_id: int) -> dict | None:
    """The customer's booking of this TYPE and id (the My bookings row), or None."""
    if kind not in KINDS:
        return None
    found = atlas_app_reads.my_bookings(user_id)
    rows = found["flights"] if kind == "flight" else found["hotels"]
    return next((b for b in rows if b["id"] == int(booking_id)), None)


def owned_any(user_id: int, booking_id: int) -> dict | None:
    """The customer's booking of either type with this id (the chat's "about this booking" check), or None."""
    for kind in KINDS:
        row = owned(user_id, kind, booking_id)
        if row is not None:
            return {"kind": kind, **row}
    return None


def booking(user_id: int, kind: str, booking_id: int) -> dict | None:
    """One OWNED booking with the facts and the money, or None (missing / wrong type / someone else's)."""
    row = owned(user_id, kind, booking_id)
    if row is None:
        return None
    facts = (reads.get_flight_booking if kind == "flight" else reads.get_hotel_booking)(row["id"])
    return {"kind": kind, "booking": row, "facts": None if "error" in facts else facts,
            "refunds": reads.get_refunds(kind, row["id"]), "compensations": reads.get_compensations(kind, row["id"]),
            "sim_today": sim_today().isoformat()}
