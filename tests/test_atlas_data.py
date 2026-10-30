"""Atlas Travel's company data (T20): schema, counts, labels, dates, money, rules, read functions, the builder.

Everything runs offline on the committed sample: no raw file, no API. The builder is tested on tiny fake raw files.
"""

import csv
import json
import random
import re
import sqlite3
from datetime import date, datetime, timedelta

import pytest

from callverse.data.atlas import db as atlas_db
from callverse.data.atlas import reads
from callverse.data.atlas import schema
from callverse.data.atlas.seed import ASSISTANCE_REQUESTS, SAMPLE_PATH, load_sample, seed
from callverse.kb.policies import POLICIES_PATH, check_condition, load_policies
from scripts import build_atlas_sample as builder

TODAY = date(2026, 10, 9)
POLICIES = {r["id"]: r for r in load_policies(POLICIES_PATH.parent / "policies_atlas.json")}
PROFILE = json.loads((SAMPLE_PATH.parent.parent / "atlas_profile.json").read_text(encoding="utf-8"))
REAL_HOTELS = "source = 'hotel_booking_demand'"


@pytest.fixture(scope="module", autouse=True)
def atlas_database(tmp_path_factory):
    """One seeded Atlas database for this file. The real atlas.db is never touched."""
    path = tmp_path_factory.mktemp("atlas") / "atlas_test.db"
    seed(path)
    atlas_db.use_db(path)
    yield
    atlas_db.use_db(atlas_db.DEFAULT_DB_PATH)


def _q(sql: str, *params) -> list:
    con = atlas_db.connect()
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def _count(table: str, where: str = "1 = 1") -> int:
    return _q(f"SELECT COUNT(*) FROM {table} WHERE {where}")[0][0]


def rule(rule_id: str, facts: dict) -> bool:
    return check_condition(POLICIES[rule_id]["condition"], facts)


def true_rules(prefix: str, facts: dict) -> set:
    """The rules of one family that hold for these facts."""
    return {i for i in POLICIES if i.startswith(prefix) and rule(i, facts)}


# ---- Schema and allowed codes ----------------------------------------------------------------------------------

def test_all_tables_exist():
    names = {r[0] for r in _q("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert names == set(schema.TABLES)


@pytest.mark.parametrize("table", [t for t in schema.TABLES if t != "proposals"])
def test_every_table_has_the_labels(table):
    columns = {r[1] for r in _q(f"PRAGMA table_info({table})")}
    assert {"source", "source_id", "ai_generated", "scripted"} <= columns


def test_proposals_have_the_same_columns_as_shopnova():
    con = sqlite3.connect(":memory:")
    from callverse.data.seed import SCHEMA as SHOPNOVA_SCHEMA
    con.executescript(SHOPNOVA_SCHEMA)
    shopnova = [r[1] for r in con.execute("PRAGMA table_info(proposals)")]
    con.close()
    assert [r[1] for r in _q("PRAGMA table_info(proposals)")] == shopnova


@pytest.mark.parametrize("table, column, allowed", [
    ("hotel_bookings", "status", schema.HOTEL_BOOKING_STATUSES),
    ("hotel_bookings", "deposit_type", schema.DEPOSIT_TYPES),
    ("flights", "status", schema.FLIGHT_STATUSES),
    ("flights", "cancellation_reason", schema.CAUSES + (None,)),
    ("flights", "main_delay_cause", schema.CAUSES + (None,)),
    ("flight_bookings", "status", schema.FLIGHT_BOOKING_STATUSES),
    ("flight_bookings", "seat_class", schema.SEAT_CLASSES),
])
def test_codes_in_the_data_are_allowed(table, column, allowed):
    assert {r[0] for r in _q(f"SELECT DISTINCT {column} FROM {table}")} <= set(allowed)


def test_wrong_code_is_refused(tmp_path):
    con = sqlite3.connect(seed(tmp_path / "copy.db"))
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("UPDATE hotel_bookings SET status = 'lost' WHERE id = 7001")
    con.close()


# ---- Counts and labels -----------------------------------------------------------------------------------------

def test_counts():
    assert _count("hotel_bookings", REAL_HOTELS) == 2000
    assert _count("flights", "source = 'usdot_2015'") == 2000
    assert _count("flight_bookings", "source = 'generated'") == 2000
    assert _count("hotel_bookings", "scripted = 1") + _count("flight_bookings", "scripted = 1") == 10
    assert _count("users", "scripted = 1") == 5
    assert _count("users") == 4005
    assert _count("hotels") == 2


def test_empty_at_seed():
    assert _count("compensations") == 0
    assert _count("proposals") == 0


def test_real_rows_keep_their_source():
    assert _count("hotel_bookings", f"{REAL_HOTELS} AND ai_generated = 0 AND source_id IS NOT NULL") == 2000
    assert _count("flights", "source = 'usdot_2015' AND ai_generated = 0 AND source_id IS NOT NULL") == 2000
    assert _q("SELECT MIN(id), MAX(id) FROM hotel_bookings WHERE source != 'scripted'")[0][:2] == (20001, 22000)
    assert _q("SELECT MIN(id), MAX(id) FROM flights WHERE source != 'scripted'")[0][:2] == (1, 2000)
    # the flight's source_id = carrier + flight number + original date
    assert all(re.fullmatch(r"[A-Z0-9]{2}\d+-2015-\d\d-\d\d", r[0]) for r in _q(
        "SELECT source_id FROM flights WHERE source = 'usdot_2015'"))
    # the hotel's source_id = the CSV row number, each one once
    assert _q("SELECT COUNT(DISTINCT source_id) FROM hotel_bookings WHERE " + REAL_HOTELS)[0][0] == 2000


def test_generated_rows_are_labelled():
    assert _q("SELECT MIN(id), MAX(id) FROM flight_bookings WHERE source = 'generated'")[0][:2] == (30001, 32000)
    assert _count("users", "ai_generated = 0") == 0
    assert _count("flight_bookings", "ai_generated = 0") == 0
    assert _q("SELECT MIN(id), MAX(id) FROM users WHERE source = 'generated'")[0][:2] == (101, 4100)
    assert _count("hotels", "ai_generated = 1") == 2
    assert _count("refunds", "ai_generated = 0") == 0


def test_each_generated_user_has_exactly_one_booking():
    hotel = {r[0] for r in _q("SELECT user_id FROM hotel_bookings WHERE " + REAL_HOTELS)}
    flight = {r[0] for r in _q("SELECT user_id FROM flight_bookings WHERE source = 'generated'")}
    assert len(hotel) == 2000 and len(flight) == 2000 and not hotel & flight


def test_users_look_tunisian_and_are_unique():
    cities = set(PROFILE["cities_served"])
    rows = _q("SELECT name, email, phone, city FROM users")
    assert len(cities) == 8 and {r["city"] for r in rows} <= cities
    assert all(re.fullmatch(r"\+216 \d\d \d{3} \d{3}", r["phone"]) for r in rows)
    assert len({r["email"] for r in rows}) == len(rows) and len({r["phone"] for r in rows}) == len(rows)


def test_scripted_users_are_not_shopnova_users():
    from callverse.data.seed import USERS as SHOPNOVA_USERS
    names = {r[0] for r in _q("SELECT name FROM users WHERE scripted = 1")}
    assert len(names) == 5 and not names & {u[1] for u in SHOPNOVA_USERS}


def test_hotels_are_the_two_atlas_hotels():
    assert [(r["id"], r["name"]) for r in _q("SELECT id, name FROM hotels ORDER BY id")] == [
        (1, "Atlas City Hotel — Lisbon"), (2, "Atlas Resort Hotel — Algarve")]


# ---- Real mix --------------------------------------------------------------------------------------------------

def test_real_mix_is_kept():
    built = load_sample()["built_with"]
    for key in ("cancelled", "no_show", "room_changed", "no_deposit", "refundable", "non_refundable"):
        assert abs(built["hotel_sample"][key] - built["hotel_full_file"][key]) < 0.03, key
    for key in ("cancelled", "delayed_15_min", "reason_carrier", "reason_weather", "reason_air_system"):
        assert abs(built["flight_sample"][key] - built["flight_full_file"][key]) < 0.03, key


def test_the_recorded_mix_is_the_mix_in_the_database():
    built = load_sample()["built_with"]
    assert _count("hotel_bookings", f"{REAL_HOTELS} AND status = 'cancelled'") / 2000 == built["hotel_sample"]["cancelled"]
    assert _count("hotel_bookings", f"{REAL_HOTELS} AND status = 'no_show'") / 2000 == built["hotel_sample"]["no_show"]
    assert _count("flights", "source = 'usdot_2015' AND status = 'cancelled'") / 2000 == built["flight_sample"]["cancelled"]
    assert _count("flights", "source = 'usdot_2015' AND status = 'delayed'") / 2000 == built["flight_sample"]["delayed_15_min"]


# ---- Dates and statuses possible on 2026-10-09 -------------------------------------------------------------------

def test_hotel_dates_are_inside_their_window():
    rows = _q("SELECT * FROM hotel_bookings WHERE " + REAL_HOTELS)
    assert all("2026-07-11" <= r["arrival_date"] <= "2026-12-31" for r in rows)
    assert all(r["booked_date"] <= r["arrival_date"] for r in rows)
    assert all(r["booked_date"] <= TODAY.isoformat() for r in rows)      # nothing was booked in the future


def test_flight_dates_are_in_the_60_days_before_today():
    first, last = (TODAY - timedelta(days=60)).isoformat(), (TODAY - timedelta(days=1)).isoformat()
    rows = _q("SELECT scheduled_departure FROM flights WHERE source = 'usdot_2015'")
    assert all(first <= r[0][:10] <= last for r in rows)
    assert all(datetime.strptime(r[0], "%Y-%m-%d %H:%M") for r in rows)


def test_flight_bookings_come_before_the_flight():
    rows = _q("SELECT b.booked_date, f.scheduled_departure FROM flight_bookings b JOIN flights f ON f.id = b.flight_id")
    assert len(rows) == 2006 and all(r[0] <= r[1][:10] for r in rows)


def test_hotel_statuses_are_possible_today():
    today = TODAY.isoformat()
    for r in _q("SELECT * FROM hotel_bookings"):
        end = (date.fromisoformat(r["arrival_date"]) + timedelta(days=r["nights"])).isoformat()
        if r["status"] == "stayed":
            assert end <= today, r["id"]
        if r["status"] == "no_show":
            assert r["arrival_date"] <= today, r["id"]
        if r["status"] == "cancelled":
            assert r["booked_date"] <= r["cancelled_date"] <= today, r["id"]
            assert r["cancelled_date"] <= r["arrival_date"], r["id"]
        else:
            assert r["cancelled_date"] is None, r["id"]


def test_some_real_trips_are_still_in_the_future():
    assert _count("hotel_bookings", f"{REAL_HOTELS} AND status = 'confirmed' AND arrival_date > '{TODAY}'") > 0


def test_flight_statuses_follow_the_delays():
    for r in _q("SELECT * FROM flights WHERE source = 'usdot_2015'"):
        if r["cancelled"]:
            assert r["status"] == "cancelled" and r["arrival_delay_min"] is None and r["cancellation_reason"]
        else:
            assert r["status"] == ("delayed" if r["arrival_delay_min"] >= 15 else "on_time")
            assert r["cancellation_reason"] is None
        assert (r["main_delay_cause"] is not None) <= (r["status"] == "delayed")


def test_flight_booking_status_follows_its_flight():
    rows = _q("SELECT b.status, b.notice_days, f.cancelled FROM flight_bookings b JOIN flights f ON f.id = b.flight_id"
              " WHERE b.source = 'generated'")
    assert all(r["status"] == ("cancelled" if r["cancelled"] else "flown") for r in rows)
    assert all(r["notice_days"] == (0 if r["cancelled"] else None) for r in rows)


# ---- Money -----------------------------------------------------------------------------------------------------

def test_hotel_total_is_price_per_night_times_nights():
    rows = _q("SELECT * FROM hotel_bookings")
    assert all(r["total_tnd"] == round(r["price_per_night_tnd"] * r["nights"], 2) for r in rows)


def test_hotel_paid_rule():
    for r in _q("SELECT * FROM hotel_bookings"):
        assert r["paid_tnd"] == (0 if r["deposit_type"] == "no_deposit" else r["total_tnd"]), r["id"]


def test_hotel_money_conversion():
    row = dict.fromkeys(builder.HOTEL_COLUMNS, "0")
    row.update(hotel="City Hotel", adr="100", stays_in_weekend_nights="1", stays_in_week_nights="2", adults="2",
               children="NA", meal="Undefined", reserved_room_type="A", assigned_room_type="B",
               deposit_type="Non Refund")
    dates = {"booked_date": "2026-09-01", "arrival_date": "2026-09-02", "status": "stayed", "cancelled_date": None}
    b = builder.hotel_booking(row, 7, dates)
    assert (b["price_per_night_tnd"], b["total_tnd"], b["paid_tnd"]) == (335.8, 1007.4, 1007.4)
    assert (b["nights"], b["children"], b["meal"], b["source_id"]) == (3, 0, "SC", "7")


def test_fare_formula():
    average = 1000.0
    assert builder.fare_tnd(1000, average) == round(377 * 3.005, 2)
    assert builder.fare_tnd(100, average) == round(377 * 0.5 * 3.005, 2)     # bottom bound
    assert builder.fare_tnd(9000, average) == round(377 * 2.5 * 3.005, 2)    # top bound


def test_flight_prices_use_the_fare_formula():
    rows = _q("SELECT f.distance_km, b.price_tnd, b.paid_tnd FROM flight_bookings b JOIN flights f ON f.id = b.flight_id"
              " WHERE b.source = 'generated'")
    average = sum(r["distance_km"] for r in rows) / len(rows)
    assert all(r["price_tnd"] == r["paid_tnd"] for r in rows)
    assert all(abs(r["price_tnd"] - builder.fare_tnd(r["distance_km"], average)) < 0.01 for r in rows)
    assert 566.44 == min(r["price_tnd"] for r in rows) and max(r["price_tnd"] for r in rows) == 2832.21


def test_distance_in_km():
    r = {name: "" for name in builder.FLIGHT_COLUMNS}
    r.update(YEAR="2015", MONTH="3", DAY="7", AIRLINE="AA", FLIGHT_NUMBER="12", ORIGIN_AIRPORT="JFK",
             DESTINATION_AIRPORT="LAX", SCHEDULED_DEPARTURE="0905", DISTANCE="1000", CANCELLED="1",
             CANCELLATION_REASON="B", DIVERTED="0")
    f = builder.flight_row(r, date(2026, 9, 1), {"AA": "American"}, {"JFK": "New York", "LAX": "Los Angeles"})
    assert f["distance_km"] == 1609.0
    assert f["scheduled_departure"] == "2026-09-01 09:05"
    assert f["cancellation_reason"] == "weather" and f["status"] == "cancelled"
    assert f["source_id"] == "AA12-2015-03-07"


@pytest.mark.parametrize("delays, expected", [
    ({"AIRLINE_DELAY": "30", "WEATHER_DELAY": "20"}, "carrier"),
    ({"LATE_AIRCRAFT_DELAY": "30", "AIR_SYSTEM_DELAY": "40"}, "air_system"),
    ({"WEATHER_DELAY": "50", "AIRLINE_DELAY": "10", "LATE_AIRCRAFT_DELAY": "30"}, "weather"),
    ({"SECURITY_DELAY": "16"}, "security"),
    ({"AIRLINE_DELAY": "25", "WEATHER_DELAY": "25"}, "carrier"),      # a tie stays on the carrier's side
    ({}, None),
])
def test_main_delay_cause(delays, expected):
    empty = dict.fromkeys(("AIRLINE_DELAY", "LATE_AIRCRAFT_DELAY", "WEATHER_DELAY", "AIR_SYSTEM_DELAY",
                           "SECURITY_DELAY"), "")
    assert builder.main_delay_cause({**empty, **delays}) == expected


# ---- Scripted bookings, pinned: ids, amounts, statuses never change silently --------------------------------------

@pytest.mark.parametrize("booking_id, deposit, status, total, paid, days_before", [
    (7001, "no_deposit", "cancelled", 360.00, 0.00, 9),
    (7002, "non_refundable", "cancelled", 380.00, 380.00, 7),
    (7003, "refundable", "stayed", 360.00, 360.00, None),
    (7009, "refundable", "cancelled", 450.00, 450.00, 5),
])
def test_scripted_hotel_bookings(booking_id, deposit, status, total, paid, days_before):
    b = reads.get_hotel_booking(booking_id)
    assert (b["deposit_type"], b["status"], b["total_tnd"], b["paid_tnd"], b["days_before_arrival"]) == (
        deposit, status, total, paid, days_before)


@pytest.mark.parametrize("booking_id, status, paid, flight_status, departure, arrival, reason, cause, km", [
    (7004, "flown", 700.00, "delayed", 195, 200, None, "carrier", 1190.7),
    (7005, "cancelled", 1500.00, "cancelled", None, None, "carrier", None, 3131.1),
    (7006, "flown", 1900.00, "delayed", 330, 318, None, "air_system", 4160.9),
    (7007, "flown", 800.00, "delayed", 60, 60, None, "carrier", 1522.1),
    (7008, "cancelled", 690.00, "cancelled", None, None, "weather", None, 1428.8),
    (7010, "confirmed", 1700.00, "scheduled", None, None, None, None, 3768.3),
])
def test_scripted_flight_bookings(booking_id, status, paid, flight_status, departure, arrival, reason, cause, km):
    b = reads.get_flight_booking(booking_id)
    assert (b["status"], b["paid_tnd"], b["flight_status"], b["departure_delay_min"], b["arrival_delay_min"],
            b["cancellation_reason"], b["main_delay_cause"], b["distance_km"]) == (
        status, paid, flight_status, departure, arrival, reason, cause, km)


def test_scripted_assistance_request():
    assert ASSISTANCE_REQUESTS == [(1, 7010, "wheelchair", "requested", "2026-10-08")]
    assert _count("assistance_requests") == 1


def test_scripted_bookings_are_labelled():
    assert _count("hotel_bookings", "scripted = 1 AND source = 'scripted' AND ai_generated = 1") == 4
    assert _count("flight_bookings", "scripted = 1 AND source = 'scripted' AND ai_generated = 1") == 6
    assert _count("flights", "scripted = 1 AND source = 'scripted' AND ai_generated = 1") == 6


# ---- Rules -----------------------------------------------------------------------------------------------------

def test_rules_file_has_the_approved_rules():
    assert set(POLICIES) == {"AT-FLT-01", "AT-FLT-02", "AT-FLT-03", "AT-FLT-04", "AT-FLT-05", "AT-FLT-06",
                             "AT-AST-01", "AT-HOT-01", "AT-HOT-02", "AT-HOT-03", "AT-HOT-04", "AT-HOT-05",
                             "AT-REF-01", "AT-ESC-01"}
    assert all(r["ai_generated"] and r["condition"] for r in POLICIES.values())


def test_rule_amounts_are_the_approved_ones_at_3_358():
    assert [round(eur * 3.358, 2) for eur in (250, 400, 600, 300)] == [839.5, 1343.2, 2014.8, 1007.4]
    for amount in ("839.50", "1,343.20", "2,014.80"):
        assert amount in POLICIES["AT-FLT-02"]["text"] and amount in POLICIES["AT-FLT-03"]["text"]
    assert "1,007.40" in POLICIES["AT-FLT-03"]["text"]


@pytest.mark.parametrize("booking_id, expected", [
    (7001, {"AT-HOT-01"}), (7002, {"AT-HOT-03"}), (7003, {"AT-HOT-04"}), (7009, {"AT-HOT-02"}),
])
def test_hotel_rules_on_scripted_bookings(booking_id, expected):
    assert true_rules("AT-HOT", reads.get_hotel_booking(booking_id)) == expected


@pytest.mark.parametrize("booking_id, expected", [
    (7004, {"AT-FLT-03", "AT-FLT-05"}),                 # compensation; the 3 h 15 wait also earns a meal
    (7005, {"AT-FLT-01", "AT-FLT-02"}),
    (7006, {"AT-FLT-04", "AT-FLT-05", "AT-FLT-06"}),    # refund right; extraordinary, so no compensation
    (7007, set()),
    (7008, {"AT-FLT-01", "AT-FLT-06"}),
    (7010, set()),
])
def test_flight_rules_on_scripted_bookings(booking_id, expected):
    assert true_rules("AT-FLT", reads.get_flight_booking(booking_id)) == expected


def test_no_show_rule_on_a_real_booking():
    booking_id = _q("SELECT id FROM hotel_bookings WHERE status = 'no_show' LIMIT 1")[0][0]
    assert true_rules("AT-HOT", reads.get_hotel_booking(booking_id)) == {"AT-HOT-05"}


def test_compensation_needs_a_short_notice():
    facts = reads.get_flight_booking(7005)
    assert rule("AT-FLT-02", {**facts, "notice_days": 13})
    assert not rule("AT-FLT-02", {**facts, "notice_days": 14})


def test_refundable_deposit_needs_2_days():
    facts = reads.get_hotel_booking(7009)
    assert rule("AT-HOT-02", {**facts, "days_before_arrival": 2})
    assert not rule("AT-HOT-02", {**facts, "days_before_arrival": 1})


@pytest.mark.parametrize("arrival, expected", [(179, False), (180, True)])
def test_long_delay_starts_at_3_hours(arrival, expected):
    assert rule("AT-FLT-03", {**reads.get_flight_booking(7004), "arrival_delay_min": arrival}) is expected


@pytest.mark.parametrize("departure, expected", [(299, False), (300, True)])
def test_refund_right_starts_at_5_hours(departure, expected):
    assert rule("AT-FLT-04", {**reads.get_flight_booking(7006), "departure_delay_min": departure}) is expected


@pytest.mark.parametrize("km, departure, expected", [
    (1500, 120, True), (1500, 119, False), (1500.1, 179, False), (3500, 180, True), (3500.1, 239, False),
    (3500.1, 240, True),
])
def test_meal_voucher_by_distance(km, departure, expected):
    facts = {**reads.get_flight_booking(7004), "distance_km": km, "departure_delay_min": departure}
    assert rule("AT-FLT-05", facts) is expected


def test_assistance_needs_48_hours():
    assert reads.get_flight_booking(7010)["hours_before_departure"] == 275.5
    assert rule("AT-AST-01", reads.get_flight_booking(7010))
    assert not rule("AT-AST-01", reads.get_flight_booking(7004))      # a past flight


def test_refund_limit():
    facts = reads.get_hotel_booking(7003)
    assert rule("AT-REF-01", {**facts, "amount": 72.00})              # the 20 % of AT-HOT-04
    assert rule("AT-REF-01", {**facts, "amount": 360.00})
    assert not rule("AT-REF-01", {**facts, "amount": 360.01})
    assert not rule("AT-REF-01", {**facts, "amount": 72.00, "refunded_total": 300.00})


def test_finance_above_300():
    assert rule("AT-ESC-01", {"amount": 450.00})                      # 7009's refund
    assert rule("AT-ESC-01", {"amount": 839.50})                      # the smallest compensation
    assert not rule("AT-ESC-01", {"amount": 300})


# ---- Generated refunds -----------------------------------------------------------------------------------------

def test_refunds_in_the_database_follow_the_rules():
    assert _count("refunds") == len(load_sample()["refunds"])
    for r in _q("SELECT * FROM refunds"):
        assert r["amount"] <= 300 and r["status"] == "completed", r["id"]
        booking = (reads.get_hotel_booking if r["booking_type"] == "hotel" else reads.get_flight_booking)(r["booking_id"])
        assert rule(r["rule_id"], booking), r["id"]


def _hotel(**changes) -> dict:
    return {"id": 1, "deposit_type": "refundable", "status": "cancelled", "paid_tnd": 250.0,
            "arrival_date": "2026-10-10", "cancelled_date": "2026-10-08", **changes}


def test_hotel_refund_only_where_the_rules_allow():
    refund = builder.hotel_refund(_hotel())
    assert (refund["amount"], refund["rule_id"], refund["ai_generated"]) == (250.0, "AT-HOT-02", 1)
    assert builder.hotel_refund(_hotel(paid_tnd=300.0))["amount"] == 300.0
    assert builder.hotel_refund(_hotel(paid_tnd=300.01)) is None                  # finance: stays an open case
    assert builder.hotel_refund(_hotel(cancelled_date="2026-10-09")) is None      # 1 day before arrival
    assert builder.hotel_refund(_hotel(deposit_type="non_refundable")) is None
    assert builder.hotel_refund(_hotel(deposit_type="no_deposit", paid_tnd=0.0)) is None
    assert builder.hotel_refund(_hotel(status="stayed")) is None


def test_flight_refund_only_where_the_rules_allow():
    booking = {"id": 1, "paid_tnd": 280.0}
    flight = {"cancellation_reason": "carrier", "scheduled_departure": "2026-10-01 09:00"}
    refund = builder.flight_refund(booking, flight)
    assert (refund["amount"], refund["rule_id"], refund["created_at"]) == (280.0, "AT-FLT-01", "2026-10-01")
    assert builder.flight_refund({"id": 1, "paid_tnd": 300.01}, flight) is None
    assert builder.flight_refund(booking, {**flight, "cancellation_reason": "weather"}) is None
    assert builder.flight_refund(booking, {**flight, "cancellation_reason": None}) is None


# ---- Read functions --------------------------------------------------------------------------------------------

def _all_keys(value) -> set:
    """Every dict key inside a result, at any depth."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _all_keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _all_keys(v)}
    return set()


@pytest.mark.parametrize("result", [
    lambda: reads.get_user(user_id=1),
    lambda: reads.get_user(user_id=101),
    lambda: reads.get_hotel_booking(7001),
    lambda: reads.get_hotel_booking(20001),
    lambda: reads.get_flight(1),
    lambda: reads.get_flight(7005),
    lambda: reads.get_flight_booking(7005),
    lambda: reads.get_flight_booking(30001),
    lambda: reads.get_refunds("hotel", 7003),
    lambda: reads.user_bookings(1),
    lambda: reads.user_bookings(5),
])
def test_reads_never_show_hidden_fields(result):
    keys = _all_keys(result())
    assert keys and not keys & {"source", "source_id", "city", "payment", "payment_method", "ai_generated", "scripted"}


def test_get_user():
    assert reads.get_user(user_id=1)["name"] == "Hedi Karoui"
    assert reads.get_user(email="HEDI@example.com ")["id"] == 1
    assert reads.get_user(phone="+216 22 420 202")["id"] == 2
    assert "error" in reads.get_user(user_id=99)
    assert "error" in reads.get_user()


def test_not_found_is_an_error():
    assert "error" in reads.get_hotel_booking(1)
    assert "error" in reads.get_flight_booking(1)
    assert "error" in reads.get_flight(99999)
    assert "error" in reads.get_refunds("car", 1)


def test_hotel_booking_has_the_hotels_name():
    assert reads.get_hotel_booking(7001)["hotel_name"] == "Atlas City Hotel — Lisbon"


def test_flight_booking_keeps_both_statuses():
    b = reads.get_flight_booking(7004)
    assert (b["id"], b["flight_id"], b["status"], b["flight_status"]) == (7004, 7004, "flown", "delayed")


def test_get_refunds_counts_the_total(tmp_path):
    path = seed(tmp_path / "refunds.db")
    con = sqlite3.connect(path)
    con.executemany("INSERT INTO refunds (booking_type, booking_id, amount, status) VALUES (?, ?, ?, ?)",
                    [("hotel", 7003, 72.00, "completed"), ("hotel", 7003, 50.00, "refused")])
    con.commit()
    con.close()
    module_db = atlas_db.db_path()
    atlas_db.use_db(path)
    try:
        assert reads.get_refunds("hotel", 7003)["refunded_total"] == 72.00      # a refused refund does not count
        assert reads.get_hotel_booking(7003)["refunded_total"] == 72.00
        assert reads.get_refunds("flight", 7003)["refunds"] == []
    finally:
        atlas_db.use_db(module_db)


def test_user_bookings():
    bookings = reads.user_bookings(5)
    assert [b["id"] for b in bookings["flight_bookings"]] == [7004, 7010]
    assert bookings["hotel_bookings"] == []


def test_summary():
    s = reads.summary()
    assert sum(s["hotel_bookings"].values()) == 2004
    assert sum(s["flights"].values()) == 2006
    assert sum(s["flight_bookings"].values()) == 2006
    assert s["flights"]["scheduled"] == 1
    assert 0 < s["flight_cancellation_rate"] < s["flight_delay_rate"] < 1
    assert s["hotel_paid_tnd"] < s["hotel_total_tnd"]
    assert s["refunds"] == _count("refunds")


def test_atlas_is_read_by_no_agent():
    from callverse.tools import registry
    source = open(registry.__file__, encoding="utf-8").read()
    assert "atlas" not in source.lower()


# ---- Company profile -------------------------------------------------------------------------------------------

def test_profile_facts_are_computed_from_the_sample():
    assert PROFILE == json.loads(json.dumps(builder.company_profile(load_sample())))
    built = load_sample()["built_with"]
    assert PROFILE["facts"]["hotel_cancellation_rate"] == built["hotel_sample"]["cancelled"]
    assert PROFILE["facts"]["flight_delay_rate"] == built["flight_sample"]["delayed_15_min"]


def test_profile_fields():
    assert (PROFILE["name"], PROFILE["domain"], PROFILE["currency"]) == ("Atlas Travel", "travel", "TND")
    assert PROFILE["ai_generated"] is True
    assert PROFILE["payment_methods"] == ["card", "pay_at_hotel"]
    assert len(PROFILE["hotels"]) == 2


# ---- The builder, on tiny fake raw files ---------------------------------------------------------------------------

HOTEL_CASES = [("City Hotel", "Check-Out", "No Deposit"), ("Resort Hotel", "Canceled", "Non Refund"),
               ("City Hotel", "No-Show", "Refundable"), ("Resort Hotel", "Canceled", "Refundable")]


def _write(path, columns, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)


def _fake_raw(folder):
    """A few rows of each raw file with the real columns, including rows the builder must leave out."""
    hotels = []
    for i in range(40):
        hotel, status, deposit = HOTEL_CASES[i % 4]
        row = dict.fromkeys(builder.HOTEL_COLUMNS, "0")
        row.update(hotel=hotel, lead_time=str(10 + i), arrival_date_year="2016", arrival_date_month="March",
                   arrival_date_day_of_month=str(i % 28 + 1), stays_in_week_nights=str(i % 5 + 1), adults="2",
                   meal="BB", reserved_room_type="A", assigned_room_type="A" if i % 3 else "D", deposit_type=deposit,
                   adr=str(20 + i), reservation_status=status, reservation_status_date="2016-02-20")
        hotels.append([row[c] for c in builder.HOTEL_COLUMNS])
    bad_stay = dict.fromkeys(builder.HOTEL_COLUMNS, "0")     # 0 nights: left out
    bad_stay.update(hotel="City Hotel", adr="50", adults="2", deposit_type="No Deposit", reservation_status="Check-Out",
                    arrival_date_month="May", arrival_date_year="2016", arrival_date_day_of_month="1")
    hotels.append([bad_stay[c] for c in builder.HOTEL_COLUMNS])
    _write(folder / "hotel_bookings.csv", builder.HOTEL_COLUMNS, hotels)

    flights = []
    for i in range(40):
        row = dict.fromkeys(builder.FLIGHT_COLUMNS, "")
        cancelled = i % 8 == 0
        row.update(YEAR="2015", MONTH="3", DAY=str(i % 28 + 1), AIRLINE="AA", FLIGHT_NUMBER=str(100 + i),
                   ORIGIN_AIRPORT="JFK", DESTINATION_AIRPORT="LAX", SCHEDULED_DEPARTURE=f"{i % 24:02d}10",
                   DISTANCE=str(500 + 50 * i), DIVERTED="0", CANCELLED="1" if cancelled else "0",
                   CANCELLATION_REASON="A" if cancelled else "", ARRIVAL_DELAY="" if cancelled else str(i),
                   DEPARTURE_DELAY=str(i))
        flights.append([row[c] for c in builder.FLIGHT_COLUMNS])
    numeric = dict.fromkeys(builder.FLIGHT_COLUMNS, "")      # October 2015's numeric airport codes: left out
    numeric.update(ORIGIN_AIRPORT="14747", DESTINATION_AIRPORT="LAX", DIVERTED="0", CANCELLED="0", ARRIVAL_DELAY="1")
    diverted = {**numeric, "ORIGIN_AIRPORT": "JFK", "DIVERTED": "1", "ARRIVAL_DELAY": ""}   # diverted: left out
    flights += [[r[c] for c in builder.FLIGHT_COLUMNS] for r in (numeric, diverted)]
    _write(folder / "flights.csv", builder.FLIGHT_COLUMNS, flights)

    _write(folder / "airlines.csv", builder.AIRLINE_COLUMNS, [["AA", "American Airlines Inc."]])
    _write(folder / "airports.csv", builder.AIRPORT_COLUMNS,
           [["JFK", "John F. Kennedy", "New York", "NY", "USA", "", ""],
            ["LAX", "Los Angeles Intl", "Los Angeles", "CA", "USA", "", ""]])
    return folder


def test_the_builder_gives_the_same_sample_twice(tmp_path):
    raw = _fake_raw(tmp_path)
    assert builder.build_sample(raw, size=20) == builder.build_sample(raw, size=20)


def test_the_builder_writes_the_same_bytes_twice(tmp_path):
    raw = _fake_raw(tmp_path)
    one, two = tmp_path / "one.json", tmp_path / "two.json"
    builder.write_json(builder.build_sample(raw, size=20), one)
    builder.write_json(builder.build_sample(raw, size=20), two)
    assert one.read_bytes() == two.read_bytes()


def test_the_builder_leaves_out_impossible_rows(tmp_path):
    raw = _fake_raw(tmp_path)
    data = builder.build_sample(raw, size=38)
    assert all(b["nights"] > 0 for b in data["hotel_bookings"])
    assert {f["origin"] for f in data["flights"]} == {"JFK"}
    assert all(f["cancelled"] or f["arrival_delay_min"] is not None for f in data["flights"])
    assert data["built_with"]["flight_full_file"]["rows"] == 42
    assert data["built_with"]["flight_full_file"]["usable_rows"] == 40
    with pytest.raises(SystemExit):
        builder.build_sample(raw, size=41)              # only 40 usable rows


def test_the_builder_stops_on_a_missing_file(tmp_path):
    raw = _fake_raw(tmp_path)
    (raw / "airports.csv").unlink()
    with pytest.raises(SystemExit, match="missing raw file"):
        builder.build_sample(raw, size=20)


def test_the_builder_stops_on_different_columns(tmp_path):
    raw = _fake_raw(tmp_path)
    _write(raw / "hotel_bookings.csv", ["hotel", "price"], [["City Hotel", "1"]])
    with pytest.raises(SystemExit, match="columns of hotel_bookings.csv differ"):
        builder.build_sample(raw, size=20)


@pytest.mark.parametrize("status, lead, days_before", [
    ("Check-Out", 0, None), ("Check-Out", 300, None), ("Canceled", 300, 200), ("Canceled", 5, 0), ("No-Show", 100, None),
])
def test_new_hotel_dates_keep_the_real_durations(status, lead, days_before):
    row = {"lead_time": str(lead), "stays_in_weekend_nights": "1", "stays_in_week_nights": "2",
           "reservation_status": status, "arrival_date_year": "2016", "arrival_date_month": "May",
           "arrival_date_day_of_month": "20", "reservation_status_date": "2016-05-20"}
    if days_before is not None:
        row["reservation_status_date"] = (date(2016, 5, 20) - timedelta(days=days_before)).isoformat()
    rng = random.Random(1)
    for _ in range(200):
        d = builder.hotel_dates_and_status(row, rng, TODAY)
        arrival = date.fromisoformat(d["arrival_date"])
        assert builder.ARRIVALS_FROM <= arrival <= builder.ARRIVALS_TO
        assert (arrival - date.fromisoformat(d["booked_date"])).days == lead
        assert date.fromisoformat(d["booked_date"]) <= TODAY
        if status == "Canceled":
            assert d["status"] == "cancelled"
            assert (arrival - date.fromisoformat(d["cancelled_date"])).days == days_before
            assert date.fromisoformat(d["cancelled_date"]) <= TODAY
        elif status == "No-Show":
            assert d["status"] == "no_show" and arrival <= TODAY
        else:
            assert d["status"] == ("stayed" if arrival + timedelta(days=3) <= TODAY else "confirmed")


def test_the_sample_file_is_labelled():
    sample = load_sample()
    assert "CC BY 4.0" in sample["_note"] and "CC0" in sample["_note"]
    assert sample["built_with"]["random_seed"] == 2026
    assert sample["built_with"]["eur_to_tnd"] == 3.358 and sample["built_with"]["usd_to_tnd"] == 3.005


def test_the_atlas_database_is_separate_from_shopnova():
    from callverse.data import db as shopnova_db
    assert atlas_db.DEFAULT_DB_PATH.name == "atlas.db"
    assert shopnova_db.db_path() != atlas_db.db_path()
