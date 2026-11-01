"""Step 2 tests: the ShopNova customer routes (own orders only), on a seeded TEMPORARY shopnova.db.

Run: pytest webui/api/tests -q
"""

import hashlib

from conftest import CSRF, login

from callverse.data import shop_reads
from callverse.tools import shopnova_tools

ROUTES = ("/api/shop/orders", "/api/shop/orders/4505")


def ids(body: dict) -> list[int]:
    return [o["id"] for o in body["orders"]]


def test_customer_sees_only_her_own_orders(client, shop_db):
    login(client, "sara")   # user_id 1 in the accounts file
    r = client.get("/api/shop/orders")
    assert r.status_code == 200
    body = r.json()
    expected = [o["id"] for o in shop_reads.user_orders(1)]   # the same function as the Streamlit page
    assert ids(body) == expected and body["count"] == len(expected) and len(expected) > 0
    assert set(ids(body)).isdisjoint({o["id"] for o in shop_reads.user_orders(2)})
    assert body["sim_today"] == "2026-10-09"
    row = body["orders"][0]
    assert set(row) == {"id", "status", "order_date", "promised_date", "delivered_date", "total", "paid", "payment",
                        "carrier", "tracking_number", "items_count", "items_preview", "refunds_count"}


def test_another_customer_cannot_open_the_order_by_changing_the_url(client, shop_db):
    saras = shop_reads.user_orders(1)[0]["id"]
    login(client, "youssef")   # user_id 2
    r = client.get(f"/api/shop/orders/{saras}")
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    missing = client.get("/api/shop/orders/999999")
    assert missing.status_code == 404 and missing.json() == r.json() | {"message": missing.json()["message"]}
    # the two answers differ only by the id in the words: nothing says whether the order exists
    assert r.json()["message"].replace(str(saras), "N") == missing.json()["message"].replace("999999", "N")


def test_atlas_user_with_the_same_numeric_id_is_rejected(client, shop_db):
    login(client, "hedi")   # Atlas, user_id 1 like sara
    for path in ROUTES:
        r = client.get(path)
        assert r.status_code == 403 and r.json()["error"] == "customer_only", path


def test_admin_supervisor_and_no_login_are_rejected(client, shop_db):
    for path in ROUTES:
        assert client.get(path).status_code == 401, path
    for username in ("admin", "supervisor", "atlas_admin"):
        login(client, username)
        for path in ROUTES:
            r = client.get(path)
            assert r.status_code == 403 and r.json()["error"] == "customer_only", (username, path)
        client.post("/api/auth/logout", headers=CSRF)


def test_owned_order_detail_matches_the_read_functions(client, shop_db):
    login(client, "sara")
    own = shop_reads.user_orders(1)[0]
    r = client.get(f"/api/shop/orders/{own['id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["order"] == own                                   # lines, dates, payment, refunds as the page reads them
    assert body["tracking"] == shopnova_tools.get_tracking(own["id"])
    assert body["refunds"] == shopnova_tools.get_refunds(own["id"])
    assert body["tracking"]["checked_on"] == "2026-10-09"          # the simulation date, never the real clock
    assert body["sim_today"] == "2026-10-09"


def test_empty_orders_list(client, shop_db):
    """A customer without orders gets an empty list (not an error). User 5 (leila) may have orders in the
    sample, so the test points the account at a user id that has none."""
    import yaml
    from callverse.auth import accounts
    path = accounts.accounts_path()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["credentials"]["usernames"]["leila"]["user_id"] = 999999
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    login(client, "leila")
    r = client.get("/api/shop/orders")
    assert r.status_code == 200 and r.json()["orders"] == [] and r.json()["count"] == 0


def test_unfamiliar_status_is_passed_through(client, shop_db, monkeypatch):
    """A status the UI has never seen (e.g. one T14c adds) arrives as plain text; nothing filters it."""
    own = shop_reads.user_orders(1)[0]
    real = shop_reads.user_orders

    def with_new_status(user_id):
        rows = real(user_id)
        for o in rows:
            if o["id"] == own["id"]:
                o["status"] = "held_for_photo_proof"
        return rows
    monkeypatch.setattr(shop_reads, "user_orders", with_new_status)
    login(client, "sara")
    assert client.get("/api/shop/orders").json()["orders"][0]["status"] == "held_for_photo_proof"
    assert client.get(f"/api/shop/orders/{own['id']}").json()["order"]["status"] == "held_for_photo_proof"


def test_reads_write_nothing(client, shop_db):
    login(client, "sara")
    own = shop_reads.user_orders(1)[0]["id"]
    before = hashlib.sha256(shop_db.read_bytes()).hexdigest()
    for path in ("/api/shop/orders", f"/api/shop/orders/{own}", "/api/shop/orders/999999"):
        client.get(path)
    assert hashlib.sha256(shop_db.read_bytes()).hexdigest() == before
    assert not (shop_db.parent / "atlas_never_created.db").exists()


def test_missing_shop_database_gives_503_and_creates_nothing(client, isolated_env):
    """No shop_db fixture here: the configured shopnova.db does not exist. Both routes answer 503
    setup_required BEFORE any read function runs, and the file is still absent afterwards."""
    from callverse.data import db as shopnova_db
    path = shopnova_db.db_path()
    assert not path.exists()
    login(client, "sara")
    for route in ROUTES:
        r = client.get(route)
        assert r.status_code == 503 and r.json()["error"] == "setup_required", route
        assert "shopnova.db" in r.json()["message"]
    assert not path.exists()
    # the guard comes after the role check: a non-customer still gets 403, not a hint about the file
    client.post("/api/auth/logout", headers=CSRF)
    login(client, "supervisor")
    assert client.get("/api/shop/orders").status_code == 403


def test_console_stays_usable_without_shop_data(supervisor, isolated_env):
    from callverse.data import db as shopnova_db
    path = shopnova_db.db_path()
    assert not path.exists()
    for route in ("/api/console/tickets", "/api/console/tickets/filters", "/api/company"):
        assert supervisor.get(route).status_code == 200, route
    assert supervisor.get("/api/console/tickets/T-0001").status_code == 404
    assert not path.exists()   # read-only connections never create the company file
