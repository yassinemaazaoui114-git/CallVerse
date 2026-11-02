"""The three sign-in portals (ShopNova /shop/login, Atlas /atlas/login, Console /console/login) on the ONE
account store and the ONE session system. The portal is checked on the server, from the accounts file, after the
password and before a session exists. Checked here: every demo account signs in on its own portal and on no
other; a wrong portal looks exactly like a wrong password (same status, same body, no cookie, no session); a
company or role the browser adds is ignored; an unknown or missing portal is 400; a refused attempt leaves the
existing session alone; a successful one replaces the browser's previous session; the session route names the
account's portal; the data routes keep their own company checks.

Run: pytest webui/api/tests -q
"""

import pytest
from conftest import CSRF, PASSWORD, login, portal_for

from callverse.auth import accounts

from webui.api import settings

PORTALS = ("shop", "atlas", "console")
USERNAMES = [u for u, *_ in accounts.DEMO_ACCOUNTS]


def raw_login(client, body):
    return client.post("/api/auth/login", json=body, headers=CSRF)


@pytest.mark.parametrize("username", USERNAMES)
def test_each_account_signs_in_on_its_own_portal_only(client, username):
    own = portal_for(username)
    for portal in PORTALS:
        r = login(client, username, portal=portal)
        if portal == own:
            assert r.status_code == 200, (username, portal, r.text)
            assert r.json()["session"]["portal"] == own
            assert client.get("/api/auth/session").json()["session"]["portal"] == own
            client.post("/api/auth/logout", headers=CSRF)
        else:
            assert r.status_code == 401 and r.json()["error"] == "bad_login", (username, portal)
            assert settings.COOKIE_NAME not in r.headers.get("set-cookie", "")
            assert client.get("/api/auth/session").status_code == 401


def test_wrong_portal_looks_exactly_like_a_wrong_password(client):
    wrong_portal = login(client, "sara", portal="atlas")
    wrong_password = login(client, "hedi", "nope", portal="atlas")
    unknown_user = login(client, "nobody", portal="atlas")
    assert wrong_portal.status_code == wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_portal.json() == wrong_password.json() == unknown_user.json()
    assert "atlas" not in wrong_portal.json()["message"].lower() and "sara" not in wrong_portal.text


def test_browser_supplied_company_or_role_is_ignored(client):
    r = raw_login(client, {"username": "sara", "password": PASSWORD, "portal": "atlas", "company": "atlas", "role": "admin"})
    assert r.status_code == 401
    r = raw_login(client, {"username": "admin", "password": PASSWORD, "portal": "console", "role": "supervisor"})
    assert r.status_code == 401
    r = raw_login(client, {"username": "sara", "password": PASSWORD, "portal": "shop", "company": "atlas", "role": "admin"})
    assert r.status_code == 200
    assert r.json()["session"] == {"username": "sara", "name": "Sara Ben Ali", "role": "user", "company": "shopnova", "portal": "shop"}
    assert client.get("/api/atlas/bookings").status_code == 403          # still a ShopNova customer everywhere
    assert client.get("/api/admin/approvals").status_code == 403


def test_unknown_or_missing_portal_is_refused_before_the_password(client):
    for body in ({"username": "sara", "password": PASSWORD}, {"username": "sara", "password": PASSWORD, "portal": "admin"},
                 {"username": "sara", "password": PASSWORD, "portal": "SHOP"}):
        r = raw_login(client, body)
        assert r.status_code == 400 and r.json()["error"] == "bad_portal", body
    assert client.get("/api/auth/session").status_code == 401


def test_refused_attempt_keeps_the_session_and_a_new_login_replaces_it(client):
    assert login(client, "sara").status_code == 200
    first = client.cookies.get(settings.COOKIE_NAME)
    assert login(client, "sara", portal="atlas").status_code == 401           # wrong portal: nothing changes
    assert client.get("/api/auth/session").json()["session"]["username"] == "sara"
    assert login(client, "hedi", "nope").status_code == 401                   # wrong password: nothing changes
    assert client.get("/api/auth/session").json()["session"]["username"] == "sara"
    assert login(client, "hedi").status_code == 200                           # the Atlas page, an Atlas account
    assert client.get("/api/auth/session").json()["session"] == {"username": "hedi", "name": "Hedi Karoui", "role": "user",
                                                                "company": "atlas", "portal": "atlas"}
    client.cookies.set(settings.COOKIE_NAME, first)                           # sara's old token is dead on the server
    assert client.get("/api/auth/session").status_code == 401


def test_company_isolation_after_portal_login(client, shop_db, atlas_db_seeded):
    login(client, "hedi")
    assert client.get("/api/atlas/bookings").status_code == 200
    assert client.get("/api/shop/orders").status_code == 403
    assert client.get("/api/admin/manage/products").status_code == 403
    client.post("/api/auth/logout", headers=CSRF)
    login(client, "atlas_admin")
    assert client.get("/api/atlas/admin/approvals").status_code == 200
    assert client.get("/api/admin/approvals").status_code == 403
    assert client.get("/api/console/tickets").status_code == 403
    client.post("/api/auth/logout", headers=CSRF)
    login(client, "supervisor")
    assert client.get("/api/console/tickets").status_code == 200
    assert client.get("/api/shop/orders").status_code == 403 and client.get("/api/atlas/bookings").status_code == 403
