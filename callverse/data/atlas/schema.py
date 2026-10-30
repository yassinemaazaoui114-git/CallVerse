"""The tables of the Atlas Travel database (atlas.db) and their allowed codes (task T20).

Same ideas as ShopNova's schema (callverse/data/seed.py):
- every table says where a row comes from: `source`, `source_id`, `ai_generated`, `scripted`;
- the allowed codes below are also enforced by CHECK constraints, so a wrong code cannot be stored;
- `proposals` has ShopNova's columns; the Coordinator uses it since T21 (ids AP-0001, ...). T22 adds the code's own
  confirmation decision (CONFIRMATION_COLUMNS), next to the agent's flag `user_confirmed`, kept for the record;
- `admin_actions`: T22, the same log as ShopNova's: who decided what, when, before / after.

Atlas sells two things, so a refund points at a booking with two columns: `booking_type` + `booking_id`.
"""

from callverse.data.seed import DECISIONS, LABELS, REFUND_STATUSES, _in

# Where a row comes from. The two real datasets are named; see DATA_LICENCES.md.
SOURCES = ("scripted", "hotel_booking_demand", "usdot_2015", "generated")

DEPOSIT_TYPES = ("no_deposit", "refundable", "non_refundable")
HOTEL_BOOKING_STATUSES = ("confirmed", "stayed", "cancelled", "no_show")
FLIGHT_STATUSES = ("scheduled", "on_time", "delayed", "cancelled")
FLIGHT_BOOKING_STATUSES = ("confirmed", "flown", "cancelled")
SEAT_CLASSES = ("economy",)
BOOKING_TYPES = ("hotel", "flight")
ASSISTANCE_STATUSES = ("requested", "confirmed")

# Why a flight was cancelled or late. Used for both cancellation_reason and main_delay_cause.
CAUSES = ("carrier", "weather", "air_system", "security")
# Rule AT-FLT-06: these causes are outside the airline's control, so no compensation is paid.
EXTRAORDINARY_CAUSES = ("weather", "air_system", "security")

SOURCE = f"""
    source    TEXT CHECK (source IS NULL OR source IN {_in(SOURCES)}),  -- NULL = written at run time
    source_id TEXT,                    -- id of the row in the real dataset, NULL otherwise"""

# T22: db.py adds these two to an atlas.db made before T22 (name, SQL type).
CONFIRMATION_COLUMNS = (("confirmed_by_code", "INTEGER CHECK (confirmed_by_code IN (0, 1))"),   # NULL = not checked
                        ("confirmation_reason", "TEXT"))                                        # e.g. "negative sentence"

ADMIN_ACTIONS = """
CREATE TABLE IF NOT EXISTS admin_actions (  -- T22: every decision of the Atlas admin, same columns as ShopNova's
    id           INTEGER PRIMARY KEY,
    at           TEXT NOT NULL,        -- simulation clock, ISO
    admin        TEXT NOT NULL,        -- the admin's username
    action       TEXT NOT NULL,        -- e.g. "approve_compensation", "refuse_refund"
    target_table TEXT NOT NULL,        -- e.g. "compensations"
    target_id    TEXT NOT NULL,        -- the changed row's id
    before       TEXT,                 -- JSON of the row before (NULL for a new row)
    after        TEXT                  -- JSON of the row after
);
"""

SCHEMA = f"""
CREATE TABLE users (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL,
    email TEXT UNIQUE,
    phone TEXT UNIQUE,                 -- +216 XX XXX XXX
    city  TEXT,                        -- one of ShopNova's 8 cities (company_profile.json cities_served){SOURCE},{LABELS}
);
CREATE TABLE hotels (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL,{SOURCE},{LABELS}
);
CREATE TABLE hotel_bookings (
    id                  INTEGER PRIMARY KEY,
    user_id             INTEGER NOT NULL REFERENCES users(id),
    hotel_id            INTEGER NOT NULL REFERENCES hotels(id),
    booked_date         TEXT NOT NULL,     -- ISO dates: YYYY-MM-DD
    arrival_date        TEXT NOT NULL,
    nights              INTEGER NOT NULL CHECK (nights >= 1),
    adults              INTEGER NOT NULL,
    children            INTEGER NOT NULL,
    meal                TEXT NOT NULL,     -- BB, HB, FB or SC (no meal), as in the dataset
    room_reserved       TEXT NOT NULL,     -- room type letter
    room_assigned       TEXT NOT NULL,
    deposit_type        TEXT NOT NULL CHECK (deposit_type IN {_in(DEPOSIT_TYPES)}),
    price_per_night_tnd REAL NOT NULL,
    total_tnd           REAL NOT NULL,     -- price per night x nights
    paid_tnd            REAL NOT NULL,     -- no deposit: 0 until the stay is finished (paid at the hotel)
    status              TEXT NOT NULL CHECK (status IN {_in(HOTEL_BOOKING_STATUSES)}),
    cancelled_date      TEXT,              -- NULL = not cancelled
    special_requests    INTEGER NOT NULL,  -- how many the client asked for{SOURCE},{LABELS}
);
CREATE TABLE flights (
    id                  INTEGER PRIMARY KEY,
    carrier             TEXT NOT NULL,     -- airline code, e.g. AA
    carrier_name        TEXT NOT NULL,
    flight_number       INTEGER NOT NULL,
    origin              TEXT NOT NULL,     -- airport code, e.g. JFK
    origin_city         TEXT NOT NULL,
    destination         TEXT NOT NULL,
    destination_city    TEXT NOT NULL,
    distance_km         REAL NOT NULL,
    scheduled_departure TEXT NOT NULL,     -- YYYY-MM-DD HH:MM
    departure_delay_min INTEGER,           -- NULL = did not depart (or not yet)
    arrival_delay_min   INTEGER,           -- NULL = did not arrive (or not yet)
    cancelled           INTEGER NOT NULL CHECK (cancelled IN (0, 1)),
    cancellation_reason TEXT CHECK (cancellation_reason IS NULL OR cancellation_reason IN {_in(CAUSES)}),
    main_delay_cause    TEXT CHECK (main_delay_cause IS NULL OR main_delay_cause IN {_in(CAUSES)}),
    status              TEXT NOT NULL CHECK (status IN {_in(FLIGHT_STATUSES)}),{SOURCE},{LABELS}
);
CREATE TABLE flight_bookings (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    flight_id   INTEGER NOT NULL REFERENCES flights(id),
    booked_date TEXT NOT NULL,
    seat_class  TEXT NOT NULL CHECK (seat_class IN {_in(SEAT_CLASSES)}),
    price_tnd   REAL NOT NULL,
    paid_tnd    REAL NOT NULL,
    status      TEXT NOT NULL CHECK (status IN {_in(FLIGHT_BOOKING_STATUSES)}),
    notice_days INTEGER,                   -- days of warning before a cancelled flight; NULL = not cancelled{SOURCE},{LABELS}
);
CREATE TABLE refunds (
    id           INTEGER PRIMARY KEY,
    booking_type TEXT NOT NULL CHECK (booking_type IN {_in(BOOKING_TYPES)}),
    booking_id   INTEGER NOT NULL,         -- id in hotel_bookings or flight_bookings
    amount       REAL NOT NULL,            -- TND
    status       TEXT NOT NULL CHECK (status IN {_in(REFUND_STATUSES)}),
    rule_id      TEXT,                     -- policy rule that justified it, e.g. AT-HOT-02
    proposal_id  TEXT,                     -- the agent proposal the Coordinator approved
    created_at   TEXT,{SOURCE},{LABELS}
);
CREATE TABLE compensations (           -- same shape as refunds; empty at seed
    id           INTEGER PRIMARY KEY,
    booking_type TEXT NOT NULL CHECK (booking_type IN {_in(BOOKING_TYPES)}),
    booking_id   INTEGER NOT NULL,
    amount       REAL NOT NULL,
    status       TEXT NOT NULL CHECK (status IN {_in(REFUND_STATUSES)}),
    rule_id      TEXT,
    proposal_id  TEXT,
    created_at   TEXT,{SOURCE},{LABELS}
);
CREATE TABLE assistance_requests (
    id                INTEGER PRIMARY KEY,
    flight_booking_id INTEGER NOT NULL REFERENCES flight_bookings(id),
    kind              TEXT NOT NULL,       -- e.g. wheelchair
    status            TEXT NOT NULL CHECK (status IN {_in(ASSISTANCE_STATUSES)}),
    created_at        TEXT NOT NULL,{SOURCE},{LABELS}
);
CREATE TABLE proposals (               -- same columns as ShopNova's; empty at seed
    id              TEXT PRIMARY KEY,
    agent           TEXT NOT NULL,
    action          TEXT NOT NULL,
    params          TEXT NOT NULL,
    rule_id         TEXT,
    facts_used      TEXT NOT NULL,
    user_confirmed  INTEGER NOT NULL CHECK (user_confirmed IN (0, 1)),
    decision        TEXT CHECK (decision IS NULL OR decision IN {_in(DECISIONS)}),
    decision_reason TEXT,
    created_at      TEXT NOT NULL,
    decided_at      TEXT,{LABELS},
    {', '.join(f"{name} {kind}" for name, kind in CONFIRMATION_COLUMNS)}
);
{ADMIN_ACTIONS}
"""

TABLES = ("users", "hotels", "hotel_bookings", "flights", "flight_bookings", "refunds", "compensations",
          "assistance_requests", "proposals", "admin_actions")
