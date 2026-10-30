"""T22 tests: the Atlas Travel app with Streamlit's AppTest, accounts with a company, the account script, the Atlas admin
log, the code's confirmation decision (proposal columns + Console line), and the wall between the two companies.

No API call: the agents get a fake LLM, the SLM is offline (conftest: its template writes the reply), the quota check
is replaced. Temporary accounts file (fake hashes), tickets database and atlas.db.
"""

import json
import shutil
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import bcrypt
import pytest
import yaml
from streamlit.testing.v1 import AppTest

from callverse.auth import accounts
from callverse.channels import approvals, web_chat
from callverse.console import reads as console
from callverse.coordinator import atlas_coordinator as gate
from callverse.coordinator.coordinator import new_case, review as shopnova_review
from callverse.data.atlas import atlas_app_reads, reads, writes
from callverse.data.atlas import db as atlas_db
from callverse.data.atlas.seed import seed
from callverse.tickets import store
from scripts import create_demo_accounts as script

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "apps" / "atlas"
SHOPNOVA = ROOT / "apps" / "shopnova"
sys.path[:0] = [str(APP), str(SHOPNOVA)]   # the pages import atlas_ui / shopnova_ui (Streamlit adds this itself)
# atlas_ui is imported INSIDE the tests only: its os.environ.setdefault(...) lines must run while monkeypatch holds
# the env vars (same reason as tests/test_shopnova_admin_app.py).

HOME, BOOKINGS, CHAT = APP / "Home.py", APP / "pages" / "1_My_bookings.py", APP / "pages" / "2_Help_chat.py"
DASHBOARD, APPROVALS, RECORDS = (APP / "pages" / "3_Admin_dashboard.py", APP / "pages" / "4_Approvals.py",
                                 APP / "pages" / "5_Records.py")
USER_PAGES, ADMIN_PAGES = [BOOKINGS, CHAT], [DASHBOARD, APPROVALS, RECORDS]
TIMEOUT = 60
QUOTE = "as the client wrote it"
COMPENSATION_MESSAGE = "Flight 7004 got me to Chicago more than three hours late. I want the compensation I am owed."


@pytest.fixture(scope="module")
def atlas_template(tmp_path_factory):
    return seed(tmp_path_factory.mktemp("atlas_template") / "atlas.db")


def accounts_file(path: Path, with_company: bool = True) -> Path:
    hashed = bcrypt.hashpw(b"test-only", bcrypt.gensalt(rounds=4)).decode()
    users = {}
    for username, name, _, role, user_id in accounts.DEMO_ACCOUNTS:
        users[username] = {"name": name, "roles": [role], "user_id": user_id, "password": hashed}
        if with_company:
            users[username]["company"] = accounts.demo_company(username, role)
    path.write_text(yaml.safe_dump({"credentials": {"usernames": users},
                                    "cookie": {"name": "t", "key": "k" * 32, "expiry_days": 1}}), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def app_env(tmp_path, atlas_template, monkeypatch):
    monkeypatch.setenv("CALLVERSE_AGENTS_SET", "local")
    monkeypatch.setenv("CALLVERSE_LAYER3_MODE", "queue")
    monkeypatch.setattr(web_chat, "agent_b_ready", lambda: True)
    accounts.use_accounts(accounts_file(tmp_path / "accounts.yaml"))
    shutil.copyfile(atlas_template, tmp_path / "atlas.db")
    atlas_db.use_db(tmp_path / "atlas.db")
    store.use_db(tmp_path / "callverse.db")
    yield
    accounts.use_accounts(accounts.DEFAULT_ACCOUNTS_PATH)
    atlas_db.use_db(atlas_db.DEFAULT_DB_PATH)
    store.use_db(store.DEFAULT_DB_PATH)


def run(path: Path, username: str | None = None, **state) -> AppTest:
    at = AppTest.from_file(str(path), default_timeout=TIMEOUT)
    if username:
        at.session_state["authentication_status"] = True
        at.session_state["username"] = username
    for key, value in state.items():
        at.session_state[key] = value
    return at.run()


def q(statement: str, *params) -> list:
    con = atlas_db.connect()
    try:
        return [tuple(r) for r in con.execute(statement, params).fetchall()]
    finally:
        con.close()


def log_rows() -> list:
    return q("SELECT admin, action, target_table, target_id FROM admin_actions ORDER BY id")


def session(username: str | None) -> dict:
    return {"authentication_status": True, "username": username} if username else {}


def all_text(at: AppTest) -> str:
    return " ".join(e.value for kind in (at.markdown, at.caption, at.subheader, at.info) for e in kind)


def fake_agent(tool: str, booking_type: str, booking_id: int, rule_id: str, quote: str = QUOTE, confirmed: bool = True):
    """A fake Agent B that calls one proposal tool, quoting the client's real words, then answers."""
    used = []

    def fake(role_key, messages, tools=None):
        if used:
            return SimpleNamespace(content="It is sent for checking.", tool_calls=None)
        used.append(True)
        said = messages[1]["content"].split("\n\n")[0] if quote == QUOTE else quote
        arguments = {"booking_type": booking_type, "booking_id": booking_id, "rule_id": rule_id,
                     "facts_used": {"read": True}, "user_confirmed": confirmed, "user_quote": said}
        call = SimpleNamespace(id="call_1", function=SimpleNamespace(name=tool, arguments=json.dumps(arguments)))
        return SimpleNamespace(content=None, tool_calls=[call])
    return fake


def pending_compensation() -> tuple[dict, dict]:
    """Nizar's flight 7004 case, waiting for the Atlas admin."""
    out = web_chat.send(5, "atlas", COMPENSATION_MESSAGE,
                        chat_fn=fake_agent("propose_compensation", "flight", 7004, "AT-FLT-03"))
    return out, store.approvals("pending", company="atlas")[0]


def pending_shopnova_refund() -> dict:
    decision = shopnova_review({"agent": "B", "action": "refund", "params": {"order_id": 4515, "amount": 378.0},
                                "rule_id": "R-REF-03", "facts_used": {"days_late": 8}, "user_confirmed": True},
                               new_case("T-0001"))
    ticket = store.create_ticket("shopnova", 2)
    return store.create_approval(ticket["id"], 4515, 378.0, decision["proposal_id"])


# ---------- accounts with a company ----------

def test_the_six_new_accounts():
    found = {a[0]: a for a in accounts.DEMO_ACCOUNTS}
    assert len(found) == 13
    for username, user_id in (("hedi", 1), ("sonia", 2), ("tarek", 3), ("lobna", 4), ("nizar", 5)):
        assert found[username][3:] == ("user", user_id) and accounts.demo_company(username, "user") == "atlas"
    assert found["atlas_admin"][3:] == ("admin", None) and accounts.demo_company("atlas_admin", "admin") == "atlas"
    assert accounts.demo_company("sara", "user") == accounts.demo_company("admin", "admin") == "shopnova"
    assert accounts.demo_company("supervisor", "supervisor") is None


def test_each_name_of_an_atlas_user_is_its_database_name():
    for username, name, email, role, user_id in accounts.DEMO_ACCOUNTS:
        if role == "user" and username in accounts.ATLAS_ACCOUNTS:
            assert reads.get_user(user_id=user_id)["name"] == name and reads.get_user(user_id=user_id)["email"] == email


def test_an_account_of_the_other_company_is_refused():
    sara, hedi = session("sara"), session("hedi")
    assert accounts.check_role(sara, "user")["user_id"] == 1
    assert accounts.check_role(sara, "user", "atlas") is None
    assert accounts.check_role(hedi, "user") is None                 # no company given = ShopNova's app
    assert accounts.check_role(hedi, "user", "atlas")["user_id"] == 1


@pytest.mark.parametrize("perm", accounts.ALL_PERMISSIONS)
def test_each_admin_has_its_permissions_only_at_its_company(perm):
    assert accounts.check_permission(session("atlas_admin"), perm, "atlas")["username"] == "atlas_admin"
    assert accounts.check_permission(session("atlas_admin"), perm) is None
    assert accounts.check_permission(session("admin"), perm, "atlas") is None
    assert accounts.check_permission(session("admin"), perm)["username"] == "admin"


def test_the_supervisor_still_opens_the_console_and_has_no_company():
    assert accounts.check_role(session("supervisor"), "supervisor")["username"] == "supervisor"
    assert accounts.company_of(accounts.account("supervisor")) is None
    assert accounts.check_permission(session("supervisor"), "approve_refunds", "atlas") is None
    assert accounts.check_role(session("supervisor"), "user", "atlas") is None


def test_an_old_accounts_file_without_company_is_shopnova(tmp_path):
    accounts.use_accounts(accounts_file(tmp_path / "old.yaml", with_company=False))
    assert accounts.company_of(accounts.account("sara")) == accounts.company_of(accounts.account("admin")) == "shopnova"
    assert accounts.company_of(accounts.account("supervisor")) is None
    assert accounts.check_role(session("sara"), "user") is not None
    assert accounts.check_role(session("sara"), "user", "atlas") is None


# ---------- the account script (fake hashes, temporary file) ----------

@pytest.fixture
def old_file(tmp_path, monkeypatch):
    """An accounts file of before T22: the 7 old accounts, no company, fake hashes."""
    salt = bcrypt.gensalt(rounds=4)
    monkeypatch.setattr(script.bcrypt, "gensalt", lambda: salt)
    users = {u: {"name": name, "email": email, "roles": [role], "user_id": uid, "password": f"fake-hash-{u}"}
             for u, name, email, role, uid in accounts.DEMO_ACCOUNTS if u not in accounts.ATLAS_ACCOUNTS}
    path = tmp_path / "accounts_old.yaml"
    path.write_text(yaml.safe_dump({"credentials": {"usernames": users},
                                    "cookie": {"name": "callverse_auth", "key": "keep-this-key", "expiry_days": 1}}),
                    encoding="utf-8")
    return path


def test_the_script_adds_only_the_missing_accounts_and_keeps_the_hashes(old_file):
    asked = []
    script.main(old_file, lambda username: (asked.append(username), ("a-test-password", False))[1])
    data = yaml.safe_load(old_file.read_text(encoding="utf-8"))
    users = data["credentials"]["usernames"]
    assert asked == list(accounts.ATLAS_ACCOUNTS)                                  # no password asked for an old account
    old = [a[0] for a in accounts.DEMO_ACCOUNTS if a[0] not in accounts.ATLAS_ACCOUNTS]
    assert len(old) == 7 and all(users[u]["password"] == f"fake-hash-{u}" for u in old)
    assert data["cookie"]["key"] == "keep-this-key"
    assert users["sara"]["company"] == "shopnova" and users["supervisor"]["company"] is None
    assert users["hedi"]["company"] == "atlas" and users["hedi"]["user_id"] == 1
    assert users["atlas_admin"]["roles"] == ["admin"]
    assert bcrypt.checkpw(b"a-test-password", users["nizar"]["password"].encode())


def test_the_script_run_again_changes_nothing(old_file):
    script.main(old_file, lambda username: ("a-test-password", False))
    before = old_file.read_text(encoding="utf-8")

    def never(username):
        raise AssertionError(f"asked a password for {username}")
    script.main(old_file, never)
    assert old_file.read_text(encoding="utf-8") == before


def test_the_script_shows_only_random_passwords_of_new_accounts(old_file):
    data = script.load_or_new(old_file)
    added, shown = script.add_missing(data, lambda username: ("random-one", True))
    assert len(added) == 6 and {u for u, _ in shown} == set(added)


def test_a_new_file_gets_all_accounts_and_a_cookie_key(tmp_path, monkeypatch):
    salt = bcrypt.gensalt(rounds=4)
    monkeypatch.setattr(script.bcrypt, "gensalt", lambda: salt)
    path = tmp_path / "new.yaml"
    script.main(path, lambda username: ("a-test-password", False))
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert len(data["credentials"]["usernames"]) == 13 and len(data["cookie"]["key"]) == 64


# ---------- pages: who sees what ----------

def test_home_loads_for_everyone():
    at = run(HOME)
    assert not at.exception and any("Welcome to Atlas Travel" in m.value for m in at.markdown)


@pytest.mark.parametrize("page", USER_PAGES)
def test_user_pages_load_for_an_atlas_user(page):
    at = run(page, "hedi")
    assert not at.exception and accounts.LOGIN_MESSAGE not in [i.value for i in at.info]


@pytest.mark.parametrize("page", ADMIN_PAGES)
def test_admin_pages_load_for_the_atlas_admin(page):
    at = run(page, "atlas_admin")
    assert not at.exception and accounts.LOGIN_MESSAGE not in [i.value for i in at.info]


def only_please_log_in(at: AppTest) -> None:
    assert not at.exception
    assert [i.value for i in at.info] == [accounts.LOGIN_MESSAGE]
    assert len(at.main.button) == 0 and len(at.dataframe) == 0 and len(at.tabs) == 0 and len(at.chat_input) == 0


@pytest.mark.parametrize("username", [None, "sara", "admin", "supervisor", "atlas_admin"])
@pytest.mark.parametrize("page", USER_PAGES)
def test_user_pages_show_only_please_log_in_to_others(page, username):
    only_please_log_in(run(page, username))


@pytest.mark.parametrize("username", [None, "sara", "admin", "supervisor", "hedi"])
@pytest.mark.parametrize("page", ADMIN_PAGES)
def test_admin_pages_show_only_please_log_in_to_others(page, username):
    only_please_log_in(run(page, username))


@pytest.mark.parametrize("page, username", [(SHOPNOVA / "pages" / "2_My_orders.py", "hedi"),
                                            (SHOPNOVA / "pages" / "3_Help_chat.py", "hedi"),
                                            (SHOPNOVA / "pages" / "6_Refund_approvals.py", "atlas_admin"),
                                            (SHOPNOVA / "pages" / "4_Admin_dashboard.py", "atlas_admin")])
def test_shopnova_pages_refuse_atlas_accounts(page, username):
    only_please_log_in(run(page, username))


def test_the_menu():
    import atlas_ui
    labels = lambda name: [m[1] for m in atlas_ui.menu_items(session(name))]  # noqa: E731
    assert labels("hedi") == ["Home", "My bookings", "Help chat"]
    assert labels("atlas_admin") == ["Admin dashboard", "Approvals", "Records"]
    assert labels(None) == labels("sara") == labels("admin") == labels("supervisor") == []


def test_the_app_draws_the_menu_of_the_account():
    at = run(APP / "app.py", "hedi")
    assert not at.exception
    assert [link.proto.label for link in at.sidebar.get("page_link")] == ["Home", "My bookings", "Help chat"]
    at = run(APP / "app.py", "atlas_admin")
    assert [link.proto.label for link in at.sidebar.get("page_link")] == ["Admin dashboard", "Approvals", "Records"]


def test_the_app_is_on_its_own_port_and_localhost_only():
    config = (APP / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert 'address = "127.0.0.1"' in config and "port = 8503" in config
    assert "--server.address 127.0.0.1 --server.port 8503" in (ROOT / "start_atlas.ps1").read_text(encoding="utf-8")


def test_the_login_cookie_is_its_own():
    import atlas_ui
    assert atlas_ui.COOKIE_SUFFIX == "_atlas"


# ---------- My bookings ----------

def test_my_bookings_shows_only_the_users_own_bookings():
    text = all_text(run(BOOKINGS, "hedi"))
    assert "Booking 7005" in text and "Booking 7001" in text and "Booking 7011" in text
    assert "Booking 7004" not in text and "Booking 7002" not in text and "Booking 7012" not in text
    text = all_text(run(BOOKINGS, "nizar"))
    assert "Booking 7004" in text and "Booking 7010" in text and "Booking 7005" not in text


def test_same_user_id_two_companies_never_mix():
    # Sara and Hedi are both user 1: Sara, in Atlas's app, sees nothing of Hedi's.
    assert "7005" not in all_text(run(BOOKINGS, "sara"))


def test_flight_details_in_plain_words():
    flights = {f["id"]: f for f in atlas_app_reads.my_bookings(5)["flights"]}
    f = flights[7004]
    assert f["route"] == "New York (JFK) → Chicago (ORD)" and f["airline"] == "Delta Air Lines Inc."
    assert f["flight_number"] == "DL 1204" and f["departure"] == "2026-10-05 08:15"
    assert f["situation"] == "delayed 200 minutes (the airline)"
    assert flights[7010]["situation"] == "scheduled"
    assert atlas_app_reads.my_bookings(4)["flights"][0]["situation"] == "cancelled (weather)"


def test_hotel_details_in_plain_words():
    h = {b["id"]: b for b in atlas_app_reads.my_bookings(3)["hotels"]}[7003]
    assert (h["nights"], h["room_booked"], h["room_given"]) == (3, "D", "A")
    assert h["deposit"] == "refundable deposit" and (h["total"], h["paid"]) == (360.0, 360.0)
    assert h["hotel"] and h["arrival"] == "2026-10-01" and h["status"] == "stayed"


def test_refunds_and_compensation_show_under_their_booking():
    out, approval = pending_compensation()
    approvals.decide(approval["id"], "atlas_admin", True)
    at = run(BOOKINGS, "nizar")
    assert any("Compensation of **839.50 TND** · approved · 2026-10-09" in m.value for m in at.markdown)
    assert any(f"New reply on {out['ticket_id']}" in i.value for i in at.info)


def test_ask_about_this_booking_opens_the_chat_with_the_label():
    at = run(BOOKINGS, "nizar")
    assert at.button(key="ask_7004").label == "Ask about this booking"
    at = run(CHAT, "nizar", chat_booking=7004)
    assert any("📦 About booking 7004" in c.value for c in at.caption)


# ---------- About booking N ----------

def test_about_booking_is_added_only_when_no_number_is_typed():
    assert web_chat.with_order("Is it late?", 7004, "atlas") == "Is it late? (booking 7004)"
    assert web_chat.with_order("Is booking 7011 confirmed?", 7004, "atlas") == "Is booking 7011 confirmed?"
    assert web_chat.with_order("Is flight 7011 late?", 7004, "atlas") == "Is flight 7011 late?"
    assert web_chat.with_order("Is it late?", None, "atlas") == "Is it late?"
    assert web_chat.with_order("Is it late?", 4512) == "Is it late? (order 4512)"       # ShopNova: as before


def test_the_channel_uses_the_added_number():
    out = web_chat.send(5, "atlas", "Is it late?", about_order=7004,
                        chat_fn=fake_agent("propose_compensation", "flight", 7004, "AT-FLT-03"))
    assert store.messages(out["ticket_id"])[0]["text"] == "Is it late? (booking 7004)"


def test_the_added_number_goes_through_the_identity_check():
    out = web_chat.send(1, "atlas", "Is it late?", about_order=7004)       # 7004 is Nizar's, this is Hedi
    assert out["reply"] == web_chat.NOT_YOUR_BOOKING_REPLY


# ---------- Help chat ----------

def test_help_chat_sends_through_the_channel_as_atlas(monkeypatch):
    calls = []

    def fake_send(user_id, company, text, ticket_id=None, on_step=None, about_order=None):
        calls.append((user_id, company, text, ticket_id, about_order))
        ticket = store.ticket_for_message(company, user_id, ticket_id)
        store.add_message(ticket["id"], "user", text)
        return {"ticket_id": ticket["id"]}
    monkeypatch.setattr(web_chat, "send", fake_send)
    at = run(CHAT, "nizar", chat_booking=7004)
    at.chat_input[0].set_value("Is it late?").run()
    assert not at.exception and calls == [(5, "atlas", "Is it late?", None, 7004)]
    assert any("T-0001" in m.value for m in at.markdown)


def test_help_chat_shows_the_ticket_and_new_chat_clears_it():
    out, _ = pending_compensation()
    at = run(CHAT, "nizar")
    assert any(out["ticket_id"] in m.value and "Waiting for finance" in m.value for m in at.markdown)
    assert any(COMPENSATION_MESSAGE in m.value for m in at.markdown)
    at.button(key="new_chat").click().run()
    assert not at.exception and any("New conversation" in m.value for m in at.markdown)


def test_new_reply_notice_then_opening_marks_it_read():
    out, approval = pending_compensation()
    approvals.decide(approval["id"], "atlas_admin", True)
    at = run(CHAT, "nizar", chat_ticket_id=None)     # a new chat is on screen: the reply is on another ticket
    assert any(f"New reply on {out['ticket_id']}" in i.value for i in at.info)
    at.button(key=f"open_{out['ticket_id']}").click().run()
    assert not at.exception and store.get_ticket(out["ticket_id"])["user_unread"] == 0


def test_help_chat_never_shows_a_ticket_of_the_other_company():
    ticket = store.create_ticket("shopnova", 1)
    store.add_message(ticket["id"], "user", "my shopnova secret")
    at = run(CHAT, "hedi", chat_ticket_id=ticket["id"])
    assert "my shopnova secret" not in all_text(at) and not at.chat_message


# ---------- Approvals ----------

def test_approvals_shows_the_case_with_all_its_facts():
    _, approval = pending_compensation()
    at = run(APPROVALS, "atlas_admin")
    text = all_text(at)
    assert "Waiting (1)" in text and "Compensation of 839.50 TND · flight booking 7004 · Nizar Haddad" in text
    assert "rule AT-FLT-03" in text and approval["ticket_id"] in text and approval["proposal_id"] in text
    assert "Confirmed by code: **yes (compensation request + quote found)**" in text
    assert get_rule_title("AT-FLT-03") in text


def get_rule_title(rule_id: str) -> str:
    from callverse.kb.policies import get_policy
    return get_policy(rule_id, "atlas")["title"]


def test_approve_writes_rows_log_message_solved_and_unread():
    out, approval = pending_compensation()
    at = run(APPROVALS, "atlas_admin")
    at.button(key=f"approve_{approval['id']}").click().run()
    assert not at.exception and any("approved" in s.value for s in at.success)
    assert "Waiting (0)" in [s.value for s in at.subheader] and "Decided (1)" in [s.value for s in at.subheader]
    assert store.get_approval(approval["id"])["status"] == "approved"
    assert q("SELECT amount, status, rule_id FROM compensations") == [(839.5, "approved", "AT-FLT-03")]
    compensation_id = q("SELECT id FROM compensations")[0][0]
    assert log_rows() == [("atlas_admin", "approve_compensation", "compensations", str(compensation_id))]
    after = json.loads(q("SELECT after FROM admin_actions")[0][0])
    assert after["approval_id"] == approval["id"] and after["compensation"]["amount"] == 839.5
    last = store.messages(out["ticket_id"])[-1]
    assert last["sender"] == "assistant" and "839.50 TND for booking 7004 is approved" in last["text"]
    ticket = store.get_ticket(out["ticket_id"])
    assert (ticket["status"], ticket["user_unread"]) == ("Solved", 1)


def test_refuse_needs_a_reason_then_writes_the_log_and_pays_nothing():
    out, approval = pending_compensation()
    at = run(APPROVALS, "atlas_admin")
    at.button(key=f"refuse_{approval['id']}").click().run()
    assert any("a reason is required" in e.value for e in at.error)
    assert store.get_approval(approval["id"])["status"] == "pending" and log_rows() == []
    at.text_input(key=f"reason_{approval['id']}").input("secret internal reason").run()
    at.button(key=f"refuse_{approval['id']}").click().run()
    assert not at.exception and store.get_approval(approval["id"])["status"] == "refused"
    assert q("SELECT COUNT(*) FROM compensations") == [(0,)]
    assert log_rows() == [("atlas_admin", "refuse_compensation", "proposals", approval["proposal_id"])]
    assert json.loads(q("SELECT after FROM admin_actions")[0][0])["reason"] == "secret internal reason"
    last = store.messages(out["ticket_id"])[-1]["text"]
    assert "secret" not in last and "We cannot approve a compensation of 839.50 TND" in last
    ticket = store.get_ticket(out["ticket_id"])
    assert (ticket["status"], ticket["user_unread"]) == ("Solved", 1)


def test_a_big_refund_is_logged_on_its_refund_row():
    web_chat.send(2, "atlas", "Flight booking 7006 left five hours late. I want a refund.",
                  chat_fn=fake_agent("propose_refund", "flight", 7006, "AT-FLT-04"))
    approval = store.approvals("pending", company="atlas")[0]
    assert "error" not in approvals.decide(approval["id"], "atlas_admin", True, company="atlas")
    refund_id = q("SELECT id FROM refunds WHERE proposal_id = ?", approval["proposal_id"])[0][0]
    assert log_rows() == [("atlas_admin", "approve_refund", "refunds", str(refund_id))]


def test_a_cancellation_decided_by_finance_is_logged_on_the_booking():
    proposal_id = writes.record_proposal({"agent": "B", "action": "cancel_hotel",
                                          "params": {"booking_type": "hotel", "booking_id": 7011},
                                          "rule_id": "AT-HOT-02", "facts_used": {}})["id"]
    writes.set_proposal_amount(proposal_id, 220.0)
    written = writes.admin_decide("atlas_admin", proposal_id, True, approval_id=1)
    assert written["booking_status"] == "cancelled" and written["refund"]["amount"] == 220.0
    assert log_rows() == [("atlas_admin", "approve_cancel_hotel", "hotel_bookings", "7011")]
    before, after = q("SELECT before, after FROM admin_actions")[0]
    assert json.loads(before) == {"booking_status": "confirmed"} and json.loads(after)["refund"]["amount"] == 220.0


def failing_log(*args, **kwargs):
    raise sqlite3.OperationalError("disk full")


def test_a_forced_log_failure_writes_nothing_and_the_approval_stays_pending(monkeypatch):
    out, approval = pending_compensation()
    monkeypatch.setattr(writes, "_log_action", failing_log)
    at = run(APPROVALS, "atlas_admin")
    at.button(key=f"approve_{approval['id']}").click().run()
    assert not at.exception and any("nothing was done" in e.value and "nothing was written" in e.value for e in at.error)
    assert store.get_approval(approval["id"])["status"] == "pending"
    assert writes.get_proposal(approval["proposal_id"])["decision"] is None
    assert q("SELECT COUNT(*) FROM compensations") == [(0,)] and log_rows() == []
    assert store.get_ticket(out["ticket_id"])["status"] == "Waiting for finance"
    assert len(store.messages(out["ticket_id"])) == 2                                 # no new reply


def test_a_forced_log_failure_on_a_cancellation_cancels_nothing(monkeypatch):
    proposal_id = writes.record_proposal({"agent": "B", "action": "cancel_hotel",
                                          "params": {"booking_type": "hotel", "booking_id": 7011},
                                          "rule_id": "AT-HOT-02", "facts_used": {}})["id"]
    writes.set_proposal_amount(proposal_id, 220.0)
    monkeypatch.setattr(writes, "_log_action", failing_log)
    assert "nothing was written" in writes.admin_decide("atlas_admin", proposal_id, True)["error"]
    assert q("SELECT status FROM hotel_bookings WHERE id = 7011") == [("confirmed",)]
    assert q("SELECT COUNT(*) FROM refunds") == [(0,)]
    assert writes.get_proposal(proposal_id)["decision"] is None


def test_the_rights_are_checked_again_just_before_the_decision():
    _, approval = pending_compensation()
    at = run(APPROVALS, "atlas_admin")
    at.session_state["username"] = "admin"                     # the session changed after the page was drawn
    at.button(key=f"approve_{approval['id']}").click().run()
    assert store.get_approval(approval["id"])["status"] == "pending" and log_rows() == []


# ---------- the wall between the two companies ----------

def test_atlas_approvals_never_show_shopnova_cases():
    pending_shopnova_refund()
    at = run(APPROVALS, "atlas_admin")
    assert "Waiting (0)" in [s.value for s in at.subheader] and "4515" not in all_text(at)


def test_shopnova_approvals_never_show_atlas_cases():
    pending_compensation()
    at = run(SHOPNOVA / "pages" / "6_Refund_approvals.py", "admin")
    assert "Waiting (0)" in [s.value for s in at.subheader] and "7004" not in all_text(at)


def test_a_decision_with_a_company_refuses_the_other_companys_approval():
    shopnova = pending_shopnova_refund()
    _, atlas = pending_compensation()
    assert approvals.decide(shopnova["id"], "atlas_admin", True, company="atlas") == \
        {"error": f"approval {shopnova['id']} not found"}
    assert approvals.decide(atlas["id"], "admin", True, company="shopnova") == {"error": f"approval {atlas['id']} not found"}
    assert store.get_approval(shopnova["id"])["status"] == store.get_approval(atlas["id"])["status"] == "pending"


# ---------- the code's confirmation decision ----------

def proposal_row() -> dict:
    return writes.get_proposal(q("SELECT id FROM proposals ORDER BY id DESC LIMIT 1")[0][0])


def test_the_code_said_yes_and_the_agents_flag_is_kept():
    web_chat.send(5, "atlas", COMPENSATION_MESSAGE,
                  chat_fn=fake_agent("propose_compensation", "flight", 7004, "AT-FLT-03", confirmed=False))
    row = proposal_row()
    assert (row["confirmed_by_code"], row["confirmation_reason"]) == (1, "compensation request + quote found")
    assert row["user_confirmed"] is False                                       # the agent's own flag, for the record
    assert store.approvals("pending", company="atlas")                         # the code decided, not the flag


@pytest.mark.parametrize("quote, main_reason, confirmed, why", [
    ("please refund me", "refund_request", True, "refund request + quote found"),
    ("cancel my booking", "cancellation", True, "cancellation + quote found"),
    ("do not refund me", "refund_request", False, "negative sentence"),
    ("something else", "refund_request", False, "quote not in the message"),
    ("", "refund_request", False, "no quote"),
    ("please refund me", "booking_status", False, "the message asks for no action"),
])
def test_confirmation_gives_a_short_reason(quote, main_reason, confirmed, why):
    case = {"main_reason": main_reason, "user_message": "Hello. Please refund me. Do not refund me. Cancel my booking."}
    assert gate.confirmation({"user_quote": quote}, case) == (confirmed, why)
    assert gate.client_confirmed({"user_quote": quote}, case) is confirmed


def test_a_negative_sentence_is_stored_and_the_client_is_asked():
    message = "Please do not cancel my hotel booking 7011."
    case = {**new_case("T-1"), "order_id": 7011, "booking_type": "hotel", "main_reason": "cancellation",
            "user_message": message}
    decision = gate.review({"agent": "B", "action": "cancel_hotel",
                            "params": {"booking_type": "hotel", "booking_id": 7011}, "rule_id": "AT-HOT-02",
                            "facts_used": {}, "user_confirmed": True, "user_quote": message}, case)
    assert decision["outcome"] == "ask_user"
    row = proposal_row()
    assert (row["confirmed_by_code"], row["confirmation_reason"], row["user_confirmed"]) == (0, "negative sentence", True)


def test_a_proposal_sent_back_before_the_check_stays_not_checked():
    case = {**new_case("T-1"), "order_id": 7004, "booking_type": "flight", "main_reason": "compensation_request",
            "user_message": COMPENSATION_MESSAGE}
    gate.review({"agent": "B", "action": "compensation", "params": {"booking_type": "flight", "booking_id": 7004},
                 "rule_id": "AT-NOPE", "facts_used": {}, "user_confirmed": True, "user_quote": "x"}, case)
    assert proposal_row()["confirmed_by_code"] is None
    assert reads.confirmation_words(None, None) == "not checked"


def old_database(path: Path) -> Path:
    """An atlas.db of before T22: no admin log, no confirmation columns, one old proposal."""
    con = sqlite3.connect(path)
    con.execute("DROP TABLE admin_actions")
    con.execute("ALTER TABLE proposals DROP COLUMN confirmed_by_code")
    con.execute("ALTER TABLE proposals DROP COLUMN confirmation_reason")
    con.execute("INSERT INTO proposals (id, agent, action, params, facts_used, user_confirmed, created_at)"
                " VALUES ('AP-0001', 'B', 'refund', '{}', '{}', 1, '2026-10-09')")
    con.commit()
    con.close()
    return path


def test_an_old_database_keeps_working(tmp_path):
    atlas_db.use_db(old_database(atlas_db.db_path()))
    row = writes.get_proposal("AP-0001")
    assert row["confirmed_by_code"] is None and row["confirmation_reason"] is None
    assert log_rows() == []
    assert "error" not in writes.set_proposal_confirmation("AP-0001", True, "refund request + quote found")
    assert writes.get_proposal("AP-0001")["confirmed_by_code"] == 1


def test_connect_adds_the_columns_once(tmp_path):
    old_database(atlas_db.db_path())
    for _ in range(2):
        atlas_db.connect().close()                      # the second time must not add them again
    assert writes.get_proposal("AP-0001")["user_confirmed"] is True


def test_confirmation_of_an_unknown_proposal_is_refused():
    assert "not found" in writes.set_proposal_confirmation("AP-9999", True, "x")["error"]


def proposal_lines(ticket_id: str) -> list[str]:
    steps = [s for turn in console.ticket_detail(ticket_id)["turns"] for s in turn["steps"]]
    return [console.describe_step(s)[2] for s in steps if console.kind_of(s) == "proposal"]


def test_the_console_shows_the_codes_decision_for_atlas():
    out = web_chat.send(5, "atlas", COMPENSATION_MESSAGE,
                        chat_fn=fake_agent("propose_compensation", "flight", 7004, "AT-FLT-03", confirmed=False))
    line = proposal_lines(out["ticket_id"])[0]
    assert "Confirmed by code: yes (compensation request + quote found)" in line
    assert "client confirmed" not in line


def test_the_console_says_no_with_the_reason():
    out = web_chat.send(5, "atlas", COMPENSATION_MESSAGE,
                        chat_fn=fake_agent("propose_compensation", "flight", 7004, "AT-FLT-03", quote="made up words"))
    assert "Confirmed by code: no (quote not in the message)" in proposal_lines(out["ticket_id"])[0]


def test_the_console_line_of_shopnova_is_unchanged():
    step = {"step": "proposal", "kind": "proposal", "data": {"trace_step": "proposal", "action": "refund", "amount": 59.9,
                                                              "order_id": 4512, "rule_id": "R-REF-03",
                                                              "user_confirmed": True, "facts_used": {"a": 1}}}
    assert console.describe_step(step) == ("📝", "Proposal: refund", '59.9 TND on order 4512 · rule R-REF-03 · '
                                           'client confirmed: True · facts {"a": 1}')


def test_an_atlas_proposal_without_a_decision_says_not_checked():
    step = {"step": "proposal", "kind": "proposal", "data": {"trace_step": "proposal", "action": "refund",
                                                              "booking_type": "flight", "booking_id": 7005,
                                                              "rule_id": "AT-FLT-01", "user_confirmed": True}}
    assert "Confirmed by code: not checked" in console.describe_step(step)[2]


# ---------- Admin dashboard ----------

def test_dashboard_numbers_on_all_data():
    d = atlas_app_reads.dashboard()
    hotel = {r["status"]: r["bookings"] for r in d["hotel_by_status"]}
    flight = {r["status"]: r["bookings"] for r in d["flight_by_status"]}
    assert sum(hotel.values()) == d["hotel_bookings"] == 2006 and sum(flight.values()) == d["flight_bookings"] == 2006
    assert d["hotel_cancellation_rate"] == round(100 * hotel["cancelled"] / 2006, 1)
    past = q("SELECT status, COUNT(*) FROM flights WHERE status != 'scheduled' GROUP BY status")
    counts = dict(past)
    assert d["flights"] == sum(counts.values())
    assert d["flight_delay_rate"] == round(100 * counts["delayed"] / d["flights"], 1)
    assert d["flight_cancellation_rate"] == round(100 * counts["cancelled"] / d["flights"], 1)
    assert d["start"] is None and d["today"] == "2026-10-09"


def test_dashboard_money_counts_refunds_and_compensation():
    assert atlas_app_reads.dashboard()["compensation_paid"] == {"count": 0, "tnd": 0.0}
    _, approval = pending_compensation()
    approvals.decide(approval["id"], "atlas_admin", True)
    assert atlas_app_reads.dashboard(7)["compensation_paid"] == {"count": 1, "tnd": 839.5}
    assert atlas_app_reads.dashboard()["refunds_paid"] == {"count": 0, "tnd": 0.0}


def test_dashboard_period_is_counted_from_the_simulation_clock():
    week, month, everything = (atlas_app_reads.dashboard(d) for d in (7, 30, None))
    assert week["start"] == "2026-10-03" and month["start"] == "2026-09-10"
    assert week["hotel_bookings"] <= month["hotel_bookings"] <= everything["hotel_bookings"]
    assert week["flights"] < month["flights"] < everything["flights"]


def test_upcoming_arrivals_and_departures_of_the_next_14_days():
    d = atlas_app_reads.dashboard()
    assert d["upcoming_until"] == "2026-10-23"
    arrivals = {a["id"] for a in d["upcoming_arrivals"]}
    assert 7011 in arrivals and 7012 not in arrivals                            # 7012 arrives on 10-25
    assert all("2026-10-09" <= a["arrival_date"] <= "2026-10-23" for a in d["upcoming_arrivals"])
    assert [b["id"] for b in d["upcoming_departures"]] == [7010]


def test_dashboard_page_period_radio():
    at = run(DASHBOARD, "atlas_admin")
    assert at.radio(key="dash_period").value == "All" and any("All dates" in c.value for c in at.caption)
    at.radio(key="dash_period").set_value("Last 7 days").run()
    assert not at.exception and any("From 2026-10-03" in c.value for c in at.caption)


# ---------- Records ----------

def test_records_has_the_six_read_only_tabs():
    at = run(RECORDS, "atlas_admin")
    assert [t.label for t in at.tabs] == ["Hotel bookings", "Flight bookings", "Users", "Refunds", "Compensation", "Admin log"]
    assert len(at.main.button) == 0     # no editing in T22
    assert len(at.dataframe) == 6


@pytest.mark.parametrize("read, total", [(atlas_app_reads.hotel_bookings_page, 2006),
                                         (atlas_app_reads.flight_bookings_page, 2006)])
def test_records_pages_have_50_rows(read, total):
    found = read()
    assert found["total"] == total and len(found["items"]) == 50 and found["pages"] == 41
    assert len(read(page=41)["items"]) == total - 40 * 50


def test_records_search():
    assert [r["id"] for r in atlas_app_reads.hotel_bookings_page("7011")["items"]] == [7011]
    assert {r["client"] for r in atlas_app_reads.flight_bookings_page("7004")["items"]} == {"Nizar Haddad"}
    assert [r["id"] for r in atlas_app_reads.users_page("hedi@example.com")["items"]] == [1]


def test_records_show_a_refund_a_compensation_and_the_log():
    _, approval = pending_compensation()
    approvals.decide(approval["id"], "atlas_admin", True)
    assert atlas_app_reads.compensations_page("7004")["items"][0]["amount"] == 839.5
    assert atlas_app_reads.refunds_page()["total"] == 0
    assert [r["action"] for r in atlas_app_reads.admin_log()] == ["approve_compensation"]


def test_the_admin_log_shows_the_last_50_newest_first():
    con = atlas_db.connect()
    con.executemany("INSERT INTO admin_actions (at, admin, action, target_table, target_id) VALUES ('t', 'a', ?, 't', '1')",
                    [(f"action {i}",) for i in range(60)])
    con.commit()
    con.close()
    rows = atlas_app_reads.admin_log(50)
    assert len(rows) == 50 and rows[0]["action"] == "action 59"


# ---------- nothing else of the app writes ----------

def test_the_app_reaches_callverse_only_through_the_two_doors():
    code = "".join(p.read_text(encoding="utf-8") for p in APP.rglob("*.py"))
    for forbidden in ("callverse.pipeline", "callverse.agents", "callverse.coordinator", "callverse.intake",
                      "atlas.writes", "import writes", "DELETE ", "UPDATE ", "INSERT "):
        assert forbidden not in code
    assert "web_chat.send(" in code and "approvals.decide(" in code


def test_the_new_reads_write_nothing():
    code = (ROOT / "callverse" / "data" / "atlas" / "atlas_app_reads.py").read_text(encoding="utf-8")
    assert not any(word in code for word in ("UPDATE ", "INSERT ", "DELETE ", ".commit("))
