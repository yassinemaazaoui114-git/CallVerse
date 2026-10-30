"""Read-only views of Atlas data for the ATLAS APP (T22): My bookings, the Admin dashboard, Approvals and Records.

Like ShopNova's shop_reads.py and admin_reads.py: NOT agent tools, nothing here writes. The agents' reads are in
reads.py; here the same facts are put in plain words for a page.

Dashboard period: the last 7 / 30 days, or all, counted back from the simulation clock's today (sim_today), so the
numbers follow the demo date. A booking belongs to the period by its booked date, a flight by its departure date,
a refund or a compensation by the date it was written.
"""

from contextlib import closing
from datetime import timedelta

from callverse.config import sim_today
from callverse.data.admin_reads import PAGE_SIZE, _matches, _page  # noqa: F401 (PAGE_SIZE: for the Records page)
from callverse.data.atlas import reads, writes
from callverse.data.atlas.db import connect
from callverse.data.seed import COUNTED_REFUND_STATUSES
from callverse.kb.policies import get_policy

COMPANY = "atlas"
PERIODS = {"Last 7 days": 7, "Last 30 days": 30, "All": None}
DEFAULT_PERIOD = "All"
UPCOMING_DAYS = 14

DEPOSIT_WORDS = {"no_deposit": "no deposit (pay at the hotel)", "refundable": "refundable deposit",
                 "non_refundable": "non-refundable"}
HOTEL_STATUS_WORDS = {"confirmed": "confirmed", "stayed": "stayed", "cancelled": "cancelled", "no_show": "no-show"}
CAUSE_WORDS = {"carrier": "the airline", "weather": "weather", "air_system": "air traffic control",
               "security": "security"}
FLIGHT_STATUS_WORDS = {"scheduled": "scheduled", "on_time": "on time"}


# ---------- My bookings ----------

def _money(booking_type: str, booking_id: int) -> dict:
    """A booking's refunds and compensation, as My bookings shows them under the booking."""
    return {"refunds": reads.get_refunds(booking_type, booking_id)["refunds"],
            "compensations": reads.get_compensations(booking_type, booking_id)["compensations"]}


def flight_situation(flight: dict) -> str:
    """What happened to the flight, in plain words: "delayed 200 minutes (the airline)", "cancelled (weather)"..."""
    status = flight["flight_status"]
    if status == "cancelled":
        return f"cancelled ({CAUSE_WORDS.get(flight['cancellation_reason'], 'cause not known')})"
    if status == "delayed":
        minutes = flight["arrival_delay_min"] if flight["arrival_delay_min"] is not None else flight["departure_delay_min"]
        return f"delayed {minutes} minutes ({CAUSE_WORDS.get(flight['main_delay_cause'], 'cause not known')})"
    return FLIGHT_STATUS_WORDS.get(status, status)


def my_bookings(user_id: int) -> dict:
    """The bookings of ONE user: {"flights": [...], "hotels": [...]}. The user id comes from the accounts file."""
    found = reads.user_bookings(user_id)
    flights = [{"id": b["id"], "route": f"{b['origin_city']} ({b['origin']}) → {b['destination_city']} ({b['destination']})",
                "airline": b["carrier_name"], "flight_number": f"{b['carrier']} {b['flight_number']}",
                "departure": b["scheduled_departure"], "situation": flight_situation(b), "paid": b["paid_tnd"],
                **_money("flight", b["id"])} for b in found["flight_bookings"]]
    hotels = [{"id": b["id"], "hotel": b["hotel_name"], "arrival": b["arrival_date"], "nights": b["nights"],
               "room_booked": b["room_reserved"], "room_given": b["room_assigned"],
               "deposit": DEPOSIT_WORDS.get(b["deposit_type"], b["deposit_type"]), "total": b["total_tnd"],
               "paid": b["paid_tnd"], "status": HOTEL_STATUS_WORDS.get(b["status"], b["status"]),
               **_money("hotel", b["id"])} for b in found["hotel_bookings"]]
    return {"flights": flights, "hotels": hotels}


# ---------- Admin dashboard ----------

def _period_start(days: int | None) -> str:
    """First day of the period (today included); the very beginning for "all"."""
    return "0000-01-01" if days is None else (sim_today() - timedelta(days=days - 1)).isoformat()


def _rate(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def _by_status(rows: list) -> list[dict]:
    return [{"status": r["status"], "bookings": r["n"]} for r in rows]


def _paid(con, table: str, start: str, today: str) -> dict:
    """{count, tnd} of a money table in the period (table: our own two names)."""
    marks = ", ".join("?" for _ in COUNTED_REFUND_STATUSES)
    row = con.execute(f"SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM {table} WHERE status IN ({marks})"
                      " AND created_at BETWEEN ? AND ?", (*COUNTED_REFUND_STATUSES, start, today)).fetchone()
    return {"count": row[0], "tnd": round(row[1], 2)}


def dashboard(days: int | None = None) -> dict:
    """Everything the Admin dashboard shows for the period (7, 30 or None = all)."""
    start, today = _period_start(days), sim_today().isoformat()
    last = (sim_today() + timedelta(days=UPCOMING_DAYS)).isoformat()
    period = (start, today)
    with closing(connect()) as con:
        hotel = con.execute("SELECT status, COUNT(*) AS n FROM hotel_bookings WHERE booked_date BETWEEN ? AND ?"
                            " GROUP BY status ORDER BY n DESC", period).fetchall()
        flight = con.execute("SELECT status, COUNT(*) AS n FROM flight_bookings WHERE booked_date BETWEEN ? AND ?"
                             " GROUP BY status ORDER BY n DESC", period).fetchall()
        flights = {r["status"]: r["n"] for r in con.execute(
            "SELECT status, COUNT(*) AS n FROM flights WHERE substr(scheduled_departure, 1, 10) BETWEEN ? AND ?"
            " AND status != 'scheduled' GROUP BY status", period).fetchall()}
        refunds, compensations = _paid(con, "refunds", start, today), _paid(con, "compensations", start, today)
        arrivals = [dict(r) for r in con.execute(
            "SELECT b.id, u.name AS client, h.name AS hotel, b.arrival_date, b.nights FROM hotel_bookings b"
            " JOIN users u ON u.id = b.user_id JOIN hotels h ON h.id = b.hotel_id WHERE b.status = 'confirmed'"
            " AND b.arrival_date BETWEEN ? AND ? ORDER BY b.arrival_date, b.id", (today, last)).fetchall()]
        departures = [dict(r) for r in con.execute(
            "SELECT b.id, u.name AS client, f.origin_city AS origin, f.destination_city AS destination,"
            " f.scheduled_departure FROM flight_bookings b JOIN users u ON u.id = b.user_id"
            " JOIN flights f ON f.id = b.flight_id WHERE b.status = 'confirmed'"
            " AND substr(f.scheduled_departure, 1, 10) BETWEEN ? AND ? ORDER BY f.scheduled_departure, b.id",
            (today, last)).fetchall()]
    hotel_total = sum(r["n"] for r in hotel)
    flown = sum(flights.values())
    return {"start": start if days else None, "today": today, "upcoming_until": last,
            "hotel_by_status": _by_status(hotel), "flight_by_status": _by_status(flight),
            "hotel_bookings": hotel_total, "flight_bookings": sum(r["n"] for r in flight),
            "hotel_cancellation_rate": _rate(sum(r["n"] for r in hotel if r["status"] == "cancelled"), hotel_total),
            "flights": flown, "flight_delay_rate": _rate(flights.get("delayed", 0), flown),
            "flight_cancellation_rate": _rate(flights.get("cancelled", 0), flown),
            "refunds_paid": refunds, "compensation_paid": compensations,
            "upcoming_arrivals": arrivals, "upcoming_departures": departures}


# ---------- Approvals ----------

def approval_facts(approval: dict) -> dict:
    """What the Approvals page shows next to an approval: the client's name, the rule, the agent's facts and the
    code's confirmation decision. approval = a row of store.approvals, always one of Atlas's."""
    booking = reads.find_booking(approval["order_id"])
    user = reads.get_user(user_id=booking["user_id"]) if "error" not in booking else {}
    proposal = writes.get_proposal(approval["proposal_id"]) or {}
    rule = get_policy(proposal["rule_id"], COMPANY) if proposal.get("rule_id") else None
    return {"user_name": user.get("name"), "booking_status": booking.get("status"), "rule_id": proposal.get("rule_id"),
            "rule_title": rule["title"] if rule else None, "facts_used": proposal.get("facts_used", {}),
            "confirmation": reads.confirmation_words(proposal.get("confirmed_by_code"),
                                                     proposal.get("confirmation_reason"))}


# ---------- Records (search box + 50 rows per page, view only) ----------

def _rows(sql: str) -> list[dict]:
    with closing(connect()) as con:
        return [dict(r) for r in con.execute(sql).fetchall()]


def hotel_bookings_page(search: str = "", page: int = 1) -> dict:
    """Hotel bookings, newest first. Search: booking id, client, hotel or status."""
    rows = _rows("SELECT b.id, b.user_id, u.name AS client, h.name AS hotel, b.booked_date, b.arrival_date, b.nights,"
                 " b.deposit_type, b.total_tnd, b.paid_tnd, b.status, b.cancelled_date, b.source FROM hotel_bookings b"
                 " JOIN users u ON u.id = b.user_id JOIN hotels h ON h.id = b.hotel_id"
                 " ORDER BY b.booked_date DESC, b.id DESC")
    return _page([r for r in rows if _matches(search, r["id"], r["client"], r["hotel"], r["status"])], page)


def flight_bookings_page(search: str = "", page: int = 1) -> dict:
    """Flight bookings, newest first. Search: booking id, client, route, airline or status."""
    rows = _rows("SELECT b.id, b.user_id, u.name AS client, f.carrier_name AS airline, f.flight_number,"
                 " f.origin_city AS origin, f.destination_city AS destination, f.scheduled_departure,"
                 " f.status AS flight_status, b.price_tnd, b.paid_tnd, b.status, b.source FROM flight_bookings b"
                 " JOIN users u ON u.id = b.user_id JOIN flights f ON f.id = b.flight_id"
                 " ORDER BY b.booked_date DESC, b.id DESC")
    return _page([r for r in rows if _matches(search, r["id"], r["client"], r["origin"], r["destination"],
                                              r["airline"], r["status"])], page)


def users_page(search: str = "", page: int = 1) -> dict:
    rows = _rows("SELECT id, name, email, phone, city, source FROM users ORDER BY id")
    return _page([r for r in rows if _matches(search, r["id"], r["name"], r["email"], r["phone"], r["city"])], page)


def _money_page(table: str, search: str, page: int) -> dict:
    """Newest first. Search: row id, booking id, status or rule. table: our own two names."""
    rows = _rows(f"SELECT id, booking_type, booking_id, amount, status, rule_id, proposal_id, created_at, source"
                 f" FROM {table} ORDER BY id DESC")
    return _page([r for r in rows if _matches(search, r["id"], r["booking_id"], r["status"], r["rule_id"])], page)


def refunds_page(search: str = "", page: int = 1) -> dict:
    return _money_page("refunds", search, page)


def compensations_page(search: str = "", page: int = 1) -> dict:
    return _money_page("compensations", search, page)


def admin_log(limit: int = 50) -> list[dict]:
    """The last Atlas admin actions, newest first."""
    with closing(connect()) as con:
        return [dict(r) for r in con.execute("SELECT * FROM admin_actions ORDER BY id DESC LIMIT ?",
                                             (int(limit),)).fetchall()]
