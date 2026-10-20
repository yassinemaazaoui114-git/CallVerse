"""Local platform server: read endpoints, agent tool calls through the registry, token-protected writes.

All requests go through FastAPI's TestClient (no real network). conftest.py points the platform at a
temporary database, so these tests never touch callverse/data/shopnova.db.
"""

import json
import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from callverse import trace
from callverse.data import db
from callverse.server.app import TOKEN_ENV, app

client = TestClient(app)
TOKEN = "test-token-123"


def _refund_count() -> int:
    with closing(sqlite3.connect(db.db_path())) as con:
        return con.execute("SELECT COUNT(*) FROM refunds").fetchone()[0]


@pytest.fixture
def token_on(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    return {"X-Coordinator-Token": TOKEN}


# --- read endpoints -------------------------------------------------------

def test_tracking_4512():
    r = client.get("/orders/4512/tracking")
    assert r.status_code == 200 and r.json()["days_late"] == 6


def test_orders_filters_and_summary():
    assert len(client.get("/orders", params={"scripted": 1}).json()) == 11
    assert len(client.get("/orders", params={"limit": 500}).json()) == 131
    assert len(client.get("/orders").json()) == 50                     # default limit
    stuck = client.get("/orders", params={"status": "stuck_at_depot", "limit": 500}).json()
    assert stuck and all(o["status"] == "stuck_at_depot" for o in stuck)
    s = client.get("/summary").json()
    assert s["orders_total"] == 131 and s["scripted_orders"]["count"] == 11


def test_other_reads_return_what_the_functions_return():
    from callverse.tools.shopnova_tools import get_order, get_refunds
    assert client.get("/orders/4506").json() == get_order(4506)
    assert client.get("/orders/4506/refunds").json() == get_refunds(4506)
    assert client.get("/users/1").json()["name"].startswith("Sara")
    assert client.get("/company").json()["name"] == "ShopNova"
    assert len(client.get("/policies").json()) == 8
    assert client.get("/policies/R-REF-05").json()["condition"] == "amount <= paid - refunded_total"


def test_unknown_things_are_404():
    assert client.get("/orders/9999").status_code == 404
    assert client.get("/orders/9999/tracking").status_code == 404
    assert client.get("/users/999").status_code == 404
    assert client.get("/policies/R-NOPE").status_code == 404


def test_dashboard_is_html():
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "ShopNova" in r.text
    assert 'method="post"' not in r.text.lower()  # read-only page: no write forms


# --- agent tool calls -------------------------------------------------------

def test_tool_call_allowed_for_agent_a():
    r = client.post("/tools/get_tracking", json={"agent": "A", "args": {"order_id": 4512}})
    assert r.status_code == 200 and r.json()["days_late"] == 6


def test_tool_call_outside_allow_list_is_403_and_traced():
    r = client.post("/tools/get_refunds", json={"agent": "A", "args": {"order_id": 4512}})
    assert r.status_code == 403 and "not allowed" in r.json()["error"]
    lines = [json.loads(x) for x in trace.current_path().read_text(encoding="utf-8").splitlines()]
    assert any(x["step"] == "tool_refused" and x["data"]["tool"] == "get_refunds" for x in lines)
    last = lines[-1]
    assert last["actor"] == "server" and last["data"]["agent"] == "A" and last["data"]["status"] == 403


def test_write_functions_are_not_tools():
    for name in ("create_refund", "set_order_status", "layer3_decide"):
        assert client.post(f"/tools/{name}", json={"agent": "A", "args": {}}).status_code == 403


# --- coordinator writes -------------------------------------------------------

REFUND = {"order_id": 4512, "amount": 59.90, "rule_id": "R-REF-03", "proposal_id": "P-0001"}
PROPOSAL = {"agent": "B", "action": "refund", "params": {"order_id": 4512, "amount": 59.90},
            "rule_id": "R-REF-03", "facts_used": {"days_late": 6}, "user_confirmed": True}


def _approved_over_http(headers, order_id=4512, amount=59.90) -> str:
    """Record a proposal and an "approve" decision through the endpoints; return the proposal id."""
    pid = client.post("/coordinator/proposals", headers=headers,
                      json={**PROPOSAL, "params": {"order_id": order_id, "amount": amount}}).json()["id"]
    client.post(f"/coordinator/proposals/{pid}/decision", json={"decision": "approve", "reason": "t"}, headers=headers)
    return pid


def test_writes_refused_when_token_env_missing(monkeypatch):
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    before = _refund_count()
    r = client.post("/coordinator/refunds", json=REFUND, headers={"X-Coordinator-Token": "anything"})
    assert r.status_code == 403 and "disabled" in r.json()["error"]
    assert client.post("/admin/reset").status_code == 403
    assert _refund_count() == before


def test_writes_refused_without_or_with_wrong_token(token_on):
    before = _refund_count()
    assert client.post("/coordinator/refunds", json=REFUND).status_code == 403
    assert client.post("/coordinator/refunds", json=REFUND, headers={"X-Coordinator-Token": "wrong"}).status_code == 403
    assert client.post("/coordinator/subscriptions", json={"order_id": 4512, "event": "delivered"}).status_code == 403
    assert client.post("/coordinator/orders/4512/status", json={"new_status": "out_for_delivery"}).status_code == 403
    assert client.post("/layer3/decide", json={"order_id": 4515, "amount": 378}).status_code == 403
    assert _refund_count() == before
    assert client.get("/orders/4512").json()["status"] == "stuck_at_depot"


def test_refund_with_token(token_on):
    unknown = client.post("/coordinator/refunds", json={**REFUND, "proposal_id": "p-made-up"}, headers=token_on)
    assert unknown.status_code == 400 and "not found" in unknown.json()["error"]
    over_id = _approved_over_http(token_on, amount=70.00)
    over = client.post("/coordinator/refunds", json={**REFUND, "amount": 70.00, "proposal_id": over_id},
                       headers=token_on)
    assert over.status_code == 400 and "safety net" in over.json()["error"]
    ok = client.post("/coordinator/refunds", json={**REFUND, "proposal_id": _approved_over_http(token_on)},
                     headers=token_on)
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    assert client.get("/orders/4512/refunds").json()["refunded_total"] == 59.90


def test_nan_amount_is_400(token_on):
    before = _refund_count()
    body = '{"order_id": 4512, "amount": NaN, "rule_id": "R-REF-03", "proposal_id": "p-nan"}'
    r = client.post("/coordinator/refunds", content=body,
                    headers={**token_on, "Content-Type": "application/json"})
    assert r.status_code == 400 and "error" in r.json()
    assert _refund_count() == before


def test_other_writes_with_token(token_on):
    sub = client.post("/coordinator/subscriptions", json={"order_id": 4512, "event": "delivered"}, headers=token_on)
    assert sub.status_code == 200 and sub.json()["status"] == "waiting"
    bad = client.post("/coordinator/orders/4505/status", json={"new_status": "shipped"}, headers=token_on)
    assert bad.status_code == 400
    moved = client.post("/coordinator/orders/4512/status", json={"new_status": "out_for_delivery"}, headers=token_on)
    assert moved.status_code == 200 and moved.json()["event"]["event"] == "out_for_delivery"
    l3 = client.post("/layer3/decide", json={"order_id": 4515, "amount": 378.00, "reason": "t"}, headers=token_on)
    assert l3.status_code == 200 and l3.json()["decision"] == "approved"
    assert client.get("/events").json()[0]["event"] == "out_for_delivery"


def test_admin_reset(token_on):
    client.post("/coordinator/refunds", json={**REFUND, "proposal_id": _approved_over_http(token_on)}, headers=token_on)
    assert client.get("/orders/4512/refunds").json()["refunded_total"] == 59.90
    assert client.post("/admin/reset", headers=token_on).json()["reset"] is True
    assert client.get("/orders/4512/refunds").json()["refunded_total"] == 0.0


# --- localhost only -------------------------------------------------------

def test_run_script_binds_to_localhost():
    from scripts import run_platform_server
    assert run_platform_server.HOST == "127.0.0.1"



# --- P06 endpoints ---------------------------------------------------------

def test_proposal_endpoints(token_on):
    r = client.post("/coordinator/proposals", json=PROPOSAL, headers=token_on)
    assert r.status_code == 200 and r.json() == {"id": "P-0001"}
    assert client.post("/coordinator/proposals", json={"action": "refund"}, headers=token_on).status_code == 400
    d = client.post("/coordinator/proposals/P-0001/decision", json={"decision": "approve", "reason": "ok"},
                    headers=token_on)
    assert d.status_code == 200 and d.json()["decision"] == "approve"
    again = client.post("/coordinator/proposals/P-0001/decision", json={"decision": "escalate"}, headers=token_on)
    assert again.status_code == 400
    listed = client.get("/proposals").json()
    assert listed[0]["id"] == "P-0001" and listed[0]["params"]["order_id"] == 4512


def test_proposal_endpoints_need_the_token(monkeypatch):
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    assert client.post("/coordinator/proposals", json=PROPOSAL).status_code == 403
    assert client.post("/coordinator/proposals/P-0001/decision", json={"decision": "approve"}).status_code == 403
    assert client.post("/coordinator/subscriptions/1/sent").status_code == 403
    assert client.get("/proposals").json() == []


def test_notifications_over_http(token_on):
    sub = client.post("/coordinator/subscriptions", json={"order_id": 4512, "event": "delivered"}, headers=token_on).json()
    for status in ("out_for_delivery", "delivered"):
        client.post("/coordinator/orders/4512/status", json={"new_status": status}, headers=token_on)
    pending = client.get("/notifications/pending").json()
    assert len(pending) == 1 and pending[0]["subscription_id"] == sub["id"]
    sent = client.post(f"/coordinator/subscriptions/{sub['id']}/sent", headers=token_on)
    assert sent.status_code == 200 and sent.json()["status"] == "sent"
    assert client.get("/notifications/pending").json() == []
    assert client.post(f"/coordinator/subscriptions/{sub['id']}/sent", headers=token_on).status_code == 400


def test_simulator_data_is_not_over_http():
    paths = client.get("/openapi.json").json()["paths"]
    assert not any("own_case" in p or "scenario" in p for p in paths)
