"""Atlas Travel READ functions: they look up facts in atlas.db. They never change anything (T20).

T21: callverse/tools/atlas_tools.py gives them to the agents as tools, through the allow-lists of the registry. Their
results are what a tool may show: the names of the facts match the conditions in callverse/kb/policies_atlas.json, and
the fields in HIDDEN below (where a row comes from, the client's city, how they pay) are removed from every result.
If nothing is found they return {"error": ...}, like ShopNova's read tools.
"""

from collections import Counter
from contextlib import closing
from datetime import date, datetime, time

from callverse.config import sim_today
from callverse.data.atlas.db import connect
from callverse.data.atlas.schema import BOOKING_TYPES
from callverse.data.seed import COUNTED_REFUND_STATUSES

HIDDEN = ("source", "source_id", "ai_generated", "scripted", "city", "payment", "payment_method")


def _public(row) -> dict:
    """A database row as a dict, without the HIDDEN fields."""
    return {k: v for k, v in dict(row).items() if k not in HIDDEN}


def _fetch(sql: str, *params) -> list:
    """Run one SELECT and return its rows; closing() closes the file after use (important on Windows)."""
    with closing(connect()) as con:
        return con.execute(sql, params).fetchall()


def get_user(email: str | None = None, phone: str | None = None, user_id: int | None = None) -> dict:
    """Find a client by email, phone or user id (give one of them)."""
    if user_id is not None:
        column, value = "id", int(user_id)
    elif email:
        column, value = "email", email.strip().lower()
    elif phone:
        column, value = "phone", phone.strip()
    else:
        return {"error": "give an email, a phone or a user_id"}
    # column comes from our own fixed list above, never from the user, so this is safe.
    rows = _fetch(f"SELECT * FROM users WHERE {column} = ?", value)
    return _public(rows[0]) if rows else {"error": "user not found"}


def get_refunds(booking_type: str, booking_id: int) -> dict:
    """The refunds of a booking and how much was already given back (rule AT-REF-01 uses refunded_total)."""
    if booking_type not in BOOKING_TYPES:
        return {"error": f"booking_type must be one of {list(BOOKING_TYPES)}"}
    rows = _fetch("SELECT * FROM refunds WHERE booking_type = ? AND booking_id = ? ORDER BY id",
                  booking_type, int(booking_id))
    refunds = [_public(r) for r in rows]
    total = sum(r["amount"] for r in refunds if r["status"] in COUNTED_REFUND_STATUSES)
    return {"booking_type": booking_type, "booking_id": int(booking_id), "refunds": refunds,
            "refunded_total": round(total, 2)}


def get_hotel_booking(booking_id: int) -> dict:
    """One hotel booking with the facts the rules need.

    days_before_arrival = arrival_date - cancelled_date (None if not cancelled);
    room_changed = the room assigned is not the one reserved;
    hours_before_arrival = from the start of today in the simulation to the arrival date (negative for a past stay).
    """
    rows = _fetch("SELECT b.*, h.name AS hotel_name FROM hotel_bookings b JOIN hotels h ON h.id = b.hotel_id"
                  " WHERE b.id = ?", int(booking_id))
    if not rows:
        return {"error": f"hotel booking {booking_id} not found"}
    booking = _public(rows[0])
    cancelled = booking["cancelled_date"]
    booking["days_before_arrival"] = (
        (date.fromisoformat(booking["arrival_date"]) - date.fromisoformat(cancelled)).days if cancelled else None)
    booking["room_changed"] = booking["room_assigned"] != booking["room_reserved"]
    booking["hours_before_arrival"] = (date.fromisoformat(booking["arrival_date"]) - sim_today()).days * 24
    booking["refunded_total"] = get_refunds("hotel", booking["id"])["refunded_total"]
    return booking


def get_flight(flight_id: int) -> dict:
    """One flight: route, distance, schedule, real delays, cancellation and cause."""
    rows = _fetch("SELECT * FROM flights WHERE id = ?", int(flight_id))
    return _public(rows[0]) if rows else {"error": f"flight {flight_id} not found"}


def get_flight_booking(booking_id: int) -> dict:
    """One flight booking with its flight's facts, in one flat dict (so a rule condition can read them directly).

    `status` is the booking's, `flight_status` the flight's. hours_before_departure counts from the start of
    today in the simulation (negative for a past flight; rule AT-AST-01 uses it).
    """
    rows = _fetch("SELECT * FROM flight_bookings WHERE id = ?", int(booking_id))
    if not rows:
        return {"error": f"flight booking {booking_id} not found"}
    booking = _public(rows[0])
    flight = get_flight(booking["flight_id"])
    flight.pop("id")
    flight["flight_status"] = flight.pop("status")
    departure = datetime.fromisoformat(flight["scheduled_departure"])
    start_of_today = datetime.combine(sim_today(), time.min)
    return {**booking, **flight,
            "hours_before_departure": round((departure - start_of_today).total_seconds() / 3600, 2),
            "refunded_total": get_refunds("flight", booking["id"])["refunded_total"]}


def booking_type(booking_id: int) -> str | None:
    """"hotel" or "flight" for a booking number, None if it is neither. The client only gives a number: this lookup
    says which table it is in (the ids are unique across the two tables, a test checks it)."""
    if _fetch("SELECT 1 FROM hotel_bookings WHERE id = ?", int(booking_id)):
        return "hotel"
    if _fetch("SELECT 1 FROM flight_bookings WHERE id = ?", int(booking_id)):
        return "flight"
    return None


def find_booking(booking_id: int) -> dict:
    """A booking of either type, with its booking_type, or {"error": ...}."""
    kind = booking_type(booking_id)
    if kind is None:
        return {"error": f"booking {booking_id} not found"}
    read = get_hotel_booking if kind == "hotel" else get_flight_booking
    return {"booking_type": kind, **read(booking_id)}


def get_compensations(booking_type: str, booking_id: int) -> dict:
    """The compensations of a booking and their total (a compensation is paid once per booking)."""
    rows = _fetch("SELECT * FROM compensations WHERE booking_type = ? AND booking_id = ? ORDER BY id",
                  booking_type, int(booking_id))
    compensations = [_public(r) for r in rows]
    total = sum(r["amount"] for r in compensations if r["status"] in COUNTED_REFUND_STATUSES)
    return {"booking_type": booking_type, "booking_id": int(booking_id), "compensations": compensations,
            "compensated_total": round(total, 2)}


def user_bookings(user_id: int) -> dict:
    """All the hotel and flight bookings of one client."""
    hotel = _fetch("SELECT id FROM hotel_bookings WHERE user_id = ? ORDER BY id", int(user_id))
    flight = _fetch("SELECT id FROM flight_bookings WHERE user_id = ? ORDER BY id", int(user_id))
    return {"user_id": int(user_id),
            "hotel_bookings": [get_hotel_booking(r["id"]) for r in hotel],
            "flight_bookings": [get_flight_booking(r["id"]) for r in flight]}


def summary() -> dict:
    """The whole company in numbers: counts by status, delay and cancellation rates, money totals."""
    with closing(connect()) as con:
        hotel = con.execute("SELECT status, total_tnd, paid_tnd FROM hotel_bookings").fetchall()
        flights = con.execute("SELECT status FROM flights").fetchall()
        bookings = con.execute("SELECT status, paid_tnd FROM flight_bookings").fetchall()
        refunds = con.execute("SELECT COUNT(*) AS n, COALESCE(SUM(amount), 0) AS total FROM refunds").fetchone()
    flight_status = Counter(r["status"] for r in flights)
    past = sum(n for status, n in flight_status.items() if status != "scheduled")
    return {
        "hotel_bookings": dict(Counter(r["status"] for r in hotel)),
        "flights": dict(flight_status),
        "flight_bookings": dict(Counter(r["status"] for r in bookings)),
        "flight_delay_rate": round(flight_status["delayed"] / past, 4),
        "flight_cancellation_rate": round(flight_status["cancelled"] / past, 4),
        "hotel_total_tnd": round(sum(r["total_tnd"] for r in hotel), 2),
        "hotel_paid_tnd": round(sum(r["paid_tnd"] for r in hotel), 2),
        "flight_paid_tnd": round(sum(r["paid_tnd"] for r in bookings), 2),
        "refunds": refunds["n"],
        "refunded_tnd": round(refunds["total"], 2),
    }
