"""Creates the Atlas Travel SQLite database (callverse/data/atlas.db).

Two kinds of data go in (T20):
1. The SCRIPTED demo data written below by hand: users 1-5 and bookings 7001-7010 (one flight per flight booking,
   with the same id as the booking). It never changes (the tests pin every value).
2. The REAL sample: 2,000 hotel bookings (ids 20001+), 2,000 flights (ids 1+), the flight bookings generated on them
   (ids 30001+), their generated users (ids 101+) and refunds, read from callverse/data/real/atlas_sample.json.
   That file is built by scripts/build_atlas_sample.py and already contains everything, so seeding needs no raw
   data, no random numbers and no network.

Labels: `source`, `source_id`, `ai_generated`, `scripted` (see callverse/data/atlas/schema.py). No code uses this
database yet except the read functions in reads.py.

Run it directly:  python -m callverse.data.atlas.seed
"""

import json
import sqlite3
from functools import lru_cache
from pathlib import Path

from callverse.data.atlas import db
from callverse.data.atlas.schema import SCHEMA
from callverse.data.seed import _insert

SAMPLE_PATH = Path(__file__).resolve().parent.parent / "real" / "atlas_sample.json"

# ---------------------------------------------------------------------------
# SCRIPTED DATA: AI-written demo data (fictional people and trips), source = "scripted".
# Do not change a value: the rule tests in tests/test_atlas_data.py pin them.
# ---------------------------------------------------------------------------

USERS = [
    # (id, name, email, phone, city)
    (1, "Hedi Karoui",  "hedi@example.com",  "+216 20 410 101", "Tunis"),
    (2, "Sonia Belhaj", "sonia@example.com", "+216 22 420 202", "Sfax"),
    (3, "Tarek Mzali",  "tarek@example.com", "+216 24 430 303", "Sousse"),
    (4, "Lobna Cherif", "lobna@example.com", "+216 26 440 404", "Ariana"),
    (5, "Nizar Haddad", "nizar@example.com", "+216 28 450 505", "Bizerte"),
]

HOTEL_BOOKING_COLUMNS = ("id", "user_id", "hotel_id", "booked_date", "arrival_date", "nights", "adults", "children",
                         "meal", "room_reserved", "room_assigned", "deposit_type", "price_per_night_tnd",
                         "total_tnd", "paid_tnd", "status", "cancelled_date", "special_requests")
HOTEL_BOOKINGS = [
    # 7001: no deposit, cancelled before arrival -> free, nothing to refund (AT-HOT-01).
    (7001, 1, 1, "2026-09-20", "2026-10-15", 3, 2, 0, "BB", "A", "A", "no_deposit",
     120.00, 360.00, 0.00, "cancelled", "2026-10-06", 0),
    # 7002: non-refundable, cancelled -> no refund (AT-HOT-03).
    (7002, 2, 2, "2026-09-01", "2026-10-12", 4, 2, 1, "HB", "D", "D", "non_refundable",
     95.00, 380.00, 380.00, "cancelled", "2026-10-05", 1),
    # 7003: stayed in another room than the one booked -> 20 % of the stay, 72.00 TND (AT-HOT-04).
    # Deposit paid, so the refund limit AT-REF-01 leaves room for it.
    (7003, 3, 1, "2026-08-25", "2026-10-01", 3, 2, 0, "BB", "D", "A", "refundable",
     120.00, 360.00, 360.00, "stayed", None, 0),
    # 7009: refundable, cancelled 5 days before arrival, above 300 TND -> needs finance (AT-HOT-02 + AT-ESC-01).
    (7009, 4, 2, "2026-09-10", "2026-10-12", 3, 2, 0, "BB", "E", "E", "refundable",
     150.00, 450.00, 450.00, "cancelled", "2026-10-07", 0),
]

FLIGHT_COLUMNS = ("id", "carrier", "carrier_name", "flight_number", "origin", "origin_city", "destination",
                  "destination_city", "distance_km", "scheduled_departure", "departure_delay_min",
                  "arrival_delay_min", "cancelled", "cancellation_reason", "main_delay_cause", "status")
FLIGHTS = [
    # 7004: arrived 3 h 20 min late, carrier cause -> compensation 839.50 TND (AT-FLT-03).
    (7004, "DL", "Delta Air Lines Inc.", 1204, "JFK", "New York", "ORD", "Chicago", 1190.7,
     "2026-10-05 08:15", 195, 200, 0, None, "carrier", "delayed"),
    # 7005: cancelled, carrier cause, told the same day -> refund or new flight + compensation (AT-FLT-01, AT-FLT-02).
    (7005, "AA", "American Airlines Inc.", 2310, "ATL", "Atlanta", "LAX", "Los Angeles", 3131.1,
     "2026-10-08 14:40", None, None, 1, "carrier", None, "cancelled"),
    # 7006: departed 5 h 30 min late -> may cancel with a full refund (AT-FLT-04). Air-system cause, so no compensation.
    (7006, "UA", "United Air Lines Inc.", 1580, "SFO", "San Francisco", "JFK", "New York", 4160.9,
     "2026-10-07 07:05", 330, 318, 0, None, "air_system", "delayed"),
    # 7007: 1 h late -> no compensation.
    (7007, "WN", "Southwest Airlines Co.", 2211, "BOS", "Boston", "ATL", "Atlanta", 1522.1,
     "2026-10-06 18:20", 60, 60, 0, None, "carrier", "delayed"),
    # 7008: cancelled for weather -> refund or new flight, no compensation (AT-FLT-01, AT-FLT-06).
    (7008, "UA", "United Air Lines Inc.", 905, "DEN", "Denver", "ORD", "Chicago", 1428.8,
     "2026-10-07 16:55", None, None, 1, "weather", None, "cancelled"),
    # 7010: future flight with a wheelchair request (AT-AST-01; for agent C later).
    (7010, "AA", "American Airlines Inc.", 118, "LAX", "Los Angeles", "MIA", "Miami", 3768.3,
     "2026-10-20 11:30", None, None, 0, None, None, "scheduled"),
]

FLIGHT_BOOKING_COLUMNS = ("id", "user_id", "flight_id", "booked_date", "seat_class", "price_tnd", "paid_tnd",
                          "status", "notice_days")
FLIGHT_BOOKINGS = [
    (7004, 5, 7004, "2026-09-02", "economy", 700.00, 700.00, "flown", None),
    (7005, 1, 7005, "2026-09-05", "economy", 1500.00, 1500.00, "cancelled", 0),
    (7006, 2, 7006, "2026-09-12", "economy", 1900.00, 1900.00, "flown", None),
    (7007, 3, 7007, "2026-09-15", "economy", 800.00, 800.00, "flown", None),
    (7008, 4, 7008, "2026-09-18", "economy", 690.00, 690.00, "cancelled", 0),
    (7010, 5, 7010, "2026-10-01", "economy", 1700.00, 1700.00, "confirmed", None),
]

ASSISTANCE_REQUESTS = [
    # (id, flight_booking_id, kind, status, created_at)
    (1, 7010, "wheelchair", "requested", "2026-10-08"),
]


@lru_cache(maxsize=1)
def load_sample() -> dict:
    """The real Atlas sample (all tables), read once from its JSON file."""
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


def _insert_scripted(con: sqlite3.Connection, table: str, columns: tuple, rows: list[tuple]) -> None:
    """Insert hand-written rows, all labelled source = 'scripted', ai_generated = 1, scripted = 1."""
    con.executemany(f"INSERT INTO {table} ({', '.join(columns)}, source, ai_generated, scripted)"
                    f" VALUES ({', '.join('?' * len(columns))}, 'scripted', 1, 1)", rows)


def seed(db_path: Path | None = None) -> Path:
    """(Re)create the database file from scratch with the scripted and the real data. Returns its path.

    Without db_path, the file in use (db.db_path()) is rebuilt.
    """
    db_path = Path(db_path) if db_path else db.db_path()
    if db_path.exists():
        db_path.unlink()  # start clean every time, so the data is always the same

    con = sqlite3.connect(db_path)
    try:
        con.executescript(SCHEMA)
        _insert_scripted(con, "users", ("id", "name", "email", "phone", "city"), USERS)
        _insert_scripted(con, "hotel_bookings", HOTEL_BOOKING_COLUMNS, HOTEL_BOOKINGS)
        _insert_scripted(con, "flights", FLIGHT_COLUMNS, FLIGHTS)
        _insert_scripted(con, "flight_bookings", FLIGHT_BOOKING_COLUMNS, FLIGHT_BOOKINGS)
        _insert_scripted(con, "assistance_requests",
                         ("id", "flight_booking_id", "kind", "status", "created_at"), ASSISTANCE_REQUESTS)

        # Real data: every row of the sample file already carries its labels; refunds get their ids from SQLite.
        sample = load_sample()
        for table in ("users", "hotels", "hotel_bookings", "flights", "flight_bookings", "refunds"):
            _insert(con, table, sample[table])
        con.commit()
    finally:
        con.close()
    return db_path


if __name__ == "__main__":
    print(f"Database created: {seed()}")
