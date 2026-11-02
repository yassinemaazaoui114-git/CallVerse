"""Step 5 tests: Atlas Travel customer and admin routes, on a seeded TEMPORARY atlas.db, with a fake channel / fake
reply writer. No model, no real money. Isolation from ShopNova is checked with the accounts that share a numeric
user id (hedi = Atlas user 1, sara = ShopNova user 1).

Run: pytest webui/api/tests -q
"""

import json
import threading
from types import SimpleNamespace

import pytest
from conftest import CSRF, login, pending_approval, pending_atlas_refund, pending_compensation

from callverse.data.atlas import reads as atlas_core_reads
from callverse.tickets import store

from webui.api import admin, chat

CUSTOMER_ROUTES = ("/api/atlas/bookings", "/api/atlas/bookings/flight/7005", "/api/atlas/chat", "/api/atlas/chat/job")
ADMIN_ROUTES = ("/api/atlas/admin/approvals", "/api/atlas/admin/approvals?status=decided",
                "/api/atlas/admin/approvals/1", "/api/atlas/admin/records/hotels")


def fake_slm(role_key, messages, **kwargs):
    return SimpleNamespace(content="[TEST DATA] Dear customer, our finance team reviewed your request for flight "
                                   "7004 and it is now decided.", tool_calls=None)


@pytest.fixture(autouse=True)
def atlas_env(atlas_db_seeded):
    admin.use_slm_fn(fake_slm)
    yield
    admin.use_slm_fn(None)
    admin.use_decide_fn(None)
    chat.use_send_fn(None)


def decide(client, approval_id, approve, reason="", **extra):
    return client.post(f"/api/atlas/admin/approvals/{approval_id}/decide",
                       json={"approve": approve, "reason": reason, **extra}, headers=CSRF)


# ---------- who may use what (cross-company isolation) ----------

def test_roles_and_companies_on_atlas_routes(client):
    for path in CUSTOMER_ROUTES + ADMIN_ROUTES:
        assert client.get(path).status_code == 401, path
    # ShopNova customer with the SAME numeric user id as hedi, the ShopNova admin, the supervisor
    for username, routes, code in (("sara", CUSTOMER_ROUTES, "customer_only"), ("admin", ADMIN_ROUTES, "admin_only"),
                                   ("supervisor", CUSTOMER_ROUTES + ADMIN_ROUTES, None),
                                   ("atlas_admin", CUSTOMER_ROUTES, "customer_only"), ("hedi", ADMIN_ROUTES, "admin_only")):
        login(client, username)
        for path in routes:
            r = client.get(path)
            assert r.status_code == 403, (username, path)
            if code:
                assert r.json()["error"] == code and "Atlas" in r.json()["message"]
        client.post("/api/auth/logout", headers=CSRF)
    # and the other way round: Atlas accounts on ShopNova's routes
    for username, routes in (("hedi", ("/api/shop/orders", "/api/shop/chat")), ("atlas_admin", ("/api/admin/approvals",))):
        login(client, username)
        for path in routes:
            assert client.get(path).status_code == 403, (username, path)
        client.post("/api/auth/logout", headers=CSRF)


# ---------- bookings ----------

def test_customer_sees_only_own_bookings_with_the_right_type(client):
    login(client, "hedi")   # Atlas user 1
    body = client.get("/api/atlas/bookings").json()
    assert [b["id"] for b in body["hotels"]] == [7001, 7011] and [b["id"] for b in body["flights"]] == [7005]
    assert body["count"] == 3 and body["sim_today"] == "2026-10-09"
    flight = body["flights"][0]
    assert flight["route"] and flight["situation"] and "refunds" in flight and "compensations" in flight
    # detail: the right type, with the agents' facts (hidden fields removed) and the money reads
    r = client.get("/api/atlas/bookings/flight/7005")
    assert r.status_code == 200
    d = r.json()
    assert d["kind"] == "flight" and d["booking"]["id"] == 7005 and d["facts"]["flight_status"]
    assert "payment_method" not in d["facts"] and "source" not in d["facts"]   # HIDDEN fields never reach the browser
    assert d["refunds"]["booking_id"] == 7005 and "compensations" in d["compensations"]
    h = client.get("/api/atlas/bookings/hotel/7001").json()
    assert h["kind"] == "hotel" and h["booking"]["hotel"] and h["facts"]["nights"]
    # wrong type, someone else's, missing, unknown kind: the same 404
    for path in ("/api/atlas/bookings/hotel/7005", "/api/atlas/bookings/flight/7004", "/api/atlas/bookings/flight/9999",
                 "/api/atlas/bookings/train/7005"):
        r = client.get(path)
        assert r.status_code == 404 and r.json()["error"] == "not_found", path


def test_same_numeric_id_at_shopnova_does_not_open_atlas_bookings(client):
    login(client, "sara")   # ShopNova user 1, like hedi
    assert client.get("/api/atlas/bookings/hotel/7001").status_code == 403
    login(client, "hedi")
    assert client.get("/api/shop/orders/4505").status_code == 403


# ---------- chat: booking context and isolation ----------

def make_fake(calls):
    def fake_send(user_id, company, text, ticket_id=None, on_step=None, about_order=None, **kwargs):
        calls.append({"user_id": user_id, "company": company, "text": text, "ticket_id": ticket_id, "about": about_order})
        t = store.ticket_for_message(company, user_id, ticket_id)
        store.add_message(t["id"], "user", text)
        on_step("Checking your booking…")
        store.add_message(t["id"], "assistant", "Fake reply.", seconds=1.0)
        store.update_ticket(t["id"], status="Solved")
        return {"ticket_id": t["id"], "status": "Solved", "reply": "Fake reply.", "outcome": "info",
                "reply_source": "fake", "steps": 1, "seconds": 1.0}
    return fake_send


def test_atlas_chat_passes_the_booking_context_and_stays_apart_from_shopnova(client):
    calls = []
    chat.use_send_fn(make_fake(calls))
    login(client, "hedi")
    r = client.post("/api/atlas/chat/send", json={"text": "Is it late?", "about_booking": 7005, "client_id": "a1"}, headers=CSRF)
    assert r.status_code == 200 and "event: done" in r.text
    assert calls[-1] == {"user_id": 1, "company": "atlas", "text": "Is it late?", "ticket_id": None, "about": 7005}
    # a booking that is not his (nizar's 7004) or nobody's: refused before the channel
    for booking in (7004, 9999):
        r = client.post("/api/atlas/chat/send", json={"text": "x", "about_booking": booking, "client_id": f"b{booking}"}, headers=CSRF)
        assert r.status_code == 404 and r.json()["error"] == "not_found"
    assert len(calls) == 1
    convo = client.get("/api/atlas/chat").json()
    assert convo["company"] == "atlas" and convo["ticket"]["company"] == "atlas" and convo["job"]["client_id"] == "a1"
    atlas_ticket = convo["ticket"]["id"]
    # the ShopNova customer with the same numeric id: no job, no ticket, no read
    client.post("/api/auth/logout", headers=CSRF)
    login(client, "sara")
    shop = client.get("/api/shop/chat").json()
    assert shop["job"] is None and shop["ticket"] is None
    assert client.get("/api/shop/chat", params={"ticket": atlas_ticket}).status_code == 404
    assert client.post(f"/api/shop/chat/tickets/{atlas_ticket}/read", headers=CSRF).status_code == 404
    # the same client_id at ShopNova is a NEW job (ids are per company)
    r = client.post("/api/shop/chat/send", json={"text": "hello", "client_id": "a1"}, headers=CSRF)
    assert r.status_code == 200 and calls[-1]["company"] == "shopnova" and len(calls) == 2


# ---------- admin: the queue, compensations and refunds ----------

def test_atlas_queue_lists_only_atlas_cases_with_atlas_facts(client):
    a = pending_compensation()
    s = pending_approval()   # a ShopNova case
    login(client, "atlas_admin")
    body = client.get("/api/atlas/admin/approvals").json()
    assert body["company"] == "atlas" and [x["id"] for x in body["approvals"]] == [a["id"]]
    row = body["approvals"][0]
    assert row["action"] == "compensation" and row["booking_type"] == "flight" and row["order_id"] == 7004
    assert row["amount"] == 839.5 and row["facts"]["rule_id"] == "AT-FLT-03" and row["facts"]["user_name"]
    assert row["facts"]["confirmation"].startswith("yes")             # the code's confirmation decision, in words
    assert row["proposal"]["confirmed_by_code"] == 1 and row["proposal"]["params"]["booking_type"] == "flight"
    assert client.get(f"/api/atlas/admin/approvals/{s['id']}").status_code == 404   # ShopNova's: not found here
    assert decide(client, s["id"], True).status_code == 404
    # and the ShopNova admin does not see the Atlas case
    client.post("/api/auth/logout", headers=CSRF)
    login(client, "admin")
    assert [x["id"] for x in client.get("/api/admin/approvals").json()["approvals"]] == [s["id"]]
    assert client.get(f"/api/admin/approvals/{a['id']}").status_code == 404


def test_approve_a_compensation_writes_the_compensation_not_a_refund(client):
    a = pending_compensation()
    seen = []
    real = admin.decide_fn()

    def spy(approval_id, who, approve, reason, slm_chat_fn=None, company=None):
        seen.append((approval_id, who, company))
        return real(approval_id, who, approve, reason, slm_chat_fn=slm_chat_fn, company=company)
    admin.use_decide_fn(spy)
    login(client, "atlas_admin")
    r = decide(client, a["id"], True, "delay confirmed", client_id="c1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert seen == [(a["id"], "atlas_admin", "atlas")]
    assert body["outcome"] == "approve" and body["approval"]["status"] == "approved"
    assert body["refund"] is None and body["compensation"]["amount"] == 839.5    # a compensation, not a refund
    assert [c["amount"] for c in atlas_core_reads.get_compensations("flight", 7004)["compensations"]] == [839.5]
    assert atlas_core_reads.get_refunds("flight", 7004)["refunds"] == []
    ev = client.get(f"/api/atlas/admin/approvals/{a['id']}").json()["evidence"]
    assert ev["stage"] == "complete" and ev["action"] == "compensation" and ev["money"]["amount"] == 839.5
    # the customer (nizar) got the reply and the notice
    client.post("/api/auth/logout", headers=CSRF)
    login(client, "nizar")
    convo = client.get("/api/atlas/chat").json()
    assert convo["unread"][0]["id"] == a["ticket_id"] and convo["messages"][-1]["sender"] == "assistant"
    # recovery with the same request id: recorded, no second payment
    client.post("/api/auth/logout", headers=CSRF)
    login(client, "atlas_admin")
    again = decide(client, a["id"], True, "delay confirmed", client_id="c1")
    assert again.status_code == 200 and again.json()["recorded"] is True
    assert len(atlas_core_reads.get_compensations("flight", 7004)["compensations"]) == 1
    assert client.get("/api/atlas/admin/approvals", params={"status": "decided"}).json()["count"] == 1


def test_refuse_needs_a_reason_and_pays_nothing(client):
    a = pending_compensation()
    login(client, "atlas_admin")
    assert decide(client, a["id"], False, " ").status_code == 400
    r = decide(client, a["id"], False, "already compensated by the airline")
    assert r.status_code == 200 and r.json()["outcome"] == "layer3_refused" and r.json()["compensation"] is None
    assert atlas_core_reads.get_compensations("flight", 7004)["compensations"] == []
    assert store.get_approval(a["id"])["reason"] == "already compensated by the airline"


def test_duplicate_and_uncertain_atlas_decisions(client, monkeypatch):
    a = pending_compensation()
    login(client, "atlas_admin")
    # same client id with other content
    assert decide(client, a["id"], False, "x", client_id="d").status_code == 200
    r = decide(client, a["id"], True, "x", client_id="d")
    assert r.status_code == 409 and r.json()["error"] == "client_id_reused"
    # uncertain: the company transaction committed, then the approval record failed -> money is a compensation
    b = pending_compensation()   # a new proposal on 7004: the refusal above paid nothing, so it still qualifies
    from callverse.channels import approvals as channel

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")
    monkeypatch.setattr(channel.store, "close_approval", boom)
    r = decide(client, b["id"], True, "ok", client_id="u")
    assert r.status_code == 500 and r.json()["error"] == "decision_uncertain"
    ev = r.json()["evidence"]
    assert ev["stage"] == "company_written_approval_pending" and ev["action"] == "compensation"
    assert ev["money"]["booking_id"] == 7004 and ev["refund"] == ev["money"]
    monkeypatch.undo()
    again = decide(client, b["id"], True, "ok", client_id="u")
    assert again.status_code == 409 and again.json()["error"] == "already_decided"   # the core refuses: paid once
    assert len(atlas_core_reads.get_compensations("flight", 7004)["compensations"]) == 1


def test_atlas_and_shopnova_decisions_do_not_share_guards(client):
    """The in-flight guard and the recorded results are keyed by company: approval ids may coincide."""
    a = pending_compensation()        # Atlas approval 1
    s = pending_approval()            # ShopNova approval 2
    assert a["id"] != s["id"]
    gate, calls = threading.Event(), []

    def slow(approval_id, who, approve, reason, slm_chat_fn=None, company=None):
        calls.append(company)
        gate.wait(10)
        return {"approval": {**store.get_approval(approval_id), "status": "approved"}, "outcome": "approve",
                "ticket": {"id": "T", "status": "Solved"}, "refund": None, "compensation": None, "reply_source": "fake"}
    admin.use_decide_fn(slow)
    login(client, "atlas_admin")
    results = []
    t = threading.Thread(target=lambda: results.append(decide(client, a["id"], True, "ok", client_id="k").status_code))
    t.start()
    import time
    for _ in range(100):
        if calls:
            break
        time.sleep(0.02)
    from fastapi.testclient import TestClient
    with TestClient(client.app) as other:
        login(other, "admin")
        state = other.get(f"/api/admin/approvals/{s['id']}").json()
        assert state["in_flight"] is None   # the Atlas decision in flight is not ShopNova's
    gate.set()
    t.join(10)
    assert results == [200]


# ---------- records ----------

def test_records_pages_and_log(client):
    login(client, "atlas_admin")
    for table in ("hotels", "flights", "users", "refunds", "compensations"):
        r = client.get(f"/api/atlas/admin/records/{table}")
        assert r.status_code == 200 and r.json()["table"] == table and r.json()["page"] == 1, table
        assert r.json()["total"] >= 0 and r.json()["page_size"] > 0
    found = client.get("/api/atlas/admin/records/hotels", params={"search": "7001"}).json()
    assert found["total"] >= 1 and any(row["id"] == 7001 for row in found["items"])
    log = client.get("/api/atlas/admin/records/log").json()
    assert log["table"] == "log" and isinstance(log["items"], list)
    assert client.get("/api/atlas/admin/records/secrets").status_code == 404
    client.post("/api/auth/logout", headers=CSRF)
    login(client, "admin")   # the ShopNova admin: not this company
    assert client.get("/api/atlas/admin/records/hotels").status_code == 403


def test_missing_atlas_database_gives_503_and_creates_nothing(client, isolated_env):
    from callverse.data.atlas import db as atlas_db
    missing = isolated_env / "atlas_missing.db"
    atlas_db.use_db(missing)
    login(client, "hedi")
    for path in ("/api/atlas/bookings", "/api/atlas/bookings/flight/7005", "/api/atlas/chat"):
        r = client.get(path)
        assert r.status_code == 503 and r.json()["error"] == "setup_required" and "atlas.db" in r.json()["message"], path
    assert not missing.exists()
    client.post("/api/auth/logout", headers=CSRF)
    login(client, "atlas_admin")
    assert client.get("/api/atlas/admin/approvals").status_code == 503
    assert not missing.exists()


# ---------- admin: an Atlas REFUND above the limit (not a compensation) ----------

def test_atlas_refund_queue_and_approve_writes_a_refund_not_a_compensation(client):
    a = pending_atlas_refund()
    login(client, "atlas_admin")
    row = client.get("/api/atlas/admin/approvals").json()["approvals"][0]
    assert row["id"] == a["id"] and row["action"] == "refund" and row["booking_type"] == "flight"
    assert row["order_id"] == 7006 and row["amount"] == 1900.0 and row["facts"]["rule_id"] == "AT-FLT-04"
    r = decide(client, a["id"], True, "delay confirmed", client_id="rf1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == "approve" and body["approval"]["status"] == "approved"
    assert body["refund"]["amount"] == 1900.0 and body["compensation"] is None       # a refund, not a compensation
    assert [x["amount"] for x in atlas_core_reads.get_refunds("flight", 7006)["refunds"]] == [1900.0]
    assert atlas_core_reads.get_compensations("flight", 7006)["compensations"] == []
    ev = client.get(f"/api/atlas/admin/approvals/{a['id']}").json()["evidence"]
    assert ev["stage"] == "complete" and ev["action"] == "refund" and ev["money"]["amount"] == 1900.0
    # the customer (sonia) got the reply and the notice
    client.post("/api/auth/logout", headers=CSRF)
    login(client, "sonia")
    convo = client.get("/api/atlas/chat").json()
    assert convo["unread"][0]["id"] == a["ticket_id"] and convo["messages"][-1]["sender"] == "assistant"


def test_atlas_refund_refuse_duplicate_and_uncertain(client, monkeypatch):
    a = pending_atlas_refund()
    login(client, "atlas_admin")
    assert decide(client, a["id"], False, "").status_code == 400                       # a reason is required
    r = decide(client, a["id"], False, "airline already refunded", client_id="rr1")
    assert r.status_code == 200 and r.json()["outcome"] == "layer3_refused" and r.json()["refund"] is None
    assert atlas_core_reads.get_refunds("flight", 7006)["refunds"] == []
    # the same request id again -> recorded; another choice with that id -> refused; a new decision -> already decided
    again = decide(client, a["id"], False, "airline already refunded", client_id="rr1")
    assert again.status_code == 200 and again.json()["recorded"] is True
    assert decide(client, a["id"], True, "airline already refunded", client_id="rr1").json()["error"] == "client_id_reused"
    assert decide(client, a["id"], True, "x").json()["error"] == "already_decided"
    # uncertain: a second refund case (the refusal paid nothing, so 7006 still qualifies); the company
    # transaction commits, then the approval record fails -> partial, the money row is the REFUND
    b = pending_atlas_refund()
    from callverse.channels import approvals as channel

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")
    monkeypatch.setattr(channel.store, "close_approval", boom)
    r = decide(client, b["id"], True, "ok", client_id="ru1")
    assert r.status_code == 500 and r.json()["error"] == "decision_uncertain"
    ev = r.json()["evidence"]
    assert ev["stage"] == "company_written_approval_pending" and ev["action"] == "refund"
    assert ev["money"]["amount"] == 1900.0 and ev["money"]["booking_id"] == 7006
    monkeypatch.undo()
    retry = decide(client, b["id"], True, "ok", client_id="ru1")
    assert retry.status_code == 409 and retry.json()["error"] == "already_decided"    # the core refuses: paid once
    assert len(atlas_core_reads.get_refunds("flight", 7006)["refunds"]) == 1


def test_atlas_chat_passes_a_photo_to_the_channel(client):
    """T35: the shared register_chat gives Atlas the same photo field and checks."""
    import base64
    seen = []
    inner = make_fake([])

    def fake_send(user_id, company, text, ticket_id=None, on_step=None, about_order=None, image=None, **kwargs):
        seen.append((company, image))
        return inner(user_id, company, text, ticket_id=ticket_id, on_step=on_step, about_order=about_order)

    chat.use_send_fn(fake_send)
    login(client, "hedi")
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
    r = client.post("/api/atlas/chat/send", json={"text": "The room was dirty, see photo.", "client_id": "ph1",
                                                   "image_b64": base64.b64encode(png).decode()}, headers=CSRF)
    assert r.status_code == 200 and "event: done" in r.text
    assert seen == [("atlas", png)]
    r = client.post("/api/atlas/chat/send", json={"text": "x", "client_id": "ph2",
                                                   "image_b64": base64.b64encode(b"GIF89a....").decode()}, headers=CSRF)
    assert r.status_code == 400 and r.json()["error"] == "photo_type"
    assert len(seen) == 1
