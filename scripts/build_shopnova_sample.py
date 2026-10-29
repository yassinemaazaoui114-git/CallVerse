"""Builds ShopNova's real-data sample from the Olist dataset (task T15).

Input : data/raw/olist/  the 9 CSV files of the Kaggle dataset `olistbr/brazilian-ecommerce` (CC BY-NC-SA 4.0).
        They are downloaded by hand and never committed (data/raw/ is in .gitignore).
Output: callverse/data/real/shopnova_olist_sample.json  (committed; callverse/data/seed.py loads it).

What it does, in order (every rule is one of the 20 + 4 items agreed with Yassine on 2026-10-29):
  1. Keep only orders whose items ALL belong to electronics-shop categories (CATEGORIES below).
  2. Draw 2,000 of them at random (fixed seed 2026), keeping Olist's real status mix.
  3. Move each order into the 90 days before sim_today, keeping its real durations (shift_days).
  4. Translate Olist statuses, payments and prices (BRL -> TND) to ShopNova's codes.
  5. Fill the gaps Olist does not have (client names, carrier, tracking number, stock, product names) with
     generated values, and add refunds only where the real data says so (late + review score 1-2).
Every row says where it comes from: `source` = "olist" (real) or "generated", plus the Olist id in `source_id`.

Same input -> same output, byte for byte (fixed seed, sorted inputs). No LLM, no API, no network.

Usage (from the repo root):
    python -m scripts.build_shopnova_sample        (or: python scripts/build_shopnova_sample.py)
"""

import csv
import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

# Allow "python scripts/build_shopnova_sample.py" as well as "python -m scripts.build_shopnova_sample".
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from callverse.config import PROJECT_ROOT, load_config, sim_start  # noqa: E402

RAW_DIR = PROJECT_ROOT / "data" / "raw" / "olist"
OUT_PATH = PROJECT_ROOT / "callverse" / "data" / "real" / "shopnova_olist_sample.json"

RANDOM_SEED = 2026
SAMPLE_SIZE = 2000
WINDOW_DAYS = 90            # every order sits in the 90 days before sim_today
FIRST_ORDER_ID, FIRST_USER_ID, FIRST_PRODUCT_ID = 10001, 1001, 101

# The files and columns we read. If one is missing or different, the script stops (task stop rule).
FILES = {
    "olist_orders_dataset.csv": ["order_id", "customer_id", "order_status", "order_purchase_timestamp",
                                 "order_approved_at", "order_delivered_carrier_date",
                                 "order_delivered_customer_date", "order_estimated_delivery_date"],
    "olist_order_items_dataset.csv": ["order_id", "order_item_id", "product_id", "seller_id",
                                      "shipping_limit_date", "price", "freight_value"],
    "olist_order_payments_dataset.csv": ["order_id", "payment_sequential", "payment_type",
                                         "payment_installments", "payment_value"],
    "olist_order_reviews_dataset.csv": ["review_id", "order_id", "review_score", "review_comment_title",
                                        "review_comment_message", "review_creation_date",
                                        "review_answer_timestamp"],
    "olist_customers_dataset.csv": ["customer_id", "customer_unique_id", "customer_zip_code_prefix",
                                    "customer_city", "customer_state"],
    "olist_products_dataset.csv": ["product_id", "product_category_name", "product_name_lenght",
                                   "product_description_lenght", "product_photos_qty", "product_weight_g",
                                   "product_length_cm", "product_height_cm", "product_width_cm"],
    "olist_sellers_dataset.csv": ["seller_id", "seller_zip_code_prefix", "seller_city", "seller_state"],
    "olist_geolocation_dataset.csv": ["geolocation_zip_code_prefix", "geolocation_lat", "geolocation_lng",
                                      "geolocation_city", "geolocation_state"],
    "product_category_name_translation.csv": ["product_category_name", "product_category_name_english"],
}

# Electronics-shop categories (Olist's Portuguese names) -> label used in the generated product names.
# `pc_gamer` is missing from Olist's translation file (a known gap of the dataset): its English name is
# written here by hand ("pc_gamer"), it only has 3 products in the whole dataset.
CATEGORIES = {
    "telefonia": "Phone",
    "telefonia_fixa": "Landline phone",
    "informatica_acessorios": "Computer accessory",
    "eletronicos": "Electronics",
    "audio": "Audio",
    "pcs": "Computer",
    "pc_gamer": "Gaming PC",
    "tablets_impressao_imagem": "Tablet and printing",
    "relogios_presentes": "Watch",
    "consoles_games": "Console and games",
}

# Olist order status -> ShopNova status ("shipped" may still become stuck_at_depot, see step 4 in main()).
STATUS_MAP = {
    "delivered": "delivered",
    "shipped": "shipped",
    "canceled": "cancelled", "unavailable": "cancelled",
    "created": "processing", "approved": "processing", "invoiced": "processing", "processing": "processing",
}

# Brazilian state -> Tunisian city (one of the 8 `cities_served` in company_profile.json), a FIXED table.
# How it was made: the 27 states ranked by their number of customers in the full Olist customers file
# (SP 41,746 ... RR 46), then rank 1 -> 1st city of the profile, rank 2 -> 2nd city, ... rank 9 -> 1st city
# again (round robin). So the biggest market (SP, ~42% of clients) is Tunis, where ShopNova is based.
STATE_TO_CITY = {
    "SP": "Tunis",  "RJ": "Ariana",  "MG": "Ben Arous", "RS": "Sousse", "PR": "Sfax",
    "SC": "Monastir", "BA": "Nabeul", "DF": "Bizerte",
    "ES": "Tunis",  "GO": "Ariana",  "PE": "Ben Arous", "CE": "Sousse", "PA": "Sfax",
    "MT": "Monastir", "MA": "Nabeul", "MS": "Bizerte",
    "PB": "Tunis",  "PI": "Ariana",  "RN": "Ben Arous", "AL": "Sousse", "SE": "Sfax",
    "TO": "Monastir", "RO": "Nabeul", "AM": "Bizerte",
    "AC": "Tunis",  "AP": "Ariana",  "RR": "Ben Arous",
}

# Generated client names (Tunisian). Olist has no names (only anonymous ids), so every real client gets one.
FIRST_NAMES = ["Ahmed", "Mariem", "Omar", "Ines", "Hamza", "Nour", "Mehdi", "Rania", "Aziz", "Salma",
               "Mohamed", "Fatma", "Ali", "Amel", "Bilel", "Asma", "Wassim", "Hiba", "Skander", "Emna",
               "Firas", "Yosra", "Anis", "Khaoula", "Seif", "Nesrine", "Walid", "Sirine", "Hichem", "Olfa"]
LAST_NAMES = ["Hammami", "Bouazizi", "Chaabane", "Dridi", "Ferchichi", "Khelifi", "Mejri", "Sassi",
              "Ayari", "Baccouche", "Ben Salah", "Chebbi", "Gharsalli", "Jlassi", "Kammoun", "Labidi",
              "Mabrouk", "Nasri", "Ouertani", "Riahi", "Saidi", "Tlili", "Zouari", "Ben Youssef", "Masmoudi"]


def read_csv(name: str) -> list[dict]:
    """Read one Olist file; stop if it is missing or its columns are not the expected ones."""
    path = RAW_DIR / name
    if not path.exists():
        sys.exit(f"STOP: missing Olist file {path}")
    with open(path, encoding="utf-8-sig", newline="") as f:   # utf-8-sig: one file starts with a BOM
        reader = csv.DictReader(f)
        if reader.fieldnames != FILES[name]:
            sys.exit(f"STOP: columns of {name} differ: {reader.fieldnames}")
        return list(reader)


def day(timestamp: str) -> date | None:
    """'2017-10-02 10:56:33' -> date(2017, 10, 2); '' -> None. ShopNova stores dates only (YYYY-MM-DD)."""
    return date.fromisoformat(timestamp[:10]) if timestamp else None


def tnd(brl: float, rate: float) -> float:
    """Reais -> dinars with the fixed rate from config.yaml, rounded to 0.01 TND."""
    return round(brl * rate, 2)


def main() -> None:
    config = load_config()
    rate = config["currency"]["brl_to_tnd"]
    today = sim_start()            # the fixed start date (2026-10-09), never the moving clock
    window_start = today - timedelta(days=WINDOW_DAYS)
    rng = random.Random(RANDOM_SEED)

    # Read every file once (also checks that all 9 files are there with the expected columns).
    raw = {name: read_csv(name) for name in FILES}
    translation = {r["product_category_name"]: r["product_category_name_english"]
                   for r in raw["product_category_name_translation.csv"]}
    category_of = {r["product_id"]: r["product_category_name"] for r in raw["olist_products_dataset.csv"]}
    customers = {r["customer_id"]: r for r in raw["olist_customers_dataset.csv"]}
    items_of, payments_of, reviews_of = defaultdict(list), defaultdict(list), defaultdict(list)
    for r in raw["olist_order_items_dataset.csv"]:
        items_of[r["order_id"]].append(r)
    for r in raw["olist_order_payments_dataset.csv"]:
        payments_of[r["order_id"]].append(r)
    for r in raw["olist_order_reviews_dataset.csv"]:
        reviews_of[r["order_id"]].append(r)
    missing_states = {c["customer_state"] for c in customers.values()} - set(STATE_TO_CITY)
    if missing_states:
        sys.exit(f"STOP: states without a city in STATE_TO_CITY: {sorted(missing_states)}")

    # ---- 1. Electronics orders only (every item in CATEGORIES), plus two documented exclusions --------------
    def last_event(o: dict) -> date:
        """The last thing that really happened to the order: purchase, delivery or a review."""
        events = [day(o["order_purchase_timestamp"]), day(o["order_delivered_customer_date"])]
        events += [day(r["review_creation_date"]) for r in reviews_of[o["order_id"]]]
        return max(d for d in events if d)

    excluded = Counter()
    eligible = []
    for o in sorted(raw["olist_orders_dataset.csv"], key=lambda r: r["order_id"]):
        items = items_of[o["order_id"]]
        if not items or not all(category_of.get(i["product_id"]) in CATEGORIES for i in items):
            continue
        if not payments_of[o["order_id"]]:
            excluded["no payment row"] += 1
        elif o["order_status"] == "delivered" and not o["order_delivered_customer_date"]:
            excluded["delivered but no delivery date"] += 1
        elif (last_event(o) - day(o["order_purchase_timestamp"])).days > WINDOW_DAYS:
            excluded["real story longer than 90 days"] += 1   # cannot fit the window with its real durations
        else:
            eligible.append(o)

    # ---- 2. The random sample (real status mix kept: no status is favoured) ----------------------------------
    sample = rng.sample(eligible, SAMPLE_SIZE)

    # ---- 3. Dates: one shift (whole days) per order -----------------------------------------------------------
    # The order's real story (purchase -> last event) lasts `span` days. Its new purchase date is drawn at random
    # between window_start and today - span, so the WHOLE story fits in the window and nothing that happened
    # is after today. Every date of the order moves by the same number of days, so all real durations
    # (purchase -> promised, purchase -> delivered, delivered -> review) stay exactly the same.
    # Only the promised date of an order not delivered yet may be after today (it is a promise, not an event).
    shift_days = {}
    for o in sample:
        purchase = day(o["order_purchase_timestamp"])
        span = (last_event(o) - purchase).days
        new_purchase = window_start + timedelta(days=rng.randint(0, WINDOW_DAYS - span))
        shift_days[o["order_id"]] = (new_purchase - purchase).days

    def moved(timestamp: str, olist_order_id: str) -> str | None:
        d = day(timestamp)
        return (d + timedelta(days=shift_days[olist_order_id])).isoformat() if d else None

    # New ids follow the (new) purchase date, like a real shop's order numbers.
    sample.sort(key=lambda o: (moved(o["order_purchase_timestamp"], o["order_id"]), o["order_id"]))

    # ---- 4. Orders, users, products, reviews ------------------------------------------------------------------
    user_id_of, user_rows = {}, []          # customer_unique_id -> our user id
    product_id_of, product_prices = {}, defaultdict(list)
    orders, reviews, olist_status_of = [], [], {}

    for n, o in enumerate(sample):
        oid = FIRST_ORDER_ID + n
        customer = customers[o["customer_id"]]
        unique = customer["customer_unique_id"]   # one real person (a repeat buyer has several customer_id)
        if unique not in user_id_of:
            user_id_of[unique] = FIRST_USER_ID + len(user_id_of)
            user_rows.append({"id": user_id_of[unique], "state": customer["customer_state"], "source_id": unique})

        # Items: Olist has one row per unit; the same product and price twice = one line with qty 2.
        lines = {}
        for i in sorted(items_of[o["order_id"]], key=lambda r: int(r["order_item_id"])):
            if i["product_id"] not in product_id_of:
                product_id_of[i["product_id"]] = FIRST_PRODUCT_ID + len(product_id_of)
            pid, price = product_id_of[i["product_id"]], tnd(float(i["price"]), rate)
            product_prices[pid].append(price)
            line = lines.setdefault((pid, price), {"product_id": pid, "name": None, "qty": 0, "price": price})
            line["qty"] += 1

        payments = payments_of[o["order_id"]]
        cash_on_delivery = any(p["payment_type"] == "boleto" for p in payments)  # boleto -> cash on delivery
        total = tnd(sum(float(p["payment_value"]) for p in payments), rate)
        promised = moved(o["order_estimated_delivery_date"], o["order_id"])

        status = STATUS_MAP[o["order_status"]]
        if status == "shipped" and promised < today.isoformat():
            status = "stuck_at_depot"      # shipped, promised date passed, still not delivered
        delivered = moved(o["order_delivered_customer_date"], o["order_id"]) if status == "delivered" else None
        # Same payment rules as the old seed: cash on delivery is paid only once delivered; cancelled = never paid.
        paid = 0.0 if status == "cancelled" or (cash_on_delivery and status != "delivered") else total

        olist_status_of[oid] = o["order_status"]
        orders.append({"id": oid, "user_id": user_id_of[unique], "items": list(lines.values()),
                       "total": total, "paid": paid, "status": status,
                       "order_date": moved(o["order_purchase_timestamp"], o["order_id"]),
                       "promised_date": promised, "delivered_date": delivered,
                       "carrier": None, "tracking_number": None,
                       "payment": "cash_on_delivery" if cash_on_delivery else "card",
                       "source": "olist", "source_id": o["order_id"], "ai_generated": 0})

        for r in sorted(reviews_of[o["order_id"]], key=lambda r: (r["review_creation_date"], r["review_id"])):
            reviews.append({"id": len(reviews) + 1, "order_id": oid, "score": int(r["review_score"]),
                            "created_at": moved(r["review_creation_date"], o["order_id"]),
                            "source": "olist", "source_id": r["review_id"], "ai_generated": 0})

    # Products: one row per Olist product used. Name generated from its category ("Audio item 0042", numbered
    # per category); price = its median item price in the sample; stock generated.
    olist_product_of = {pid: olist for olist, pid in product_id_of.items()}
    per_category = Counter()
    products = []
    for pid in sorted(olist_product_of):
        category = category_of[olist_product_of[pid]]
        per_category[category] += 1
        products.append({"id": pid, "name": f"{CATEGORIES[category]} item {per_category[category]:04d}",
                         "price": round(statistics.median(product_prices[pid]), 2),
                         "stock": rng.randint(3, 80), "category": translation.get(category, category),
                         "source": "olist", "source_id": olist_product_of[pid], "ai_generated": 1})
    name_of = {p["id"]: p["name"] for p in products}
    for o in orders:
        for line in o["items"]:
            line["name"] = name_of[line["product_id"]]

    # Users: a generated Tunisian name, email and phone like the old seed; city from the real state.
    users = []
    for u in user_rows:
        uid, first, last = u["id"], rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        number = 50_000_000 + uid * 7919          # unique 8-digit number per user (+216 5x xxx xxx)
        users.append({"id": uid, "name": f"{first} {last}",
                      "email": f"{first}.{last.replace(' ', '')}.{uid}@example.com".lower(),
                      "phone": f"+216 {number // 1_000_000} {number // 1000 % 1000:03d} {number % 1000:03d}",
                      "city": STATE_TO_CITY[u["state"]],
                      "source": "olist", "source_id": u["source_id"], "ai_generated": 1})

    # ---- 5. Generated gaps: carrier + tracking number, refunds on real signals -------------------------------
    refunds = []
    scores_of = defaultdict(list)          # order id -> its review scores, oldest first
    for r in reviews:
        scores_of[r["order_id"]].append(r["score"])
    for o in orders:
        if o["status"] not in ("processing", "cancelled"):     # as in the old seed: past processing = has a carrier
            o["carrier"] = rng.choice(["Aramex", "Rapid-Poste"])
            o["tracking_number"] = ("ARX" if o["carrier"] == "Aramex" else "RP") + str(300000 + o["id"])
        # Refund only on REAL signals: delivered late AND the client's (latest) real review is 1 or 2 stars.
        # Rule R-RET-01 (return within 14 days of delivery): the item was delivered, the unhappy client sent
        # it back and got the money back. (R-REF-03 is for orders NOT delivered; R-DMG-01 needs a photo.)
        scores = scores_of[o["id"]]
        late = o["delivered_date"] is not None and o["delivered_date"] > o["promised_date"]
        if late and scores and scores[-1] <= 2:
            refund_day = min(date.fromisoformat(o["delivered_date"]) + timedelta(days=rng.randint(2, 6)), today)
            refunds.append({"id": None, "order_id": o["id"], "amount": o["paid"], "status": "completed",
                            "rule_id": "R-RET-01", "proposal_id": None, "created_at": refund_day.isoformat(),
                            "source": "generated", "source_id": None, "ai_generated": 1})
            o["status"] = "refunded"

    sample_file = {
        "_note": ("Derived from the Olist Brazilian E-Commerce dataset (Kaggle olistbr/brazilian-ecommerce), "
                  "licence CC BY-NC-SA 4.0 (https://creativecommons.org/licenses/by-nc-sa/4.0/). This processed "
                  "sample keeps the same licence; non-commercial university use. See DATA_LICENCES.md. "
                  "Built by scripts/build_shopnova_sample.py (task T15); do not edit by hand."),
        "built_with": {"random_seed": RANDOM_SEED, "sample_size": SAMPLE_SIZE, "sim_today": today.isoformat(),
                       "window_days": WINDOW_DAYS, "brl_to_tnd": rate,
                       "rate_date": config["currency"]["rate_date"],
                       "rate_source": config["currency"]["rate_source"]},
        "users": users, "products": products, "orders": orders, "reviews": reviews, "refunds": refunds,
    }
    # Refund ids are given by seed.py (after the scripted refund 1), so they are left out here.
    for r in refunds:
        del r["id"]
    write_json(sample_file)
    report(sample_file, eligible, excluded, olist_status_of)


def write_json(data: dict) -> None:
    """One row per line: small, and a rebuild shows readable diffs in git."""
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    dump = lambda v: json.dumps(v, ensure_ascii=False, separators=(",", ":"))  # noqa: E731
    parts = [f'"_note":{dump(data["_note"])}', f'"built_with":{dump(data["built_with"])}']
    for table in ("users", "products", "orders", "reviews", "refunds"):
        parts.append(f'"{table}":[\n' + ",\n".join(dump(row) for row in data[table]) + "\n]")
    OUT_PATH.write_text("{\n" + ",\n".join(parts) + "\n}\n", encoding="utf-8", newline="\n")


def report(data: dict, eligible: list, excluded: Counter, olist_status_of: dict) -> None:
    """Print the numbers the T15 report asks for."""
    orders, reviews, users, products = data["orders"], data["reviews"], data["users"], data["products"]
    print(f"Written: {OUT_PATH} ({OUT_PATH.stat().st_size:,} bytes)")
    print(f"Eligible electronics orders: {len(eligible)}; excluded before sampling: {dict(excluded)}")
    print("Categories (products | order lines):")
    line_cat = Counter()
    cat_of = {p["id"]: p["category"] for p in products}
    for o in orders:
        for line in o["items"]:
            line_cat[cat_of[line["product_id"]]] += 1
    for c, n in Counter(p["category"] for p in products).most_common():
        print(f"  {c:<24}{n:>5} | {line_cat[c]:>5}")
    print("Status (Olist original -> ShopNova):")
    for (a, b), n in sorted(Counter((olist_status_of[o["id"]], o["status"]) for o in orders).items()):
        print(f"  {a:<12} -> {b:<15}{n:>5}")
    print("ShopNova status counts:", dict(Counter(o["status"] for o in orders).most_common()))
    delivered = [o for o in orders if o["delivered_date"]]
    late = [o for o in delivered if o["delivered_date"] > o["promised_date"]]
    print(f"Delivered (incl. refunded): {len(delivered)}; late: {len(late)} ({len(late) / len(delivered):.1%})")
    print(f"Cash on delivery: {sum(o['payment'] == 'cash_on_delivery' for o in orders)} orders; "
          f"unpaid now: {sum(o['paid'] == 0 and o['status'] != 'cancelled' for o in orders)}")
    print(f"Refunds: {len(data['refunds'])}; above 300 TND: {sum(r['amount'] > 300 for r in data['refunds'])}")
    print("Review scores:", dict(sorted(Counter(r["score"] for r in reviews).items())),
          f"| reviews {len(reviews)}, orders without review {len(orders) - len({r['order_id'] for r in reviews})}")
    per_user = Counter(o["user_id"] for o in orders)
    print(f"Users: {len(users)}; repeat buyers (2+ orders): {sum(n > 1 for n in per_user.values())}; "
          f"max orders of one user: {max(per_user.values())}")
    print("Cities:", dict(Counter(u["city"] for u in users).most_common()))
    print(f"Products: {len(products)}")
    totals = sorted(o["total"] for o in orders)
    print(f"Total TND min / median / max: {totals[0]} / {statistics.median(totals)} / {totals[-1]}")
    off = sum(abs(sum(i["price"] * i["qty"] for i in o["items"]) - o["total"]) > 0.005 for o in orders)
    print(f"Orders whose total (payments) != sum of item prices (freight etc.): {off}")
    dates = [o["order_date"] for o in orders]
    print(f"Order dates: {min(dates)} .. {max(dates)}; last delivered: {max(o['delivered_date'] for o in delivered)}; "
          f"last review: {max(r['created_at'] for r in reviews)}")
    stuck = [o for o in orders if o["status"] == "stuck_at_depot"]
    print(f"Stuck at depot: {len(stuck)}; promised dates after today (not delivered): "
          f"{sum(o['promised_date'] > data['built_with']['sim_today'] for o in orders if not o['delivered_date'])}")


if __name__ == "__main__":
    main()
