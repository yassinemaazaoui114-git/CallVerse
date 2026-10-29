"""T18 tests: the ShopNova admin pages with Streamlit's AppTest (each admin page loads for the admin and shows
only "please log in" for no login / a user / the supervisor; the sidebar menu shows the admin pages only to the
admin; Manage writes through writes.py; Refund approvals decides through approvals.decide).

No API call (the SLM is offline in tests: its template writes the reply). Temporary accounts file and tickets DB.
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
from callverse.coordinator.coordinator import new_case, review
from callverse.data import db
from callverse.tickets import store

APP = Path(__file__).resolve().parent.parent / "apps" / "shopnova"
sys.path.insert(0, str(APP))   # the pages import shopnova_ui (Streamlit adds this folder itself when it runs)
# shopnova_ui is imported INSIDE the tests only: its os.environ.setdefault(...) lines must run while monkeypatch
# holds the env vars, never at collection time (they would leak "local" / "queue" into all other tests).

ADMIN_PAGES = {"dashboard": APP / "pages" / "4_Admin_dashboard.py", "manage": APP / "pages" / "5_Manage.py",
               "approvals": APP / "pages" / "6_Refund_approvals.py"}
TIMEOUT = 60


@pytest.fixture(autouse=True)
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CALLVERSE_AGENTS_SET", "local")
    monkeypatch.setenv("CALLVERSE_LAYER3_MODE", "queue")
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


def run(path: Path, username: str | None = None) -> AppTest:
    at = AppTest.from_file(str(path), default_timeout=TIMEOUT)
    if username:
        at.session_state["authentication_status"] = True
        at.session_state["username"] = username
    return at.run()


def q(sql: str) -> list:
    with closing(sqlite3.connect(db.db_path())) as con:
        return con.execute(sql).fetchall()


@pytest.mark.parametrize("page", list(ADMIN_PAGES))
def test_admin_pages_load_for_the_admin(page):
    at = run(ADMIN_PAGES[page], "admin")
    assert not at.exception
    assert accounts.LOGIN_MESSAGE not in [i.value for i in at.info]


@pytest.mark.parametrize("username", [None, "sara", "supervisor"])
@pytest.mark.parametrize("page", list(ADMIN_PAGES))
def test_admin_pages_show_only_please_log_in_to_others(page, username):
    at = run(ADMIN_PAGES[page], username)
    assert not at.exception
    assert [i.value for i in at.info] == [accounts.LOGIN_MESSAGE]
    assert len(at.main.button) == 0 and len(at.dataframe) == 0 and len(at.tabs) == 0


def test_menu_shows_admin_pages_only_to_the_admin():
    import shopnova_ui
    labels =lambda session: [m[1] for m in shopnova_ui.menu_items(session)]  # noqa: E731
    everyone = ["Home", "Shop", "My orders", "Help chat"]
    assert labels({}) == everyone
    assert labels({"authentication_status": True, "username": "sara"}) == everyone
    assert labels({"authentication_status": True, "username": "supervisor"}) == everyone
    assert labels({"authentication_status": True, "username": "admin"}) == \
        everyone + ["Admin dashboard", "Manage", "Refund approvals"]


def sidebar_links(at: AppTest) -> list[str]:
    return [link.proto.label for link in at.sidebar.get("page_link")]


def test_the_app_sidebar_of_a_user_has_no_admin_pages():
    at = run(APP / "app.py", "sara")
    assert not at.exception
    assert sidebar_links(at) == ["Home", "Shop", "My orders", "Help chat"]
    at = run(APP / "app.py", "admin")
    assert sidebar_links(at)[-3:] == ["Admin dashboard", "Manage", "Refund approvals"]


def test_dashboard_period_filter():
    at = run(ADMIN_PAGES["dashboard"], "admin")
    assert at.radio(key="dash_days").value == 30
    at.radio(key="dash_days").set_value(90).run()
    assert not at.exception and any("2026-07-12" in c.value for c in at.caption)   # 90 days back from 2026-10-09


def test_manage_adds_a_product_and_shows_a_refused_write():
    at = run(ADMIN_PAGES["manage"], "admin")
    assert [t.label for t in at.tabs] == ["Products", "Orders", "Users", "Refunds", "Admin log"]
    before = q("SELECT COUNT(*) FROM products")[0][0]
    form = at.tabs[0]
    form.text_input[1].input("Gaming Mouse")           # [0] = the search box, [1] = the add form's name
    form.number_input[1].set_value(49.90)              # [0] = page, [1] = price, [2] = stock
    form.number_input[2].set_value(12)
    next(b for b in form.button if b.label == "Add product").click().run()
    assert not at.exception and q("SELECT COUNT(*) FROM products")[0][0] == before + 1
    assert q("SELECT action, admin FROM admin_actions") == [("create_product", "admin")]
    # Refused: no name -> the write's own reason is shown, nothing written.
    next(b for b in at.tabs[0].button if b.label == "Add product").click().run()
    assert any("Not saved: name must not be empty" in e.value for e in at.error)
    assert q("SELECT COUNT(*) FROM products")[0][0] == before + 1


def test_refund_approvals_page_approves_a_pending_refund():
    decision = review({"agent": "B", "action": "refund", "params": {"order_id": 4515, "amount": 378.0},
                       "rule_id": "R-REF-03", "facts_used": {"days_late": 8}, "user_confirmed": True},
                      new_case("T-0001"))
    ticket = store.create_ticket("shopnova", 2)
    approval = store.create_approval(ticket["id"], 4515, 378.0, decision["proposal_id"])
    at = run(ADMIN_PAGES["approvals"], "admin")
    assert "Waiting (1)" in [s.value for s in at.subheader]
    assert any("Youssef Trabelsi" in m.value for m in at.markdown)
    at.button(key=f"refuse_{approval['id']}").click().run()          # Refuse without a reason: refused
    assert any("a reason is required" in e.value for e in at.error)
    at.button(key=f"approve_{approval['id']}").click().run()
    assert not at.exception and any("approved" in s.value for s in at.success)
    assert store.get_approval(approval["id"])["status"] == "approved"
    assert q("SELECT amount FROM refunds WHERE order_id = 4515") == [(378.0,)]
    assert "Waiting (0)" in [s.value for s in at.subheader]
