"""T17 tests: the ShopNova app pages with Streamlit's AppTest (each page loads; protected pages show only
"please log in" without a login; Buy is refused without a login; a logged-in user sees only their orders).

No API call: the chat's channel is replaced by a fake that writes a ticket like the real one would.
The accounts file is a temporary one with a test hash; "logged in" = the session state streamlit-authenticator
sets after a password check (authentication_status True + username).
"""

import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import bcrypt
import pytest
import yaml
from streamlit.testing.v1 import AppTest

from callverse.auth import accounts
from callverse.channels import web_chat
from callverse.data import db
from callverse.tickets import store

APP = Path(__file__).resolve().parent.parent / "apps" / "shopnova"
sys.path.insert(0, str(APP))   # the pages import shopnova_ui (Streamlit adds this folder itself when it runs)
PAGES = {"home": APP / "Home.py", "shop": APP / "pages" / "1_Shop.py", "orders": APP / "pages" / "2_My_orders.py",
         "chat": APP / "pages" / "3_Help_chat.py"}
TIMEOUT = 60


@pytest.fixture(autouse=True)
def app_env(tmp_path, monkeypatch):
    """Temporary accounts file and tickets DB; the models switch is put back after each test."""
    monkeypatch.setenv("CALLVERSE_AGENTS_SET", "local")
    hashed = bcrypt.hashpw(b"test-only", bcrypt.gensalt(rounds=4)).decode()
    users = {u: {"name": name, "roles": [role], "user_id": uid, "password": hashed}
             for u, name, _, role, uid in accounts.DEMO_ACCOUNTS}
    path = tmp_path / "accounts.yaml"
    path.write_text(yaml.safe_dump({"credentials": {"usernames": users},
                                    "cookie": {"name": "t", "key": "k" * 32, "expiry_days": 1}}), encoding="utf-8")
    accounts.use_accounts(path)
    store.use_db(tmp_path / "callverse_test.db")
    yield
    accounts.use_accounts(accounts.DEFAULT_ACCOUNTS_PATH)
    store.use_db(store.DEFAULT_DB_PATH)


def run(page: str, username: str | None = None) -> AppTest:
    at = AppTest.from_file(str(PAGES[page]), default_timeout=TIMEOUT)
    if username:
        at.session_state["authentication_status"] = True
        at.session_state["username"] = username
    return at.run()


def texts(at: AppTest) -> str:
    return "\n".join([m.value for m in at.markdown] + [i.value for i in at.info] + [w.value for w in at.warning]
                     + [s.value for s in at.success] + [c.value for c in at.caption])


def order_count() -> int:
    with closing(sqlite3.connect(db.db_path())) as con:
        return con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]


@pytest.mark.parametrize("page", list(PAGES))
def test_each_page_loads_without_login(page):
    at = run(page)
    assert not at.exception
    assert len(at.sidebar.text_input) == 2       # the login form (username, password) is in the sidebar


@pytest.mark.parametrize("page", ["orders", "chat"])
def test_protected_pages_show_only_please_log_in(page):
    at = run(page)
    assert [i.value for i in at.info] == [accounts.LOGIN_MESSAGE]
    assert len(at.dataframe) == 0 and len(at.chat_input) == 0 and len(at.main.button) == 0


@pytest.mark.parametrize("page", ["orders", "chat"])
def test_protected_pages_refuse_the_wrong_role(page):
    at = run(page, "admin")
    assert [i.value for i in at.info] == [accounts.LOGIN_MESSAGE]


def test_shop_shows_featured_then_24_products_per_page():
    at = run("shop")
    buttons = [b.key for b in at.main.button if b.key and "_buy_" in b.key]
    assert len(buttons) == 6 + 24
    assert buttons[:6] == [f"featured_buy_{i}" for i in range(1, 7)] and buttons[6] == "all_buy_1"
    assert "Wireless Earbuds" in texts(at) and "🎧" in texts(at)


def test_shop_search_and_category_filter():
    at = run("shop")
    at.text_input(key="shop_search").input("earbuds").run()
    assert "1 products" in texts(at)
    at.text_input(key="shop_search").input("").run()
    at.selectbox(key="shop_category").select("pc_gamer").run()
    assert "1 products" in texts(at)


def test_buy_is_refused_without_login():
    before = order_count()
    at = run("shop")
    at.button(key="featured_buy_1").click().run()
    assert "Please log in to buy (left sidebar)." in texts(at)
    assert not [b for b in at.main.button if b.key == "buy_confirm"]
    assert order_count() == before


def test_logged_in_user_buys_and_the_order_is_hers():
    before = order_count()
    at = run("shop", "sara")
    at.button(key="all_buy_3").click().run()
    at.number_input(key="buy_qty").set_value(2).run()
    at.button(key="buy_confirm").click().run()
    assert not at.exception and order_count() == before + 1
    assert "is placed" in texts(at)
    with closing(sqlite3.connect(db.db_path())) as con:
        user_id, items = con.execute("SELECT user_id, items FROM orders ORDER BY id DESC LIMIT 1").fetchone()
    assert user_id == 1 and '"qty": 2' in items


def test_my_orders_shows_only_the_users_own_orders():
    at = run("orders", "sara")             # Sara = user 1: orders 4509 and 4512 (and her real orders, if any)
    shown = texts(at)
    assert "Order 4512" in shown and "Order 4509" in shown
    assert "Order 4510" not in shown and "Order 4515" not in shown     # Youssef's orders
    assert any(b.key == "ask_4512" for b in at.main.button)


def test_ask_about_this_order_sets_the_chat_order():
    at = run("orders", "sara")
    at.button(key="ask_4512").click().run()
    assert at.session_state["chat_order"] == 4512


def test_help_chat_sends_through_the_channel_and_shows_the_ticket(monkeypatch):
    sent = []

    def fake_send(user_id, company, text, ticket_id=None, on_step=None, **kwargs):
        sent.append((user_id, company, text, ticket_id))
        on_step("Checking your order…")
        t = store.ticket_for_message(company, user_id, ticket_id)
        store.add_message(t["id"], "user", text)
        store.add_message(t["id"], "assistant", "Your order 4512 is delayed at the delivery depot.")
        store.update_ticket(t["id"], status="Solved")
        return {"ticket_id": t["id"], "status": "Solved", "reply": "..."}

    monkeypatch.setattr(web_chat, "send", fake_send)
    at = run("chat", "sara")
    assert len(at.chat_input) == 1 and "New conversation" in texts(at)
    at.chat_input[0].set_value("Where is my order 4512?").run()
    assert not at.exception
    assert sent == [(1, "shopnova", "Where is my order 4512?", None)]
    assert "Ticket **T-0001**" in texts(at)
    assert [m.name for m in at.chat_message] == ["user", "assistant"]

    at.button(key="new_chat").click().run()
    assert "New conversation" in texts(at) and at.session_state["chat_ticket_id"] is None


def test_help_chat_has_one_input_and_passes_the_asked_order(monkeypatch):
    sent = []

    def fake_send(user_id, company, text, ticket_id=None, on_step=None, about_order=None, **kwargs):
        sent.append(about_order)
        t = store.ticket_for_message(company, user_id, ticket_id)
        return {"ticket_id": t["id"], "status": "New", "reply": "..."}

    monkeypatch.setattr(web_chat, "send", fake_send)
    at = AppTest.from_file(str(PAGES["chat"]), default_timeout=TIMEOUT)
    at.session_state["authentication_status"] = True
    at.session_state["username"] = "sara"
    at.session_state["chat_order"] = 4512
    at.run()
    assert "About order 4512" in texts(at)
    assert len(at.chat_input) == 1 and len(at.main.text_input) == 0      # one input box, no extra form
    at.chat_input[0].set_value("Is it late?").run()
    assert sent == [4512]
    at.button(key="new_chat").click().run()
    assert "About order 4512" not in texts(at)
