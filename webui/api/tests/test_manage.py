"""The ShopNova admin's Manage routes (webui/api/manage.py over callverse.data.admin_reads / writes), on the
seeded temp shop database. Checked: who may read / write each table (401, 403 per permission, the Atlas admin
and the supervisor refused, CSRF), that nothing is written when the core refuses (bad values with the field
named, moves the core forbids, a paid order, a missing row), the successful writes with their admin-log row
(create / edit / deactivate / reactivate a product, move and cancel an order, create / edit a client), the
request id (same id + same payload = the recorded answer, no second write; another payload = refused), the
503 without the shop file, and that Atlas's database is never touched.

Run: pytest webui/api/tests -q
"""

import hashlib

import pytest
from conftest import CSRF, login

from callverse.data import admin_reads
from callverse.tools.shopnova_tools import get_order

from webui.api import manage

M = "/api/admin/manage"


@pytest.fixture(autouse=True)
def fresh_registry():
    manage.reset_registry()
    yield
    manage.reset_registry()


def post(client, path, body):
    return client.post(f"{M}{path}", json=body, headers=CSRF)


def log_actions():
    return [(r["admin"], r["action"], r["target_table"], r["target_id"]) for r in admin_reads.admin_log(50)]


# ---------- who may use it ----------

def test_permissions_per_table_and_csrf(client, shop_db):
    assert client.get(f"{M}/products").status_code == 401
    assert client.get(f"{M}/options").status_code == 401
    assert post(client, "/products", {"name": "x", "category": "toys", "price": 1, "stock": 1}).status_code == 401
    for username in ("sara", "hedi", "supervisor", "atlas_admin"):
        login(client, username)
        for table in ("products", "orders", "users", "refunds", "log"):
            r = client.get(f"{M}/{table}")
            assert r.status_code == 403 and r.json()["error"] == "admin_only", (username, table)
        assert client.get(f"{M}/options").status_code == 403
        assert post(client, "/products", {"name": "x", "category": "toys", "price": 1, "stock": 1}).status_code == 403
        assert post(client, "/orders/4511/status", {"status": "shipped"}).status_code == 403
        assert post(client, "/users", {"name": "x", "email": "a@b", "phone": "20123456", "city": "Tunis"}).status_code == 403
        client.post("/api/auth/logout", headers=CSRF)
    login(client, "admin")
    assert client.get(f"{M}/products").status_code == 200
    assert client.get(f"{M}/nothing").status_code == 404
    # a POST without the CSRF header is refused before anything runs
    assert client.post(f"{M}/products", json={"name": "x", "category": "toys", "price": 1, "stock": 1}).status_code == 403
    assert log_actions() == []


def test_tables_options_and_order_moves(client, shop_db):
    login(client, "admin")
    opts = client.get(f"{M}/options").json()
    assert "computers_accessories" in opts["categories"] or opts["categories"]       # the shop's own list
    assert opts["cities"] and "processing" in opts["statuses"]
    assert opts["limits"] == {"max_name": 100, "max_price": 100000, "max_stock": 100000}
    body = client.get(f"{M}/products", params={"search": "smart"}).json()
    assert body["page_size"] == 50 and body["total"] >= 1 and all("smart" in r["name"].lower() for r in body["items"])
    orders = {r["id"]: r for r in client.get(f"{M}/orders", params={"search": "45"}).json()["items"]}
    from callverse.data import writes
    assert orders[4511]["moves"] == ["shipped"] and orders[4511]["cancel_blocked"] == writes.PAID_CANCEL_MESSAGE   # processing, paid by card
    assert orders[4514]["moves"] == ["shipped", "cancelled"] and orders[4514]["cancel_blocked"] is None        # cash on delivery, paid 0
    assert orders[4510]["moves"] == ["out_for_delivery", "stuck_at_depot"]                                  # shipped
    assert orders[4512]["moves"] == ["out_for_delivery"]                                                   # stuck at depot
    assert orders[4505]["moves"] == [] and orders[4505]["cancel_blocked"] is None                           # delivered
    users = client.get(f"{M}/users", params={"search": "sara"}).json()
    assert users["items"][0]["id"] == 1
    assert client.get(f"{M}/refunds").json()["total"] >= 1
    assert client.get(f"{M}/log").json()["items"] == []


# ---------- products ----------

def test_product_create_edit_deactivate_reactivate_with_log(client, shop_db):
    login(client, "admin")
    opts = client.get(f"{M}/options").json()
    cat = opts["categories"][0]
    r = post(client, "/products", {"name": "  Test lamp ", "category": cat, "price": 49.9, "stock": 3, "client_id": "c1"})
    assert r.status_code == 200, r.text
    row = r.json()["row"]
    assert row["name"] == "Test lamp" and row["price"] == 49.9 and row["stock"] == 3 and row["active"] == 1 and row["source"] == "app"
    pid = row["id"]
    # edit only the changed fields
    r = post(client, f"/products/{pid}", {"price": 59.5, "client_id": "c2"})
    assert r.status_code == 200 and r.json()["row"]["price"] == 59.5 and r.json()["row"]["name"] == "Test lamp"
    # deactivate (soft delete), twice is refused, reactivate
    r = post(client, f"/products/{pid}/deactivate", {"client_id": "c3"})
    assert r.status_code == 200 and r.json()["row"]["active"] == 0
    r = post(client, f"/products/{pid}/deactivate", {"client_id": "c4"})
    assert r.status_code == 409 and r.json()["error"] == "refused" and "already" in r.json()["message"]
    r = post(client, f"/products/{pid}/reactivate", {"client_id": "c5"})
    assert r.status_code == 200 and r.json()["row"]["active"] == 1
    assert admin_reads.product_row(pid)["active"] == 1
    assert [a for a in log_actions() if a[3] == str(pid)] == [
        ("admin", "reactivate_product", "products", str(pid)), ("admin", "deactivate_product", "products", str(pid)),
        ("admin", "update_product", "products", str(pid)), ("admin", "create_product", "products", str(pid))]


def test_product_bad_values_name_the_field_and_write_nothing(client, shop_db):
    login(client, "admin")
    cat = client.get(f"{M}/options").json()["categories"][0]
    before = client.get(f"{M}/products").json()["total"]
    for body, field in (({"name": " ", "category": cat, "price": 10, "stock": 1}, "name"),
                        ({"name": "x", "category": "no-such", "price": 10, "stock": 1}, "category"),
                        ({"name": "x", "category": cat, "price": 0, "stock": 1}, "price"),
                        ({"name": "x", "category": cat, "price": 10.123, "stock": 1}, "price"),
                        ({"name": "x", "category": cat, "price": 10, "stock": -1}, "stock")):
        r = post(client, "/products", body)
        assert r.status_code == 400 and r.json()["error"] == "invalid" and r.json()["field"] == field, (body, r.text)
    assert post(client, "/products/999999", {"price": 5}).status_code == 404
    assert post(client, "/products/1", {"client_id": "x"}).status_code == 409          # nothing to change
    assert client.get(f"{M}/products").json()["total"] == before and log_actions() == []


# ---------- orders ----------

def test_order_moves_and_refusals(client, shop_db):
    login(client, "admin")
    assert post(client, "/orders/4511/status", {"status": "delivered"}).status_code == 409          # not an allowed move
    assert post(client, "/orders/4511/status", {"status": "refunded"}).status_code == 409           # never by hand
    assert post(client, "/orders/4511/status", {"status": "weird"}).status_code == 400              # unknown status
    r = post(client, "/orders/4505/status", {"status": "cancelled"})                                 # delivered: not cancellable
    assert r.status_code == 409 and r.json()["error"] == "refused"
    r = post(client, "/orders/4505/status", {"status": "shipped"})
    assert r.status_code == 409
    assert post(client, "/orders/999999/status", {"status": "shipped"}).status_code == 404
    assert get_order(4511)["status"] == "processing" and log_actions() == []
    r = post(client, "/orders/4511/status", {"status": "shipped", "client_id": "m1"})
    assert r.status_code == 200 and r.json()["row"]["status"] == "shipped" and get_order(4511)["status"] == "shipped"
    # cash on delivery, unpaid, processing: may be cancelled; the stock comes back (the core's rule)
    stock_before = admin_reads.product_row(5)["stock"]
    r = post(client, "/orders/4514/status", {"status": "cancelled", "client_id": "m2"})
    assert r.status_code == 200 and get_order(4514)["status"] == "cancelled"
    assert admin_reads.product_row(5)["stock"] == stock_before + 1
    assert log_actions()[:2] == [("admin", "admin_set_order_status", "orders", "4514"), ("admin", "admin_set_order_status", "orders", "4511")]


def test_paid_processing_order_cannot_be_cancelled(client, shop_db):
    """A paid, not shipped order: the list says why (the core's sentence) and the write is refused."""
    login(client, "admin")
    post(client, "/users", {"name": "Paid Client", "email": "paid@example.test", "phone": "20 000 000", "city": "Tunis"})
    from callverse.data import writes
    made = writes.create_order(1, 1, 1, "card")
    assert "error" not in made, made
    order = client.get(f"{M}/orders", params={"search": str(made["id"])}).json()["items"][0]
    assert order["status"] == "processing" and order["paid"] > 0
    assert order["moves"] == ["shipped"] and order["cancel_blocked"] == writes.PAID_CANCEL_MESSAGE
    r = post(client, f"/orders/{made['id']}/status", {"status": "cancelled"})
    assert r.status_code == 409 and r.json()["message"] == writes.PAID_CANCEL_MESSAGE
    assert get_order(made["id"])["status"] == "processing"


# ---------- clients ----------

def test_user_create_edit_and_uniqueness(client, shop_db):
    login(client, "admin")
    city = client.get(f"{M}/options").json()["cities"][0]
    r = post(client, "/users", {"name": "Nour Test", "email": "nour@example.test", "phone": "+216 20 123 456", "city": city, "client_id": "u1"})
    assert r.status_code == 200, r.text
    row = r.json()["row"]
    assert row["phone"] == "+216 20 123 456" and row["city"] == city and row["source"] == "app"
    r = post(client, "/users", {"name": "Other", "email": "NOUR@example.test", "phone": "20 999 999", "city": city})
    assert r.status_code == 400 and r.json()["field"] == "email" and "already used" in r.json()["message"]
    r = post(client, "/users", {"name": "Other", "email": "other@example.test", "phone": "123", "city": city})
    assert r.status_code == 400 and r.json()["field"] == "phone"
    r = post(client, "/users", {"name": "Other", "email": "other@example.test", "phone": "20 999 999", "city": "Atlantis"})
    assert r.status_code == 400 and r.json()["field"] == "city"
    r = post(client, f"/users/{row['id']}", {"name": "Nour Tested", "client_id": "u2"})
    assert r.status_code == 200 and r.json()["row"]["name"] == "Nour Tested" and r.json()["row"]["email"] == "nour@example.test"
    assert post(client, "/users/999999", {"name": "x"}).status_code == 404
    assert log_actions()[:2] == [("admin", "update_user", "users", str(row["id"])), ("admin", "create_user", "users", str(row["id"]))]


# ---------- request id: never twice ----------

def test_same_request_id_writes_once_and_another_payload_is_refused(client, shop_db):
    login(client, "admin")
    cat = client.get(f"{M}/options").json()["categories"][0]
    body = {"name": "Once only", "category": cat, "price": 10, "stock": 1, "client_id": "once"}
    first = post(client, "/products", body)
    again = post(client, "/products", body)
    assert first.status_code == 200 and again.status_code == 200
    assert again.json()["recorded"] is True and again.json()["row"]["id"] == first.json()["row"]["id"]
    assert client.get(f"{M}/products", params={"search": "Once only"}).json()["total"] == 1
    other = post(client, "/products", {**body, "price": 11})
    assert other.status_code == 409 and other.json()["error"] == "client_id_reused"
    assert client.get(f"{M}/products", params={"search": "Once only"}).json()["total"] == 1
    # a refused write is not recorded: the same id may be used for the corrected request
    bad = post(client, "/products", {"name": "", "category": cat, "price": 10, "stock": 1, "client_id": "fix"})
    assert bad.status_code == 400
    good = post(client, "/products", {"name": "Fixed", "category": cat, "price": 10, "stock": 1, "client_id": "fix"})
    assert good.status_code == 200 and "recorded" not in good.json()


# ---------- the files ----------

def test_missing_shop_database_is_503_and_atlas_is_never_touched(client, isolated_env):
    login(client, "admin")
    assert client.get(f"{M}/products").status_code == 503
    assert post(client, "/products", {"name": "x", "category": "toys", "price": 1, "stock": 1}).status_code == 503
    assert not (isolated_env / "shopnova_never_created.db").exists()
    assert not (isolated_env / "atlas_never_created.db").exists()


def test_writes_leave_atlas_alone(client, shop_db, atlas_db_seeded):
    digest = hashlib.sha256(atlas_db_seeded.read_bytes()).hexdigest()
    login(client, "admin")
    cat = client.get(f"{M}/options").json()["categories"][0]
    assert post(client, "/products", {"name": "Shop only", "category": cat, "price": 1, "stock": 1}).status_code == 200
    assert hashlib.sha256(atlas_db_seeded.read_bytes()).hexdigest() == digest
