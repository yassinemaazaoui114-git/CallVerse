"""T17 tests: the new write create_order (checks, stock, labels) and the role check of the demo logins.

No API call. The accounts file is a temporary one with a test hash (never a real password).
"""

import json
import sqlite3
from contextlib import closing

import bcrypt
import pytest
import yaml

from callverse.auth import accounts
from callverse.data import db
from callverse.data.writes import create_order
from callverse.tools import registry


def _row(sql, *args):
    with closing(sqlite3.connect(db.db_path())) as con:
        con.row_factory = sqlite3.Row
        return con.execute(sql, args).fetchone()


# ---------- create_order ----------

def test_card_order_is_created_and_stock_goes_down():
    stock = _row("SELECT stock FROM products WHERE id = 1")["stock"]
    order = create_order(1, 1, 2, "card")
    assert order["status"] == "processing" and order["user_id"] == 1
    assert order["total"] == pytest.approx(119.80) and order["paid"] == pytest.approx(119.80)
    assert order["order_date"] == "2026-10-09" and order["promised_date"] == "2026-11-03"   # + 25 days
    assert order["items"] == [{"product_id": 1, "name": "Wireless Earbuds", "qty": 2, "price": 59.90}]
    assert order["delivered_date"] is None and order["carrier"] is None
    assert (order["source"], order["ai_generated"], order["scripted"]) == (None, 0, 0)
    assert _row("SELECT stock FROM products WHERE id = 1")["stock"] == stock - 2
    assert json.loads(_row("SELECT items FROM orders WHERE id = ?", order["id"])["items"]) == order["items"]


def test_cash_on_delivery_pays_nothing_yet():
    order = create_order(5, 4, 1, "cash_on_delivery")
    assert order["total"] == 189.00 and order["paid"] == 0


def test_order_ids_follow_the_highest_id():
    biggest = _row("SELECT MAX(id) AS m FROM orders")["m"]
    assert create_order(1, 2, 1, "card")["id"] == biggest + 1


@pytest.mark.parametrize("args, words", [
    ((999999, 1, 1, "card"), "user 999999 not found"),
    ((1, 999999, 1, "card"), "product 999999 not found"),
    ((1, 1, 0, "card"), "quantity"),
    ((1, 1, 11, "card"), "quantity"),
    ((1, 1, 2.0, "card"), "quantity"),
    ((1, 1, True, "card"), "quantity"),
    ((1, 1, "2", "card"), "quantity"),
    ((1, 1, 1, "paypal"), "payment"),
    ((1, 1, 1, None), "payment"),
    (("1", 1, 1, "card"), "user_id"),
])
def test_bad_orders_are_refused_and_nothing_changes(args, words):
    orders, stock = _row("SELECT COUNT(*) AS n FROM orders")["n"], _row("SELECT stock FROM products WHERE id = 1")["stock"]
    out = create_order(*args)
    assert words in out["error"]
    assert _row("SELECT COUNT(*) AS n FROM orders")["n"] == orders
    assert _row("SELECT stock FROM products WHERE id = 1")["stock"] == stock


def test_not_enough_stock_is_refused():
    with closing(sqlite3.connect(db.db_path())) as con:
        con.execute("UPDATE products SET stock = 1 WHERE id = 4")
        con.commit()
    assert "not enough stock" in create_order(1, 4, 2, "card")["error"]
    assert "id" in create_order(1, 4, 1, "card")
    assert "not enough stock" in create_order(1, 4, 1, "card")["error"]     # stock is now 0


def test_create_order_is_in_no_allow_list():
    assert all("create_order" not in tools for tools in registry.ALLOW_LISTS.values())
    assert "create_order" not in registry.TOOL_FUNCTIONS


# ---------- roles ----------

@pytest.fixture
def accounts_file(tmp_path):
    """A temporary accounts file in streamlit-authenticator's format (one test hash, cheap bcrypt rounds)."""
    hashed = bcrypt.hashpw(b"test-only", bcrypt.gensalt(rounds=4)).decode()
    users = {name: {"name": name, "roles": [role], "user_id": uid, "password": hashed}
             for name, _, _, role, uid in accounts.DEMO_ACCOUNTS}
    users["broken"] = {"name": "no link", "roles": ["user"], "user_id": None, "password": hashed}
    path = tmp_path / "accounts.yaml"
    path.write_text(yaml.safe_dump({"credentials": {"usernames": users},
                                    "cookie": {"name": "t", "key": "k" * 32, "expiry_days": 1}}), encoding="utf-8")
    accounts.use_accounts(path)
    yield path
    accounts.use_accounts(accounts.DEFAULT_ACCOUNTS_PATH)


def test_role_check_refuses_without_login(accounts_file):
    assert accounts.check_role({}, "user") is None
    assert accounts.check_role({"authentication_status": None, "username": "sara"}, "user") is None
    assert accounts.check_role({"authentication_status": False, "username": "sara"}, "user") is None


def test_role_check_refuses_the_wrong_role(accounts_file):
    logged = {"authentication_status": True}
    assert accounts.check_role({**logged, "username": "admin"}, "user") is None
    assert accounts.check_role({**logged, "username": "sara"}, "admin") is None
    assert accounts.check_role({**logged, "username": "supervisor"}, "user") is None
    assert accounts.check_role({**logged, "username": "nobody"}, "user") is None
    assert accounts.check_role({**logged, "username": "broken"}, "user") is None   # no ShopNova user linked
    with pytest.raises(ValueError):
        accounts.check_role({**logged, "username": "sara"}, "root")


def test_role_check_gives_the_user_id_from_the_file(accounts_file):
    # the session's own "roles" are ignored: the file decides
    found = accounts.check_role({"authentication_status": True, "username": "karim", "roles": ["admin"]}, "user")
    assert found == {"username": "karim", "name": "karim", "role": "user", "user_id": 4}
    assert "password" not in found


def test_no_accounts_file_means_nobody_is_logged_in(tmp_path):
    accounts.use_accounts(tmp_path / "missing.yaml")
    try:
        assert accounts.load_accounts() is None and accounts.authenticator() is None
        assert accounts.check_role({"authentication_status": True, "username": "sara"}, "user") is None
    finally:
        accounts.use_accounts(accounts.DEFAULT_ACCOUNTS_PATH)


def test_example_file_has_the_demo_accounts_and_no_password():
    data = yaml.safe_load(accounts.EXAMPLE_PATH.read_text(encoding="utf-8"))
    users = data["credentials"]["usernames"]
    assert [(u, users[u]["roles"][0], users[u]["user_id"]) for u in users] == \
        [(u, role, uid) for u, _, _, role, uid in accounts.DEMO_ACCOUNTS]
    assert all("password" not in entry for entry in users.values())
