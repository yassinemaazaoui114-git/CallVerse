"""T18 tests: admin permissions and the admin's write functions in writes.py (input checks, admin log rows,
no row on a refusal, old orders keep their prices, inactive products, cancel only from processing).

No API call. Each test gets a fresh copy of the seeded shopnova.db (conftest).
"""

import json
import sqlite3
from contextlib import closing

import pytest

from callverse.auth import accounts
from callverse.data import db, shop_reads, writes
from callverse.tools import registry

ADMIN = "admin"


def q(sql: str, args=()) -> list:
    with closing(sqlite3.connect(db.db_path())) as con:
        return con.execute(sql, args).fetchall()


def log_count() -> int:
    return q("SELECT COUNT(*) FROM admin_actions")[0][0]


def last_log() -> dict:
    with closing(sqlite3.connect(db.db_path())) as con:
        con.row_factory = sqlite3.Row
        return dict(con.execute("SELECT * FROM admin_actions ORDER BY id DESC LIMIT 1").fetchone())


# ---------- permissions ----------

@pytest.fixture
def accounts_file(tmp_path):
    users = {u: {"name": name, "roles": [role], "user_id": uid, "password": "not-a-real-hash"}
             for u, name, _, role, uid in accounts.DEMO_ACCOUNTS}
    path = tmp_path / "accounts.yaml"
    import yaml
    path.write_text(yaml.safe_dump({"credentials": {"usernames": users}, "cookie": {"key": "k"}}), encoding="utf-8")
    accounts.use_accounts(path)
    yield
    accounts.use_accounts(accounts.DEFAULT_ACCOUNTS_PATH)


@pytest.mark.parametrize("perm", accounts.PERMISSIONS["admin"])
def test_only_the_admin_has_the_admin_permissions(accounts_file, perm):
    assert accounts.check_permission({}, perm) is None                                          # no login
    for username in ("sara", "supervisor"):
        assert accounts.check_permission({"authentication_status": True, "username": username}, perm) is None
    assert accounts.check_permission({"authentication_status": None, "username": "admin"}, perm) is None
    assert accounts.check_permission({"authentication_status": True, "username": "admin"}, perm)["role"] == "admin"


def test_unknown_permission_is_an_error(accounts_file):
    with pytest.raises(ValueError):
        accounts.check_permission({"authentication_status": True, "username": "admin"}, "delete_everything")


def test_no_admin_write_is_in_any_allow_list():
    admin_writes = {"create_product", "update_product", "deactivate_product", "reactivate_product",
                    "admin_set_order_status", "create_user", "update_user", "admin_decide_refund"}
    listed = {name for names in registry.ALLOW_LISTS.values() for name in names}
    assert not admin_writes & listed and not admin_writes & set(registry.TOOL_FUNCTIONS)
    assert all(callable(getattr(writes, name)) for name in admin_writes)


# ---------- products ----------

def test_create_product_writes_the_row_and_its_log_line():
    out = writes.create_product(ADMIN, "  Gaming Mouse  ", "computers_accessories", 49.9, 12)
    assert out["name"] == "Gaming Mouse" and out["price"] == 49.9 and out["active"] == 1
    assert out["id"] == q("SELECT MAX(id) FROM products")[0][0]
    assert (out["source"], out["ai_generated"], out["scripted"]) == ("app", 0, 0)
    log = last_log()
    assert (log["admin"], log["action"], log["target_table"], log["target_id"]) == \
        (ADMIN, "create_product", "products", str(out["id"]))
    assert log["before"] is None and json.loads(log["after"])["name"] == "Gaming Mouse"
    assert log["at"].startswith("2026-10-09")                                    # simulation clock


@pytest.mark.parametrize("name, category, price, stock, why", [
    ("", "audio", 10.0, 1, "name must not be empty"),
    ("   ", "audio", 10.0, 1, "name must not be empty"),
    ("x" * 101, "audio", 10.0, 1, "at most 100 characters"),
    ("Mouse", "audio", 0, 1, "price must be"),
    ("Mouse", "audio", -5.0, 1, "price must be"),
    ("Mouse", "audio", 100_000.01, 1, "price must be"),
    ("Mouse", "audio", "10", 1, "price must be"),
    ("Mouse", "audio", float("nan"), 1, "price must be"),
    ("Mouse", "audio", 10.555, 1, "at most 2 decimals"),
    ("Mouse", "audio", 10.0, -1, "stock must be"),
    ("Mouse", "audio", 10.0, 1.5, "stock must be"),
    ("Mouse", "audio", 10.0, 100_001, "stock must be"),
    ("Mouse", "audio", 10.0, True, "stock must be"),
    ("Mouse", "toys", 10.0, 1, "not one of the shop's categories"),
])
def test_create_product_refusals_write_nothing(name, category, price, stock, why):
    products, logs = q("SELECT COUNT(*) FROM products")[0][0], log_count()
    out = writes.create_product(ADMIN, name, category, price, stock)
    assert why in out["error"]
    assert q("SELECT COUNT(*) FROM products")[0][0] == products and log_count() == logs


def test_admin_name_is_required():
    assert "admin" in writes.create_product("", "Mouse", "audio", 10.0, 1)["error"]
    assert "admin" in writes.admin_set_order_status(None, 4511, "shipped")["error"]
    assert log_count() == 0


def test_price_edit_keeps_the_price_of_old_orders():
    old_items = q("SELECT items FROM orders WHERE id = 4512")[0][0]
    out = writes.update_product(ADMIN, 1, price=79.90)
    assert out["price"] == 79.90
    assert q("SELECT items FROM orders WHERE id = 4512")[0][0] == old_items      # still 59.90 in the order
    assert json.loads(old_items)[0]["price"] == 59.90
    log = last_log()
    assert json.loads(log["before"])["price"] == 59.90 and json.loads(log["after"])["price"] == 79.90


def test_update_product_refusals():
    logs = log_count()
    assert "not found" in writes.update_product(ADMIN, 999_999, price=10.0)["error"]
    assert "cannot be changed" in writes.update_product(ADMIN, 1, active=0)["error"]
    assert "nothing to change" in writes.update_product(ADMIN, 1)["error"]
    assert "price must be" in writes.update_product(ADMIN, 1, price=0)["error"]
    assert log_count() == logs and q("SELECT price FROM products WHERE id = 1")[0][0] == 59.90


def test_inactive_product_is_hidden_and_cannot_be_bought():
    assert writes.deactivate_product(ADMIN, 1)["active"] == 0
    assert shop_reads.product(1) is None and 1 not in [p["id"] for p in shop_reads.featured()]
    assert shop_reads.products(search="earbuds")["total"] == 0
    assert "not on sale" in writes.create_order(1, 1, 1, "card")["error"]
    assert "already inactive" in writes.deactivate_product(ADMIN, 1)["error"]
    order_4512 = next(o for o in shop_reads.user_orders(1) if o["id"] == 4512)
    assert order_4512["items"][0]["name"] == "Wireless Earbuds"                   # old orders still show it
    assert writes.reactivate_product(ADMIN, 1)["active"] == 1
    assert "error" not in writes.create_order(1, 1, 1, "card")
    assert [r[0] for r in q("SELECT action FROM admin_actions ORDER BY id")] == \
        ["deactivate_product", "reactivate_product"]


# ---------- orders ----------

def test_cancel_only_from_processing_and_the_stock_goes_back():
    # 4514: processing, cash on delivery (paid 0.00), items = 1 x Bluetooth Speaker (5)
    stock = q("SELECT stock FROM products WHERE id = 5")[0][0]
    out = writes.admin_set_order_status(ADMIN, 4514, "cancelled")
    assert out["status"] == "cancelled"
    assert q("SELECT stock FROM products WHERE id = 5")[0][0] == stock + 1
    log = last_log()
    assert log["action"] == "admin_set_order_status" and json.loads(log["before"])["status"] == "processing"

    logs = log_count()
    assert "not shipped yet" in writes.admin_set_order_status(ADMIN, 4510, "cancelled")["error"]   # shipped
    assert "not allowed" in writes.admin_set_order_status(ADMIN, 4514, "shipped")["error"]         # cancelled
    assert log_count() == logs and q("SELECT status FROM orders WHERE id = 4510")[0][0] == "shipped"


def test_a_paid_order_is_never_cancelled():
    # 4511: processing but paid by card (54.40 TND): it must be refunded first.
    stock = dict(q("SELECT id, stock FROM products WHERE id IN (2, 3)"))
    out = writes.admin_set_order_status(ADMIN, 4511, "cancelled")
    assert out["error"] == "This order is paid: it must be refunded first."
    assert q("SELECT status FROM orders WHERE id = 4511")[0][0] == "processing"
    assert dict(q("SELECT id, stock FROM products WHERE id IN (2, 3)")) == stock and log_count() == 0


def test_refunded_is_never_set_by_hand_and_moves_follow_status_moves():
    assert "never set by hand" in writes.admin_set_order_status(ADMIN, 4512, "refunded")["error"]
    assert "not allowed" in writes.admin_set_order_status(ADMIN, 4514, "delivered")["error"]
    assert "unknown status" in writes.admin_set_order_status(ADMIN, 4514, "lost")["error"]
    assert "not found" in writes.admin_set_order_status(ADMIN, 1, "shipped")["error"]
    assert log_count() == 0
    out = writes.admin_set_order_status(ADMIN, 4514, "shipped")                   # processing -> shipped
    assert out["status"] == "shipped"
    assert q("SELECT event FROM events WHERE order_id = 4514") == [("shipped",)]  # same as set_order_status


# ---------- users ----------

def test_create_user_checks_and_formats_the_phone():
    out = writes.create_user(ADMIN, "Nour Haddad", "nour@example.com", "20 123-456", "Sousse")
    assert out["phone"] == "+216 20 123 456" and out["city"] == "Sousse" and out["source"] == "app"
    assert out["id"] == q("SELECT MAX(id) FROM users")[0][0]
    assert last_log()["action"] == "create_user"
    assert writes.create_user(ADMIN, "Ali", "ali@example.com", "+216 21 000 111", "Tunis")["phone"] == "+216 21 000 111"


@pytest.mark.parametrize("email, phone, city, why", [
    ("SARA@example.com", "29 000 001", "Tunis", "already used"),        # Sara's email (any case)
    ("new@example.com", "20111222", "Tunis", "already used"),           # Sara's phone, typed without spaces
    ("no-at-sign", "29 000 001", "Tunis", "must contain '@'"),
    ("new@example.com", "1234567", "Tunis", "8 digits"),
    ("new@example.com", "123456789", "Tunis", "8 digits"),
    ("new@example.com", "2900000a", "Tunis", "8 digits"),
    ("new@example.com", "29 000 001", "Paris", "not a city"),
])
def test_create_user_refusals_write_nothing(email, phone, city, why):
    users, logs = q("SELECT COUNT(*) FROM users")[0][0], log_count()
    assert why in writes.create_user(ADMIN, "Nour", email, phone, city)["error"]
    assert q("SELECT COUNT(*) FROM users")[0][0] == users and log_count() == logs


def test_update_user_keeps_unique_checks_but_allows_own_values():
    assert writes.update_user(ADMIN, 1, city="Sfax", email="sara@example.com")["city"] == "Sfax"   # own email: ok
    assert "already used" in writes.update_user(ADMIN, 1, email="youssef@example.com")["error"]
    assert "cannot be changed" in writes.update_user(ADMIN, 1, id=99)["error"]
    assert "not found" in writes.update_user(ADMIN, 999_999, city="Sfax")["error"]
    assert [r[0] for r in q("SELECT action FROM admin_actions")] == ["update_user"]
