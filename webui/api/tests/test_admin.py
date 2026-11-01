"""Step 4 tests: the ShopNova admin approval queue over callverse.channels.approvals.decide, on temporary
databases, with a FAKE reply writer (no Ollama) and llm.chat made to fail (no model). Nothing real is paid.

Run: pytest webui/api/tests -q
"""

import threading
import time
from types import SimpleNamespace

import pytest
from conftest import CSRF, login, pending_approval

from callverse.tickets import store
from callverse.tools.shopnova_tools import get_order, get_refunds

from webui.api import admin

ROUTES = ("/api/admin/approvals", "/api/admin/approvals?status=decided", "/api/admin/approvals/1")


def fake_slm(role_key, messages, **kwargs):
    return SimpleNamespace(content="[TEST DATA] Dear customer, our finance team reviewed your refund of 378.00 TND "
                                   "for order 4515 and it is now decided.", tool_calls=None)


@pytest.fixture(autouse=True)
def admin_env(queue_mode):
    """Every admin test: queue mode, seeded shop DB, fake SLM; the real decide() and SLM are put back."""
    admin.use_slm_fn(fake_slm)
    yield
    admin.use_slm_fn(None)
    admin.use_decide_fn(None)


def decide(client, approval_id, approve, reason="", **extra):
    return client.post(f"/api/admin/approvals/{approval_id}/decide", json={"approve": approve, "reason": reason, **extra},
                       headers=CSRF)


# ---------- who may use the queue ----------

def test_roles_permission_and_company(client):
    for path in ROUTES:
        assert client.get(path).status_code == 401, path
    assert decide(client, 1, True).status_code == 401
    for username in ("sara", "hedi", "supervisor", "atlas_admin"):   # customers, Atlas accounts, the supervisor
        login(client, username)
        for path in ROUTES:
            r = client.get(path)
            assert r.status_code == 403 and r.json()["error"] == "admin_only", (username, path)
        assert decide(client, 1, True).status_code == 403, username
        client.post("/api/auth/logout", headers=CSRF)
    login(client, "admin")
    assert client.get("/api/admin/approvals").status_code == 200
    assert client.post("/api/admin/approvals/1/decide", json={"approve": True, "reason": ""}).status_code == 403   # CSRF


# ---------- the lists ----------

def test_lists_contain_only_shopnova_records_with_facts(client):
    a = pending_approval()
    atlas_ticket = store.create_ticket("atlas", 1)
    other = store.create_approval(atlas_ticket["id"], 7003, 900.0, "P-ATLAS", company="atlas", booking_type="flight")
    login(client, "admin")
    body = client.get("/api/admin/approvals").json()
    assert body["count"] == 1 and [x["id"] for x in body["approvals"]] == [a["id"]]
    row = body["approvals"][0]
    assert row["company"] == "shopnova" and row["amount"] == 378.0 and row["order_id"] == 4515
    assert row["facts"]["rule_id"] == "R-REF-03" and row["facts"]["user_name"] and row["facts"]["paid"] == 378.0
    assert row["facts"]["facts_used"]["days_late"] == 8 and row["proposal"]["decision"] is None
    assert client.get("/api/admin/approvals", params={"status": "decided"}).json()["count"] == 0
    assert client.get(f"/api/admin/approvals/{other['id']}").status_code == 404      # Atlas's: not found
    assert client.get("/api/admin/approvals/999").status_code == 404
    assert decide(client, other["id"], True).status_code == 404
    assert client.get("/api/admin/approvals", params={"status": "weird"}).status_code == 400


# ---------- decisions ----------

def test_approve_calls_decide_with_the_server_identity_and_pays_once(client):
    a = pending_approval()
    seen = []
    real = admin.decide_fn()

    def spy(approval_id, who, approve, reason, slm_chat_fn=None, company=None):
        seen.append({"approval_id": approval_id, "admin": who, "approve": approve, "reason": reason, "company": company})
        return real(approval_id, who, approve, reason, slm_chat_fn=slm_chat_fn, company=company)
    admin.use_decide_fn(spy)
    login(client, "admin")
    r = decide(client, a["id"], True, "looks fine", client_id="d1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert seen == [{"approval_id": a["id"], "admin": "admin", "approve": True, "reason": "looks fine",
                     "company": "shopnova"}]   # the identity and company from the account, not the browser
    assert body["outcome"] == "approve" and body["approval"]["status"] == "approved"
    assert body["approval"]["decided_by"] == "admin" and body["approval"]["decided_at"]
    assert body["refund"]["amount"] == 378.0 and body["ticket"]["status"] == "Solved"
    assert get_order(4515)["status"] == "refunded" and get_refunds(4515)["refunded_total"] == 378.0
    # the customer side: a new assistant reply and the unread notice (existing core behaviour)
    client.post("/api/auth/logout", headers=CSRF)
    login(client, "youssef")   # user 2 owns the ticket
    convo = client.get("/api/shop/chat").json()
    assert convo["unread"] and convo["unread"][0]["id"] == a["ticket_id"]
    assert convo["messages"][-1]["sender"] == "assistant" and "finance" in convo["messages"][-1]["text"].lower()
    # the decided list and the recorded state
    client.post("/api/auth/logout", headers=CSRF)
    login(client, "admin")
    decided = client.get("/api/admin/approvals", params={"status": "decided"}).json()
    assert decided["count"] == 1 and decided["approvals"][0]["reason"] == "looks fine"
    assert client.get("/api/admin/approvals").json()["count"] == 0


def test_refuse_needs_a_reason_and_pays_nothing(client):
    a = pending_approval()
    login(client, "admin")
    r = decide(client, a["id"], False, "   ")
    assert r.status_code == 400 and r.json()["error"] == "reason_required"
    assert store.get_approval(a["id"])["status"] == "pending"
    r = decide(client, a["id"], False, "duplicate claim")
    assert r.status_code == 200 and r.json()["outcome"] == "layer3_refused"
    assert r.json()["refund"] is None and get_refunds(4515)["refunds"] == []
    assert store.get_approval(a["id"])["reason"] == "duplicate claim"
    assert decide(client, a["id"], False, "x" * 1001).status_code == 400


def test_already_decided_and_concurrent_duplicate(client):
    a = pending_approval()
    login(client, "admin")
    assert decide(client, a["id"], False, "refused first").status_code == 200   # refuse: the order stays as it is
    r = decide(client, a["id"], True)
    assert r.status_code == 409 and r.json()["error"] == "already_decided" and "admin" in r.json()["message"]

    # concurrent: two requests on another pending approval at the same moment; decide() is held by a gate
    b = pending_approval(user_id=3, order_id=4515)   # a new proposal on the same (unchanged) order
    gate, calls = threading.Event(), []

    def slow(approval_id, who, approve, reason, slm_chat_fn=None, company=None):
        calls.append(approval_id)
        gate.wait(10)
        return {"approval": {**store.get_approval(approval_id), "status": "approved"}, "outcome": "approve",
                "ticket": {"id": b["ticket_id"], "status": "Solved"}, "refund": None, "reply_source": "fake"}
    admin.use_decide_fn(slow)
    results = []
    t = threading.Thread(target=lambda: results.append(decide(client, b["id"], True, client_id="c1").status_code))
    t.start()
    for _ in range(100):
        if calls:
            break
        time.sleep(0.02)
    second = decide(client, b["id"], True, client_id="c2")
    assert second.status_code == 409 and second.json()["error"] == "decision_in_progress"
    gate.set()
    t.join(10)
    assert results == [200] and len(calls) == 1


def test_recheck_refusal_writes_nothing_and_cannot_be_bypassed(client, monkeypatch):
    a = pending_approval()
    from callverse.channels import approvals as channel
    monkeypatch.setattr(channel, "recheck", lambda proposal: ({}, "rule R-REF-03 does not apply any more (test)"))
    login(client, "admin")
    r = decide(client, a["id"], True, "approve anyway", client_id="r1")
    assert r.status_code == 409 and r.json()["error"] == "recheck_refused"
    assert "does not apply" in r.json()["message"]
    assert store.get_approval(a["id"])["status"] == "pending" and get_refunds(4515)["refunds"] == []
    # asking again with the same client id runs the re-check again (an error is not a recorded decision)
    r2 = decide(client, a["id"], True, "approve anyway", client_id="r1")
    assert r2.status_code == 409 and r2.json()["error"] == "recheck_refused"
    # refusing is still possible
    assert decide(client, a["id"], False, "not valid any more").status_code == 200


def test_lost_response_recovery_does_not_repeat_the_decision(client):
    a = pending_approval()
    count = []
    real = admin.decide_fn()

    def counting(*args, **kwargs):
        count.append(1)
        return real(*args, **kwargs)
    admin.use_decide_fn(counting)
    login(client, "admin")
    first = decide(client, a["id"], True, "ok", client_id="lost-1")
    assert first.status_code == 200 and "recorded" not in first.json()
    # the browser never saw that answer and asks again with the same client id
    again = decide(client, a["id"], True, "ok", client_id="lost-1")
    assert again.status_code == 200 and again.json()["recorded"] is True
    assert again.json()["approval"]["status"] == "approved"
    assert len(count) == 1
    # without the id, the recorded state says who decided and when
    r = decide(client, a["id"], True, "ok")
    assert r.status_code == 409 and r.json()["error"] == "already_decided"
    state = client.get(f"/api/admin/approvals/{a['id']}").json()["approval"]
    assert state["status"] == "approved" and state["decided_by"] == "admin"


def test_exception_before_any_write_is_uncertain_with_evidence_and_the_guard_is_released(client):
    a = pending_approval()
    admin.use_decide_fn(lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    login(client, "admin")
    r = decide(client, a["id"], True, client_id="e1")
    assert r.status_code == 500 and r.json()["error"] == "decision_uncertain" and "RuntimeError" in r.json()["message"]
    assert r.json()["evidence"]["stage"] == "nothing_written"   # evidence, not a claim
    assert store.get_approval(a["id"])["status"] == "pending"
    admin.use_decide_fn(None)
    assert decide(client, a["id"], False, "after the failure").status_code == 200   # the guard was released


def test_unknown_outcome_passes_through(client):
    a = pending_approval()
    admin.use_decide_fn(lambda approval_id, *args, **kwargs: {
        "approval": store.get_approval(approval_id), "outcome": "approve_with_proof_pending",
        "ticket": store.get_ticket(a["ticket_id"]), "refund": None, "reply_source": "fake"})
    login(client, "admin")
    assert decide(client, a["id"], True).json()["outcome"] == "approve_with_proof_pending"


# ---------- correction pass: partial completion, in-flight state, bound retry identity ----------

def refund_rows(order_id=4515):
    return get_refunds(order_id)["refunds"]


def boom(message):
    def raise_it(*args, **kwargs):
        raise RuntimeError(message)
    return raise_it


def test_refund_committed_then_reply_generation_fails(client, monkeypatch):
    """The core wrote its transaction and closed the approval, then the reply writer raised: the API answers
    uncertain with the evidence (stage approval_closed_reply_missing); a retry never pays twice."""
    a = pending_approval()
    from callverse.channels import approvals as channel
    monkeypatch.setattr(channel.pipeline, "final_reply", boom("SLM down"))
    login(client, "admin")
    r = decide(client, a["id"], True, "ok", client_id="p1")
    assert r.status_code == 500 and r.json()["error"] == "decision_uncertain"
    ev = r.json()["evidence"]
    assert ev["stage"] == "approval_closed_notification_unconfirmed" and ev["notification"] == "unconfirmed"
    assert ev["refund"]["amount"] == 378.0 and ev["proposal_decision"] == "approve" and ev["approval"]["status"] == "approved"
    assert ev["ticket_status"] == "Waiting for finance"   # the customer was not told
    assert len(refund_rows()) == 1
    # recovery: the recorded state says so; the same request again is NOT a replay (nothing recorded) and the
    # core refuses a second run; no second payment
    state = client.get(f"/api/admin/approvals/{a['id']}").json()
    assert state["evidence"]["stage"] == "approval_closed_notification_unconfirmed" and state["in_flight"] is None
    again = decide(client, a["id"], True, "ok", client_id="p1")
    assert again.status_code == 409 and again.json()["error"] == "already_decided"
    assert len(refund_rows()) == 1


def test_company_transaction_committed_then_approval_update_fails(client, monkeypatch):
    """The core's transaction committed (proposal decided, refund row) and then close_approval raised: the
    approval row is still pending but money moved. The API must say PARTIAL, and a retry must not pay again."""
    a = pending_approval()
    from callverse.channels import approvals as channel
    monkeypatch.setattr(channel.store, "close_approval", boom("disk full"))
    login(client, "admin")
    r = decide(client, a["id"], True, "ok", client_id="p2")
    assert r.status_code == 500 and r.json()["error"] == "decision_uncertain"
    ev = r.json()["evidence"]
    assert ev["stage"] == "company_written_approval_pending"
    assert ev["approval"]["status"] == "pending" and ev["refund"]["amount"] == 378.0 and ev["proposal_decision"] == "approve"
    assert "PARTIAL" in ev["stage_words"]
    monkeypatch.undo()
    # the approval row still says pending: a naive retry is exactly the danger; the core refuses the proposal
    again = decide(client, a["id"], True, "ok", client_id="p2")
    assert again.status_code == 409 and again.json()["error"] == "already_decided"   # "proposal ... already decided"
    assert len(refund_rows()) == 1
    assert client.get(f"/api/admin/approvals/{a['id']}").json()["evidence"]["stage"] == "company_written_approval_pending"


def test_lost_response_while_the_original_request_is_still_running(client):
    a = pending_approval()
    gate, calls = threading.Event(), []

    def slow(approval_id, who, approve, reason, slm_chat_fn=None, company=None):
        calls.append(1)
        gate.wait(10)
        return {"approval": {**store.get_approval(approval_id), "status": "approved"}, "outcome": "approve",
                "ticket": {"id": a["ticket_id"], "status": "Solved"}, "refund": None, "reply_source": "fake"}
    admin.use_decide_fn(slow)
    login(client, "admin")
    results = []
    t = threading.Thread(target=lambda: results.append(decide(client, a["id"], True, "ok", client_id="run-1").status_code))
    t.start()
    for _ in range(100):
        if calls:
            break
        time.sleep(0.02)
    # the browser lost the answer and asks for the recorded state: the decision is IN FLIGHT, not "nothing"
    state = client.get(f"/api/admin/approvals/{a['id']}").json()
    assert state["in_flight"]["client_id"] == "run-1" and state["in_flight"]["approve"] is True
    assert state["evidence"]["stage"] == "nothing_written"   # nothing yet, but a run is going on
    # the same request again while it runs is NOT replayed and NOT run twice
    again = decide(client, a["id"], True, "ok", client_id="run-1")
    assert again.status_code == 409 and again.json()["error"] == "decision_in_progress"
    gate.set()
    t.join(10)
    assert results == [200] and len(calls) == 1
    assert client.get(f"/api/admin/approvals/{a['id']}").json()["in_flight"] is None


def test_same_client_id_with_changed_choice_or_reason_is_rejected(client):
    a = pending_approval()
    login(client, "admin")
    first = decide(client, a["id"], False, "duplicate claim", client_id="same-1")
    assert first.status_code == 200
    for other in ({"approve": True, "reason": "duplicate claim"}, {"approve": False, "reason": "other words"}):
        r = client.post(f"/api/admin/approvals/{a['id']}/decide", json={"client_id": "same-1", **other}, headers=CSRF)
        assert r.status_code == 409 and r.json()["error"] == "client_id_reused", other
    same = decide(client, a["id"], False, "  duplicate claim ", client_id="same-1")   # normalised reason: identical
    assert same.status_code == 200 and same.json()["recorded"] is True


def test_response_preparation_failure_releases_the_guard(client, monkeypatch):
    a = pending_approval()
    monkeypatch.setattr(admin, "result_view", boom("ticket"))
    login(client, "admin")
    r = decide(client, a["id"], True, "ok", client_id="prep-1")
    assert r.status_code == 500 and r.json()["error"] == "decision_uncertain"
    assert r.json()["evidence"]["stage"] == "complete"   # the decision itself completed
    monkeypatch.undo()
    state = client.get(f"/api/admin/approvals/{a['id']}").json()
    assert state["in_flight"] is None                      # the guard was released
    again = decide(client, a["id"], True, "ok", client_id="prep-1")
    assert again.status_code == 409 and again.json()["error"] == "already_decided"   # not decision_in_progress
    assert len(refund_rows()) == 1


# ---------- correction: the customer notification is judged by the approval's own decision step ----------

def evidence_of(client, approval_id):
    return client.get(f"/api/admin/approvals/{approval_id}").json()["evidence"]


def test_reading_the_reply_or_reopening_the_ticket_keeps_the_decision_complete(client):
    a = pending_approval()
    login(client, "admin")
    assert decide(client, a["id"], True, "ok").status_code == 200
    ev = evidence_of(client, a["id"])
    assert ev["stage"] == "complete" and ev["notification"] == "confirmed" and ev["decision_step_at"]
    # the customer reads the reply (the chat marks it read) ...
    store.set_unread(a["ticket_id"], False)
    assert evidence_of(client, a["id"])["stage"] == "complete"
    # ... and later writes again: the ticket is reopened and a new reply arrives
    store.update_ticket(a["ticket_id"], status="Open")
    store.add_message(a["ticket_id"], "user", "thanks, one more question")
    store.add_message(a["ticket_id"], "assistant", "Of course.")
    assert evidence_of(client, a["id"])["stage"] == "complete"


def test_an_unrelated_assistant_message_does_not_prove_the_notification(client):
    """The approval row was closed but decide() never reached its end (no decision step): a later assistant
    message on the ticket (another conversation turn) must not pass for this approval's reply."""
    a = pending_approval()
    from callverse.data import writes
    assert "error" not in writes.admin_decide_refund("admin", a["proposal_id"], True, "", approval_id=a["id"])
    assert store.close_approval(a["id"], "approved", "admin", None)
    store.add_message(a["ticket_id"], "assistant", "Hello again, how can I help?")   # unrelated
    store.update_ticket(a["ticket_id"], status="Solved")
    store.set_unread(a["ticket_id"], True)
    login(client, "admin")
    ev = evidence_of(client, a["id"])
    assert ev["stage"] == "approval_closed_notification_unconfirmed" and ev["notification"] == "unconfirmed"
    assert ev["last_message"]["sender"] == "assistant"   # it is there, but it is not evidence for this approval
    assert "not confirmed" in ev["stage_words"] and "missing" not in ev["stage_words"]
    # and nothing here replays the decision
    again = decide(client, a["id"], True, "ok", client_id="x")
    assert again.status_code == 409 and again.json()["error"] == "already_decided"
    assert len(refund_rows()) == 1
