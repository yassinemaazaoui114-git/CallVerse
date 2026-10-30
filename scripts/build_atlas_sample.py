"""Builds Atlas Travel's real-data sample from two public datasets (task T20).

Input : data/raw/atlas/  hotel_bookings.csv (Hotel Booking Demand, CC BY 4.0) and flights.csv, airlines.csv,
        airports.csv (US DOT 2015 Flight Delays, CC0). Downloaded by hand, never committed (data/raw/ is in .gitignore).
Output: callverse/data/real/atlas_sample.json  (committed; callverse/data/atlas/seed.py loads it)
        callverse/data/atlas_profile.json      (the company profile; its facts are computed from the sample)

What it does, in order:
  1. Hotels: draw 2,000 bookings at random, so the real mix stays. Convert EUR -> TND, move the dates to 2026.
  2. Flights: draw 2,000 flights at random, so the real mix stays. Move them into the 60 days before sim_today.
  3. Generate what the data does not have: one Tunisian user per booking, one flight booking per flight with a
     price from a fare formula, and the refunds the rules allow (<= 300 TND).
  4. Write the sample and the profile, print the numbers of the T20 report.

GENERATED values (ai_generated = 1): all user names, emails, phones and cities; every flight booking (dates, price);
the refunds; the hotel names and places. Real rows keep their real durations, delays, causes and mix.

Rows left out before drawing, because they cannot be a real stay or flight in our tables:
  - hotels: 0 nights, a price of 0 or less, or 0 adults;
  - flights: airports not in airports.csv (October 2015 uses numeric codes that file does not know), and diverted
    flights (they have no arrival delay).

Same input -> same output, byte for byte (fixed seed, file order). No LLM, no API, no network.

Usage (from the repo root):
    python -m scripts.build_atlas_sample        (or: python scripts/build_atlas_sample.py)
"""

import csv
import json
import random
import statistics
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

# Allow "python scripts/build_atlas_sample.py" as well as "python -m scripts.build_atlas_sample".
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from callverse.config import PROJECT_ROOT, sim_start  # noqa: E402
from scripts.build_shopnova_sample import FIRST_NAMES, LAST_NAMES  # noqa: E402

RAW_DIR = PROJECT_ROOT / "data" / "raw" / "atlas"
OUT_PATH = PROJECT_ROOT / "callverse" / "data" / "real" / "atlas_sample.json"
PROFILE_PATH = PROJECT_ROOT / "callverse" / "data" / "atlas_profile.json"
SHOPNOVA_PROFILE_PATH = PROJECT_ROOT / "callverse" / "data" / "company_profile.json"

RANDOM_SEED = 2026
SAMPLE_SIZE = 2000
FIRST_HOTEL_BOOKING_ID, FIRST_FLIGHT_BOOKING_ID, FIRST_USER_ID = 20001, 30001, 101

ARRIVALS_FROM, ARRIVALS_TO = date(2026, 7, 11), date(2026, 12, 31)   # hotel arrivals fall in this window
FLIGHT_WINDOW_DAYS = 60     # every sampled flight is in the 60 days before sim_today

EUR_TO_TND = 3.358          # Wise, 2026-10-30
USD_TO_TND = 3.005          # Wise, 2026-10-30
AVERAGE_FARE_USD = 377      # BTS, average domestic fare of 2015
FARE_MIN_RATIO, FARE_MAX_RATIO = 0.5, 2.5
MILES_TO_KM = 1.609
REFUND_LIMIT_TND = 300      # AT-ESC-01: above this it needs finance, so no generated refund above it
REFUND_MIN_DAYS = 2         # AT-HOT-02: a refundable deposit comes back if cancelled at least 2 days before arrival

# The files and columns we read. If one is missing or different, the script stops (task stop rule).
HOTEL_COLUMNS = ["hotel", "is_canceled", "lead_time", "arrival_date_year", "arrival_date_month",
                 "arrival_date_week_number", "arrival_date_day_of_month", "stays_in_weekend_nights",
                 "stays_in_week_nights", "adults", "children", "babies", "meal", "country", "market_segment",
                 "distribution_channel", "is_repeated_guest", "previous_cancellations",
                 "previous_bookings_not_canceled", "reserved_room_type", "assigned_room_type", "booking_changes",
                 "deposit_type", "agent", "company", "days_in_waiting_list", "customer_type", "adr",
                 "required_car_parking_spaces", "total_of_special_requests", "reservation_status",
                 "reservation_status_date"]
FLIGHT_COLUMNS = ["YEAR", "MONTH", "DAY", "DAY_OF_WEEK", "AIRLINE", "FLIGHT_NUMBER", "TAIL_NUMBER", "ORIGIN_AIRPORT",
                  "DESTINATION_AIRPORT", "SCHEDULED_DEPARTURE", "DEPARTURE_TIME", "DEPARTURE_DELAY", "TAXI_OUT",
                  "WHEELS_OFF", "SCHEDULED_TIME", "ELAPSED_TIME", "AIR_TIME", "DISTANCE", "WHEELS_ON", "TAXI_IN",
                  "SCHEDULED_ARRIVAL", "ARRIVAL_TIME", "ARRIVAL_DELAY", "DIVERTED", "CANCELLED",
                  "CANCELLATION_REASON", "AIR_SYSTEM_DELAY", "SECURITY_DELAY", "AIRLINE_DELAY",
                  "LATE_AIRCRAFT_DELAY", "WEATHER_DELAY"]
AIRLINE_COLUMNS = ["IATA_CODE", "AIRLINE"]
AIRPORT_COLUMNS = ["IATA_CODE", "AIRPORT", "CITY", "STATE", "COUNTRY", "LATITUDE", "LONGITUDE"]

HOTELS = {"City Hotel": 1, "Resort Hotel": 2}     # the dataset's name -> our hotel id
HOTEL_ROWS = [
    {"id": 1, "name": "Atlas City Hotel — Lisbon", "source": "hotel_booking_demand", "source_id": "City Hotel",
     "ai_generated": 1},
    {"id": 2, "name": "Atlas Resort Hotel — Algarve", "source": "hotel_booking_demand", "source_id": "Resort Hotel",
     "ai_generated": 1},
]
DEPOSITS = {"No Deposit": "no_deposit", "Refundable": "refundable", "Non Refund": "non_refundable"}
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
CANCELLATION_REASONS = {"A": "carrier", "B": "weather", "C": "air_system", "D": "security"}

SAMPLE_NOTE = ("Derived from two datasets. Hotels: Antonio, Almeida, Nunes (2019), Hotel booking demand datasets, "
               "Data in Brief, DOI 10.1016/j.dib.2018.11.126, licence CC BY 4.0. Flights: US DOT / BTS, 2015 Flight "
               "Delays and Cancellations, CC0. Rows sampled, dates moved, money converted to TND; users, flight "
               "bookings and refunds are generated. See DATA_LICENCES.md. Built by scripts/build_atlas_sample.py "
               "(task T20); do not edit by hand.")


def open_csv(path: Path, columns: list[str]):
    """Open one raw file and return (file, csv reader after the header); stop if it is missing or different."""
    if not path.exists():
        sys.exit(f"STOP: missing raw file {path}")
    f = open(path, encoding="utf-8-sig", newline="")
    reader = csv.reader(f)
    header = next(reader)
    if header != columns:
        f.close()
        sys.exit(f"STOP: columns of {path.name} differ: {header}")
    return f, reader


def read_rows(path: Path, columns: list[str]) -> list[dict]:
    """A whole small file as a list of dicts."""
    f, reader = open_csv(path, columns)
    with f:
        return [dict(zip(columns, row)) for row in reader]


def number(text: str) -> int:
    """Delay fields: '' -> 0, '12.0' -> 12."""
    return int(float(text)) if text else 0


def optional_int(text: str) -> int | None:
    """Delay fields that may really be unknown: '' -> None, '-4' -> -4."""
    return int(float(text)) if text else None


# ---- 1. Hotels ------------------------------------------------------------------------------------------------

def nights_of(r: dict) -> int:
    return int(r["stays_in_weekend_nights"]) + int(r["stays_in_week_nights"])


def real_arrival(r: dict) -> date:
    return date(int(r["arrival_date_year"]), MONTHS.index(r["arrival_date_month"]) + 1,
                int(r["arrival_date_day_of_month"]))


def is_real_stay(r: dict) -> bool:
    """False for the rows that cannot be a stay: 0 nights, no price, nobody."""
    return nights_of(r) > 0 and float(r["adr"]) > 0 and int(r["adults"]) > 0


def hotel_dates_and_status(r: dict, rng: random.Random, today: date) -> dict:
    """New dates and a status that is possible on sim_today, keeping the real lead time and stay length.

    Each booking gets its own arrival date (the real ones span 2 years, the window only 6 months). The latest
    possible arrival depends on the real story, so nothing that has not happened yet is in the data:
      - any booking: booked on or before today          -> arrival <= today + lead time;
      - a cancelled one: cancelled on or before today   -> arrival <= today + (real days between cancel and arrival);
      - a no-show: the arrival day has passed           -> arrival <= today.
    So all real cancellations and no-shows stay what they are (the real mix). Only stays can become `confirmed`:
    a stay not finished by today has not happened yet.
    """
    lead = int(r["lead_time"])
    latest = today + timedelta(days=lead)
    days_before = None
    if r["reservation_status"] == "Canceled":
        days_before = (real_arrival(r) - date.fromisoformat(r["reservation_status_date"])).days
        latest = today + timedelta(days=days_before)
    elif r["reservation_status"] == "No-Show":
        latest = today
    latest = min(latest, ARRIVALS_TO)
    arrival = ARRIVALS_FROM + timedelta(days=rng.randint(0, (latest - ARRIVALS_FROM).days))

    cancelled_date = None
    if r["reservation_status"] == "Canceled":
        status = "cancelled"
        cancelled_date = (arrival - timedelta(days=days_before)).isoformat()
    elif r["reservation_status"] == "No-Show":
        status = "no_show"
    elif arrival + timedelta(days=nights_of(r)) <= today:
        status = "stayed"
    else:
        status = "confirmed"
    return {"booked_date": (arrival - timedelta(days=lead)).isoformat(), "arrival_date": arrival.isoformat(),
            "status": status, "cancelled_date": cancelled_date}


def hotel_booking(r: dict, csv_row: int, dates: dict) -> dict:
    """One row of hotel_bookings from one CSV row. `source_id` = the CSV row number (1 = first row after the header)."""
    nights = nights_of(r)
    per_night = round(float(r["adr"]) * EUR_TO_TND, 2)
    total = round(per_night * nights, 2)
    deposit = DEPOSITS[r["deposit_type"]]
    # A deposit is paid at booking. With no deposit the client pays at the hotel, so only a finished stay is paid.
    paid = 0.0 if deposit == "no_deposit" and dates["status"] != "stayed" else total
    return {"id": None, "user_id": None, "hotel_id": HOTELS[r["hotel"]],
            "booked_date": dates["booked_date"], "arrival_date": dates["arrival_date"], "nights": nights,
            "adults": int(r["adults"]),
            "children": 0 if r["children"] == "NA" else int(r["children"]),     # 4 rows of the file have no value
            "meal": "SC" if r["meal"] == "Undefined" else r["meal"],            # the authors: Undefined = SC, no meal
            "room_reserved": r["reserved_room_type"], "room_assigned": r["assigned_room_type"],
            "deposit_type": deposit, "price_per_night_tnd": per_night, "total_tnd": total,
            "paid_tnd": paid,
            "status": dates["status"], "cancelled_date": dates["cancelled_date"],
            "special_requests": int(r["total_of_special_requests"]),
            "source": "hotel_booking_demand", "source_id": str(csv_row), "ai_generated": 0}


def hotel_mix(raw: list[dict]) -> dict:
    """The share of each real case in a list of raw rows (to compare the sample with the full file)."""
    n = len(raw)
    deposits = Counter(DEPOSITS[r["deposit_type"]] for r in raw)
    return {"rows": n,
            "cancelled": round(sum(r["reservation_status"] == "Canceled" for r in raw) / n, 4),
            "no_show": round(sum(r["reservation_status"] == "No-Show" for r in raw) / n, 4),
            "room_changed": round(sum(r["reserved_room_type"] != r["assigned_room_type"] for r in raw) / n, 4),
            **{d: round(deposits[d] / n, 4) for d in DEPOSITS.values()}}


# ---- 2. Flights -----------------------------------------------------------------------------------------------

def main_delay_cause(r: dict) -> str | None:
    """The cause with the most delay minutes. Airline and late aircraft are both the carrier's side.

    On a tie the carrier side wins (it comes first, and max() keeps the first): the client keeps the right.
    None when the file gives no delay minutes (flights less than 15 minutes late).
    """
    minutes = [("carrier", number(r["AIRLINE_DELAY"])), ("carrier", number(r["LATE_AIRCRAFT_DELAY"])),
               ("weather", number(r["WEATHER_DELAY"])), ("air_system", number(r["AIR_SYSTEM_DELAY"])),
               ("security", number(r["SECURITY_DELAY"]))]
    cause, most = max(minutes, key=lambda item: item[1])
    return cause if most > 0 else None


def flight_row(r: dict, flight_date: date, airlines: dict, airports: dict) -> dict:
    """One row of flights from one CSV row. Past flights keep their real delays, cancellation and cause."""
    cancelled = int(r["CANCELLED"])
    arrival_delay = optional_int(r["ARRIVAL_DELAY"])
    status = "cancelled" if cancelled else "delayed" if arrival_delay >= 15 else "on_time"
    hhmm = r["SCHEDULED_DEPARTURE"]
    return {"id": None, "carrier": r["AIRLINE"], "carrier_name": airlines[r["AIRLINE"]],
            "flight_number": int(r["FLIGHT_NUMBER"]),
            "origin": r["ORIGIN_AIRPORT"], "origin_city": airports[r["ORIGIN_AIRPORT"]],
            "destination": r["DESTINATION_AIRPORT"], "destination_city": airports[r["DESTINATION_AIRPORT"]],
            "distance_km": round(int(r["DISTANCE"]) * MILES_TO_KM, 1),
            "scheduled_departure": f"{flight_date.isoformat()} {hhmm[:2]}:{hhmm[2:]}",
            "departure_delay_min": optional_int(r["DEPARTURE_DELAY"]), "arrival_delay_min": arrival_delay,
            "cancelled": cancelled, "cancellation_reason": CANCELLATION_REASONS.get(r["CANCELLATION_REASON"]),
            "main_delay_cause": None if cancelled else main_delay_cause(r), "status": status,
            "source": "usdot_2015", "ai_generated": 0,
            "source_id": f"{r['AIRLINE']}{r['FLIGHT_NUMBER']}-{r['YEAR']}-{int(r['MONTH']):02d}-{int(r['DAY']):02d}"}


def fare_tnd(distance_km: float, average_km: float) -> float:
    """The fare formula: the average 2015 fare, scaled by distance (between 0.5x and 2.5x), in TND."""
    ratio = max(FARE_MIN_RATIO, min(FARE_MAX_RATIO, distance_km / average_km))
    return round(AVERAGE_FARE_USD * ratio * USD_TO_TND, 2)


def draw_flights(path: Path, known_airports: dict, size: int, rng: random.Random) -> tuple[list[dict], dict]:
    """Draw `size` flights at random. Returns (raw rows, mix of the full file).

    flights.csv has 5.8 million rows, too many to keep in memory: the first pass only remembers the numbers of the
    usable rows and counts the mix, the second pass reads the rows that were drawn.
    """
    index = {name: i for i, name in enumerate(FLIGHT_COLUMNS)}
    usable, total = [], 0
    reasons, delayed, cancelled = Counter(), 0, 0
    f, reader = open_csv(path, FLIGHT_COLUMNS)
    with f:
        for n, row in enumerate(reader):
            total += 1
            is_cancelled = row[index["CANCELLED"]] == "1"
            cancelled += is_cancelled
            reasons[row[index["CANCELLATION_REASON"]]] += is_cancelled
            arrival_delay = row[index["ARRIVAL_DELAY"]]
            delayed += bool(arrival_delay) and float(arrival_delay) >= 15
            if (row[index["ORIGIN_AIRPORT"]] in known_airports and row[index["DESTINATION_AIRPORT"]] in known_airports
                    and row[index["DIVERTED"]] == "0"):
                usable.append(n)
    if len(usable) < size:
        sys.exit(f"STOP: only {len(usable)} usable flights in {path.name}")

    drawn = set(rng.sample(usable, size))
    rows = []
    f, reader = open_csv(path, FLIGHT_COLUMNS)
    with f:
        for n, row in enumerate(reader):
            if n in drawn:
                rows.append(dict(zip(FLIGHT_COLUMNS, row)))
    full_file = {"rows": total, "usable_rows": len(usable), "cancelled": round(cancelled / total, 4),
                 "delayed_15_min": round(delayed / total, 4),
                 **{f"reason_{code}": round(reasons[letter] / total, 5)
                    for letter, code in CANCELLATION_REASONS.items()}}
    return rows, full_file


def flight_mix(flights: list[dict]) -> dict:
    """Same numbers as the full-file mix in draw_flights, for the sampled flights."""
    n = len(flights)
    reasons = Counter(f["cancellation_reason"] for f in flights)
    return {"rows": n, "cancelled": round(sum(f["cancelled"] for f in flights) / n, 4),
            "delayed_15_min": round(sum(f["status"] == "delayed" for f in flights) / n, 4),
            **{f"reason_{code}": round(reasons[code] / n, 5) for code in CANCELLATION_REASONS.values()}}


# ---- 3. Generated rows ----------------------------------------------------------------------------------------

def make_user(user_id: int, rng: random.Random, cities: list[str]) -> dict:
    """One generated Tunisian user. All of it is invented; the phone is unique per id."""
    first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
    digits = 50_000_000 + user_id * 7919
    return {"id": user_id, "name": f"{first} {last}",
            "email": f"{first}.{last.replace(' ', '')}.{user_id}@example.com".lower(),
            "phone": f"+216 {digits // 1_000_000} {digits // 1000 % 1000:03d} {digits % 1000:03d}",
            "city": rng.choice(cities), "source": "generated", "source_id": None, "ai_generated": 1}


def hotel_refund(b: dict) -> dict | None:
    """AT-HOT-02: the refund of a cancelled refundable deposit, if the rules allow it and it is <= 300 TND."""
    if b["deposit_type"] != "refundable" or b["status"] != "cancelled" or b["paid_tnd"] > REFUND_LIMIT_TND:
        return None
    days_before = (date.fromisoformat(b["arrival_date"]) - date.fromisoformat(b["cancelled_date"])).days
    if days_before < REFUND_MIN_DAYS:
        return None
    return {"booking_type": "hotel", "booking_id": b["id"], "amount": b["paid_tnd"], "status": "completed",
            "rule_id": "AT-HOT-02", "proposal_id": None, "created_at": b["cancelled_date"],
            "source": "generated", "source_id": None, "ai_generated": 1}


def flight_refund(booking: dict, flight: dict) -> dict | None:
    """AT-FLT-01: the refund of a carrier-cancelled flight, if it is <= 300 TND."""
    if flight["cancellation_reason"] != "carrier" or booking["paid_tnd"] > REFUND_LIMIT_TND:
        return None
    return {"booking_type": "flight", "booking_id": booking["id"], "amount": booking["paid_tnd"],
            "status": "completed", "rule_id": "AT-FLT-01", "proposal_id": None,
            "created_at": flight["scheduled_departure"][:10],
            "source": "generated", "source_id": None, "ai_generated": 1}


def build_sample(raw_dir: Path = RAW_DIR, size: int = SAMPLE_SIZE) -> dict:
    """Everything that goes into atlas_sample.json. Writes nothing."""
    today = sim_start()            # the fixed start date (2026-10-09), never the moving clock
    rng = random.Random(RANDOM_SEED)
    cities = json.loads(SHOPNOVA_PROFILE_PATH.read_text(encoding="utf-8"))["cities_served"]

    # Hotels: `n` is the CSV row number, 1 = the first row after the header.
    raw_hotels = list(enumerate(read_rows(raw_dir / "hotel_bookings.csv", HOTEL_COLUMNS), start=1))
    usable_hotels = [(n, r) for n, r in raw_hotels if is_real_stay(r)]
    if len(usable_hotels) < size:
        sys.exit(f"STOP: only {len(usable_hotels)} usable hotel bookings")
    drawn_hotels = rng.sample(usable_hotels, size)
    hotel_bookings = [hotel_booking(r, n, hotel_dates_and_status(r, rng, today)) for n, r in drawn_hotels]
    # Ids follow the booking date, like a real company's booking numbers.
    hotel_bookings.sort(key=lambda b: (b["booked_date"], int(b["source_id"])))

    # Flights.
    airlines = {r["IATA_CODE"]: r["AIRLINE"] for r in read_rows(raw_dir / "airlines.csv", AIRLINE_COLUMNS)}
    airports = {r["IATA_CODE"]: r["CITY"] for r in read_rows(raw_dir / "airports.csv", AIRPORT_COLUMNS)}
    drawn_flights, flights_full_file = draw_flights(raw_dir / "flights.csv", airports, size, rng)
    flights = [flight_row(r, today - timedelta(days=rng.randint(1, FLIGHT_WINDOW_DAYS)), airlines, airports)
               for r in drawn_flights]
    flights.sort(key=lambda f: (f["scheduled_departure"], f["source_id"]))
    average_km = statistics.fmean(f["distance_km"] for f in flights)

    # Users: one generated user per hotel booking, then one per flight booking.
    users = [make_user(FIRST_USER_ID + i, rng, cities) for i in range(size * 2)]
    for n, b in enumerate(hotel_bookings):
        b["id"], b["user_id"] = FIRST_HOTEL_BOOKING_ID + n, users[n]["id"]

    # Flight bookings: lead time drawn from the real hotel lead times (the flight file has no booking date).
    leads = [int(r["lead_time"]) for _, r in usable_hotels]
    flight_bookings = []
    for n, f in enumerate(flights):
        f["id"] = n + 1
        flight_date = datetime.fromisoformat(f["scheduled_departure"]).date()
        price = fare_tnd(f["distance_km"], average_km)
        flight_bookings.append({
            "id": FIRST_FLIGHT_BOOKING_ID + n, "user_id": users[size + n]["id"], "flight_id": f["id"],
            "booked_date": (flight_date - timedelta(days=rng.choice(leads))).isoformat(), "seat_class": "economy",
            "price_tnd": price, "paid_tnd": price, "status": "cancelled" if f["cancelled"] else "flown",
            "notice_days": 0 if f["cancelled"] else None,       # the file has no notice date
            "source": "generated", "source_id": None, "ai_generated": 1})

    refunds = [r for r in (hotel_refund(b) for b in hotel_bookings) if r]
    refunds += [r for r in (flight_refund(b, f) for b, f in zip(flight_bookings, flights)) if r]

    return {
        "_note": SAMPLE_NOTE,
        "built_with": {"random_seed": RANDOM_SEED, "sample_size": size, "sim_today": today.isoformat(),
                       "eur_to_tnd": EUR_TO_TND, "usd_to_tnd": USD_TO_TND, "rate_date": "2026-10-30",
                       "rate_source": "Wise mid-market rates, read by the Brain on 2026-10-30",
                       "average_fare_usd": AVERAGE_FARE_USD, "sample_average_km": round(average_km, 1),
                       "hotel_full_file": hotel_mix([r for _, r in raw_hotels]),
                       "hotel_sample": hotel_mix([r for _, r in drawn_hotels]),
                       "flight_full_file": flights_full_file, "flight_sample": flight_mix(flights)},
        "users": users, "hotels": HOTEL_ROWS, "hotel_bookings": hotel_bookings, "flights": flights,
        "flight_bookings": flight_bookings, "refunds": refunds,
    }


# ---- 4. Output ------------------------------------------------------------------------------------------------

def write_json(data: dict, path: Path = OUT_PATH) -> None:
    """One row per line: small, and a rebuild shows readable diffs in git."""
    path.parent.mkdir(parents=True, exist_ok=True)
    dump = lambda v: json.dumps(v, ensure_ascii=False, separators=(",", ":"))  # noqa: E731
    parts = [f'"_note":{dump(data["_note"])}', f'"built_with":{dump(data["built_with"])}']
    for table in ("users", "hotels", "hotel_bookings", "flights", "flight_bookings", "refunds"):
        parts.append(f'"{table}":[\n' + ",\n".join(dump(row) for row in data[table]) + "\n]")
    path.write_text("{\n" + ",\n".join(parts) + "\n}\n", encoding="utf-8", newline="\n")


def company_profile(data: dict) -> dict:
    """Atlas's profile: fixed text, and facts computed from the real sample (never written by hand)."""
    hotels, flights, bookings = data["hotel_bookings"], data["flights"], data["flight_bookings"]
    cities = json.loads(SHOPNOVA_PROFILE_PATH.read_text(encoding="utf-8"))["cities_served"]
    n_hotels, n_flights = len(hotels), len(flights)
    return {
        "name": "Atlas Travel",
        "domain": "travel",
        "description": ("Atlas Travel is a travel agency based in Tunis that sells hotel stays in Portugal and "
                        "flights in the United States to Tunisian travellers. Its customer relation center is "
                        "fully run by AI agents."),
        "hotels": [h["name"] for h in data["hotels"]],
        "airlines": sorted({f["carrier_name"] for f in flights}),
        "cities_served": cities,
        "currency": "TND",
        "payment_methods": ["card", "pay_at_hotel"],
        "support_channels": ["chat", "email", "phone"],
        "support_languages": ["French", "Arabic", "English"],
        "facts": {
            "hotel_cancellation_rate": round(sum(b["status"] == "cancelled" for b in hotels) / n_hotels, 4),
            "hotel_no_show_rate": round(sum(b["status"] == "no_show" for b in hotels) / n_hotels, 4),
            "flight_delay_rate": round(sum(f["status"] == "delayed" for f in flights) / n_flights, 4),
            "flight_cancellation_rate": round(sum(f["status"] == "cancelled" for f in flights) / n_flights, 4),
            "average_stay_tnd": round(statistics.fmean(b["total_tnd"] for b in hotels), 2),
            "average_flight_price_tnd": round(statistics.fmean(b["price_tnd"] for b in bookings), 2),
        },
        "ai_generated": True,
    }


def write_profile(profile: dict, path: Path = PROFILE_PATH) -> None:
    """Same layout as company_profile.json: one field per line."""
    body = ",\n".join(f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in profile.items())
    path.write_text("{\n" + body + "\n}\n", encoding="utf-8", newline="\n")


def report(data: dict) -> None:
    """Print the numbers the T20 report asks for."""
    built, hotels, flights = data["built_with"], data["hotel_bookings"], data["flights"]
    bookings, refunds = data["flight_bookings"], data["refunds"]
    print(f"Written: {OUT_PATH} ({OUT_PATH.stat().st_size:,} bytes)")
    print("Hotel mix, full file:", built["hotel_full_file"])
    print("Hotel mix, sample   :", built["hotel_sample"])
    print("Hotel status counts :", dict(Counter(b["status"] for b in hotels).most_common()))
    print("Flight mix, full file:", built["flight_full_file"])
    print("Flight mix, sample   :", built["flight_sample"])
    print("Flight status counts :", dict(Counter(f["status"] for f in flights).most_common()))
    totals = sorted(b["total_tnd"] for b in hotels)
    prices = sorted(b["price_tnd"] for b in bookings)
    print(f"Hotel stay TND min / average / max: {totals[0]} / {statistics.fmean(totals):.2f} / {totals[-1]}")
    print(f"Flight price TND min / average / max: {prices[0]} / {statistics.fmean(prices):.2f} / {prices[-1]}")
    print(f"Hotel stays <= 300 TND: {sum(t <= REFUND_LIMIT_TND for t in totals)}; "
          f"flight prices <= 300 TND: {sum(p <= REFUND_LIMIT_TND for p in prices)}")
    print(f"Refundable deposits cancelled: "
          f"{sum(b['deposit_type'] == 'refundable' and b['status'] == 'cancelled' for b in hotels)}; "
          f"carrier-cancelled flights: {sum(f['cancellation_reason'] == 'carrier' for f in flights)}")
    print(f"Generated refunds: {len(refunds)}, total {sum(r['amount'] for r in refunds):.2f} TND")
    arrivals = [b["arrival_date"] for b in hotels]
    print(f"Arrivals: {min(arrivals)} .. {max(arrivals)}; booked: {min(b['booked_date'] for b in hotels)} .. "
          f"{max(b['booked_date'] for b in hotels)}")
    departures = [f["scheduled_departure"] for f in flights]
    print(f"Flights: {min(departures)} .. {max(departures)}")


def main() -> None:
    data = build_sample()
    write_json(data)
    write_profile(company_profile(data))
    report(data)


if __name__ == "__main__":
    main()
