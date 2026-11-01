"""Step 1 tests of the web API: at least one test per route, the login rules, and the "no writes, no model" rules.

Run: pytest webui/api/tests -q
"""

import hashlib
import sys

from conftest import CSRF, login, make_ticket

from callverse.data import db as shopnova_db
from callverse.tickets import store

from webui.api import settings


# ---------- auth ----------

def test_login_sets_httponly_cookie_and_session_route_works(client):
    r = login(client, "supervisor")
    assert r.status_code == 200
    assert r.json()["session"] == {"username": "supervisor", "name": "CallVerse Supervisor",
                                   "role": "supervisor", "company": None}
    assert "password" not in r.text
    cookie = r.headers["set-cookie"]
    assert settings.COOKIE_NAME in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie.lower().replace("samesite=strict", "SameSite=strict")
    assert client.get("/api/auth/session").status_code == 200


def test_invalid_login_is_refused(client):
    assert login(client, "supervisor", "wrong").status_code == 401
    assert login(client, "nobody", "x").status_code == 401
    assert login(client, "supervisor", "").status_code == 401
    assert client.get("/api/auth/session").status_code == 401
    assert login(client, "supervisor", "wrong").json()["error"] == "bad_login"


def test_login_without_csrf_header_is_refused(client):
    r = client.post("/api/auth/login", json={"username": "supervisor", "password": "test-only"})
    assert r.status_code == 403 and r.json()["error"] == "csrf"


def test_logout_invalidates_the_session(supervisor):
    assert supervisor.get("/api/console/tickets").status_code == 200
    r = supervisor.post("/api/auth/logout", headers=CSRF)
    assert r.status_code == 200
    assert supervisor.get("/api/auth/session").status_code == 401
    assert supervisor.get("/api/console/tickets").status_code == 401


def test_old_cookie_is_dead_after_logout(client):
    """A copy of the cookie value is useless once the session was deleted on the server."""
    r = login(client, "supervisor")
    token = r.cookies[settings.COOKIE_NAME]
    client.post("/api/auth/logout", headers=CSRF)
    client.cookies.set(settings.COOKIE_NAME, token)
    assert client.get("/api/auth/session").status_code == 401


def test_expired_session_is_refused(client):
    from datetime import datetime, timedelta
    login(client, "supervisor")
    sessions = client.app.state.sessions
    for s in sessions._sessions.values():
        s["expires"] = datetime.now() - timedelta(seconds=1)
    assert client.get("/api/auth/session").status_code == 401


def test_no_accounts_file_gives_503(client):
    from callverse.auth import accounts
    accounts.use_accounts("C:/does/not/exist.yaml")
    r = login(client, "supervisor")
    assert r.status_code == 503 and r.json()["error"] == "no_accounts"


# ---------- company ----------

def test_company_needs_login_and_returns_the_profile(client):
    assert client.get("/api/company").status_code == 401
    login(client, "sara")   # any logged-in account may read the public profile
    r = client.get("/api/company")
    assert r.status_code == 200
    body = r.json()
    assert body["company"] == "shopnova" and body["profile"]["name"] == "ShopNova"
    atlas = client.get("/api/company", params={"company": "atlas"})
    assert atlas.status_code == 200 and atlas.json()["profile"]["name"]
    assert client.get("/api/company", params={"company": "nope"}).status_code == 404


# ---------- console: who may read ----------

def test_console_routes_reject_no_login_user_and_admin(client):
    for path in ("/api/console/tickets", "/api/console/tickets/filters", "/api/console/tickets/T-0001"):
        assert client.get(path).status_code == 401, path
    for username in ("sara", "admin", "atlas_admin", "hedi"):
        login(client, username)
        for path in ("/api/console/tickets", "/api/console/tickets/filters", "/api/console/tickets/T-0001"):
            r = client.get(path)
            assert r.status_code == 403 and r.json()["error"] == "forbidden", (username, path)
        client.post("/api/auth/logout", headers=CSRF)


# ---------- console: tickets ----------

def test_tickets_empty_database(supervisor):
    r = supervisor.get("/api/console/tickets")
    assert r.status_code == 200
    body = r.json()
    assert body["tickets"] == [] and body["has_tickets"] is False and body["no_tickets_message"]
    assert supervisor.get("/api/console/tickets/filters").json()["status"] == []


def test_tickets_list_and_filters(supervisor):
    make_ticket("shopnova", 1, "I want a refund")
    make_ticket("atlas", 2, "My flight was cancelled", outcome="escalate", status="Escalated",
                reason="rebooking", priority="high", agent="A")
    make_ticket("shopnova", 3, "Where is my order?", status="Open", reason="tracking", priority="low", agent="A")
    body = supervisor.get("/api/console/tickets").json()
    assert body["count"] == 3 and body["has_tickets"] is True
    assert [t["id"] for t in body["tickets"]] == ["T-0003", "T-0002", "T-0001"]   # newest first
    row = body["tickets"][2]
    assert set(row) == {"id", "company", "user", "reason", "priority", "status", "lead agent", "age"}
    assert row["user"] in ("user 1", "Sara Ben Ali (1)")   # the name if the company data exists, else the id

    assert supervisor.get("/api/console/tickets", params={"company": "atlas"}).json()["count"] == 1
    assert supervisor.get("/api/console/tickets", params={"status": "Open"}).json()["count"] == 1
    assert supervisor.get("/api/console/tickets", params={"priority": "low"}).json()["count"] == 1
    assert supervisor.get("/api/console/tickets", params={"agent": "A"}).json()["count"] == 2
    assert supervisor.get("/api/console/tickets", params={"agent": "A", "company": "shopnova"}).json()["count"] == 1
    assert supervisor.get("/api/console/tickets", params={"status": "Closed"}).json()["count"] == 0

    f = supervisor.get("/api/console/tickets/filters").json()
    assert f["status"] == ["Open", "Escalated", "Solved"]   # in the store's order
    assert f["priority"] == ["high", "low"] and f["agent"] == ["A", "B"]
    assert {"shopnova", "atlas"} <= set(f["company"])


def test_ticket_detail(supervisor):
    t = make_ticket("shopnova", 1, "I want a refund")
    r = supervisor.get(f"/api/console/tickets/{t['id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["ticket"]["id"] == t["id"] and body["ticket"]["status"] == "Solved"
    assert body["ticket"]["created_real"] and body["ticket"]["created_at"]   # computer time and simulation time
    assert len(body["turns"]) == 1
    turn = body["turns"][0]
    assert turn["message"]["text"] == "I want a refund"
    assert turn["replies"][0]["text"].startswith("Reply for outcome") and turn["replies"][0]["seconds"] == 3.2
    kinds = [s["kind"] for s in turn["steps"]]
    assert kinds == ["intake_ticket", "route", "llm_call", "tool_call", "tool_call", "proposal",
                     "coordinator_check", "coordinator_decision", "final_reply"]
    assert turn["decision"] == {"trace_step": "coordinator_decision", "outcome": "approve",
                                "reason": "test decision approve", "proposal_id": "P-0001", "order_id": 4505}
    assert [s["raw"]["data"]["tool"] for s in turn["tool_calls"]] == ["get_order", "search_policy"]
    assert len(turn["policy_searches"]) == 1
    assert turn["tokens"] == {"groq/openai/gpt-oss-120b": 1200} and turn["tokens_total"] == 1200
    step = turn["steps"][0]
    assert step["title"] == "Intake read the message" and "anger (0.90)" in step["detail"]
    assert step["actor"] == "intake" and step["actor_label"] == "Intake"
    assert set(step["raw"]) == {"id", "step", "agent", "at", "at_real", "data"}


def test_missing_ticket_is_404(supervisor):
    r = supervisor.get("/api/console/tickets/T-9999")
    assert r.status_code == 404 and r.json()["error"] == "not_found"


def test_unfamiliar_outcome_and_step_are_plain_text(supervisor):
    t = make_ticket("atlas", 2, "Proof attached", outcome="ask_proof", status="Waiting for user")
    mid = store.add_message(t["id"], "user", "second message")
    store.add_step(t["id"], mid, "brand_new_step", None, {"trace_step": "photo_proof_received", "ok": True})
    body = supervisor.get(f"/api/console/tickets/{t['id']}").json()
    assert body["turns"][0]["decision"]["outcome"] == "ask_proof"
    assert "ask_proof" in body["turns"][0]["steps"][7]["title"]
    new = body["turns"][1]["steps"][0]
    assert new["kind"] == "photo_proof_received" and new["title"] == "photo_proof_received"
    assert new["raw"]["data"] == {"trace_step": "photo_proof_received", "ok": True}


# ---------- no writes, no model ----------

def test_reads_write_nothing_and_load_no_model(supervisor, isolated_env):
    """The test fixture itself seeds the temp shopnova.db (the ticket store asks the simulation clock, which lives
    there); the API must then leave both files byte-for-byte as they are and never create the Atlas file."""
    make_ticket("shopnova", 1, "hello")
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()   # noqa: E731
    tickets_before = digest(store.db_path())
    company_before = digest(shopnova_db.db_path())
    for path in ("/api/console/tickets", "/api/console/tickets/filters", "/api/console/tickets/T-0001",
                 "/api/company", "/api/auth/session"):
        assert supervisor.get(path).status_code == 200, path
    assert digest(store.db_path()) == tickets_before          # tickets DB unchanged
    assert digest(shopnova_db.db_path()) == company_before    # company DB unchanged
    assert not (isolated_env / "atlas_never_created.db").exists()   # never created by a read
    # (callverse.llm itself is imported by conftest.py, to make llm.chat fail; the API never imports it.)
    for module in ("torch", "transformers", "sentence_transformers", "streamlit",
                   "callverse.pipeline", "callverse.agents", "callverse.channels.web_chat"):
        assert module not in sys.modules, module
