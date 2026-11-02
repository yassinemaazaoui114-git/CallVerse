"""The demo fixture itself (webui/api/dev_fixture.py), as the acceptance walkthrough uses it: dev_fixture.main runs
in a fresh temporary folder, then the three advertised approvals are decided through the API with the fixture's
fake reply writer (no model). Checked: the queues show exactly the advertised cases with their real proposals, each
decision writes the money record once (never twice, never the wrong kind), tells the customer who owns the
booking / order, and a refusal pays nothing. Run: pytest webui/api/tests -q
"""

import pytest
from conftest import CSRF, login

from callverse.auth import accounts
from callverse.data.atlas import reads as atlas_reads
from callverse.tickets import store
from callverse.tools.shopnova_tools import get_order, get_refunds

from webui.api import admin, dev_fixture


@pytest.fixture
def demo(tmp_path, monkeypatch):
    """A fresh fixture folder, the API pointed at it (as the CALLVERSE_WEBUI_* variables do) and the fake writer."""
    monkeypatch.delenv("CALLVERSE_LAYER3_MODE", raising=False)   # main() must set queue mode itself
    folder = tmp_path / "demo"
    made = dev_fixture.main(folder)
    assert (folder / "accounts.yaml").exists() and (folder / "callverse.db").exists()
    assert (folder / "shopnova.db").exists() and (folder / "atlas.db").exists()
    accounts.use_accounts(folder / "accounts.yaml")              # main() already called the three use_db
    admin.use_slm_fn(dev_fixture.fake_slm)
    yield made
    admin.use_slm_fn(None)
    accounts.use_accounts(accounts.DEFAULT_ACCOUNTS_PATH)


def decide(client, prefix, approval_id, approve, reason, client_id):
    return client.post(f"{prefix}/{approval_id}/decide", json={"approve": approve, "reason": reason, "client_id": client_id},
                       headers=CSRF)


def switch(client, username):
    client.post("/api/auth/logout", headers=CSRF)
    assert login(client, username, dev_fixture.PASSWORD).status_code == 200


def test_fixture_queues_show_exactly_the_advertised_cases(client, demo):
    assert set(demo) == {"shop_refund", "atlas_compensation", "atlas_refund"}
    login(client, "admin", dev_fixture.PASSWORD)
    rows = client.get("/api/admin/approvals").json()["approvals"]
    assert [r["id"] for r in rows] == [demo["shop_refund"]["id"]]
    shop = rows[0]
    assert shop["order_id"] == 4515 and shop["amount"] == 378.0 and shop["action"] == "refund"
    assert shop["proposal"] and shop["proposal"]["decision"] is None            # a real recorded proposal
    assert shop["facts"]["rule_id"] == "R-REF-03" and shop["facts"]["paid"] == 378.0
    assert store.get_ticket(shop["ticket_id"])["user_id"] == 2 == get_order(4515)["user_id"]   # youssef owns both
    switch(client, "atlas_admin")
    rows = client.get("/api/atlas/admin/approvals").json()["approvals"]
    by_booking = {r["order_id"]: r for r in rows}
    assert set(by_booking) == {7004, 7006}
    assert by_booking[7004]["action"] == "compensation" and by_booking[7004]["amount"] == 839.5
    assert by_booking[7006]["action"] == "refund" and by_booking[7006]["amount"] == 1900.0
    for booking_id, user_id in ((7004, 5), (7006, 2)):
        row = by_booking[booking_id]
        assert row["proposal"] and row["booking_type"] == "flight"
        assert store.get_ticket(row["ticket_id"])["user_id"] == user_id == atlas_reads.get_flight_booking(booking_id)["user_id"]
    # the other tickets belong to the owners of what they talk about (sara 4512, youssef 4510, leila 4514)
    for ticket_id, user_id, order_id in (("T-0001", 1, 4512), ("T-0002", 2, 4510), ("T-0005", 5, 4514)):
        assert store.get_ticket(ticket_id)["user_id"] == user_id == get_order(order_id)["user_id"]
        assert str(order_id) in store.messages(ticket_id)[0]["text"]


def test_shop_refund_is_paid_once_and_youssef_is_told(client, demo):
    a = demo["shop_refund"]
    login(client, "admin", dev_fixture.PASSWORD)
    r = decide(client, "/api/admin/approvals", a["id"], True, "late and stuck, refund", "fx-shop")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == "approve" and body["refund"]["amount"] == 378.0 and body["compensation"] is None
    assert get_order(4515)["status"] == "refunded" and [x["amount"] for x in get_refunds(4515)["refunds"]] == [378.0]
    # the same request again: the recorded answer, no second refund; a new decision: already decided
    again = decide(client, "/api/admin/approvals", a["id"], True, "late and stuck, refund", "fx-shop")
    assert again.status_code == 200 and again.json()["recorded"] is True
    assert decide(client, "/api/admin/approvals", a["id"], True, "once more", "fx-shop-2").status_code == 409
    assert len(get_refunds(4515)["refunds"]) == 1
    ev = client.get(f"/api/admin/approvals/{a['id']}").json()["evidence"]
    assert ev["stage"] == "complete" and ev["notification"] == "confirmed"
    switch(client, "youssef")
    convo = client.get("/api/shop/chat").json()
    assert convo["unread"][0]["id"] == a["ticket_id"]
    last = convo["messages"][-1]
    print("CUSTOMER REPLY:", last["text"])
    assert last["sender"] == "assistant" and last["text"]            # the reply the core wrote (fake writer or its template)
    switch(client, "sara")                                              # not her ticket: nothing for her
    assert client.get("/api/shop/chat").json()["unread"] == []


def test_atlas_compensation_approved_and_refund_refused(client, demo):
    comp, ref = demo["atlas_compensation"], demo["atlas_refund"]
    login(client, "atlas_admin", dev_fixture.PASSWORD)
    r = decide(client, "/api/atlas/admin/approvals", comp["id"], True, "delay confirmed", "fx-comp")
    assert r.status_code == 200, r.text
    assert r.json()["compensation"]["amount"] == 839.5 and r.json()["refund"] is None
    assert [c["amount"] for c in atlas_reads.get_compensations("flight", 7004)["compensations"]] == [839.5]
    assert atlas_reads.get_refunds("flight", 7004)["refunds"] == []
    r = decide(client, "/api/atlas/admin/approvals", ref["id"], False, "airline already refunded", "fx-ref")
    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "layer3_refused" and r.json()["refund"] is None and r.json()["compensation"] is None
    assert atlas_reads.get_refunds("flight", 7006)["refunds"] == [] and atlas_reads.get_compensations("flight", 7006)["compensations"] == []
    assert client.get("/api/atlas/admin/approvals").json()["count"] == 0
    assert client.get("/api/atlas/admin/approvals", params={"status": "decided"}).json()["count"] == 2
    # the ShopNova queue is untouched by the Atlas decisions
    switch(client, "admin")
    assert [x["id"] for x in client.get("/api/admin/approvals").json()["approvals"]] == [demo["shop_refund"]["id"]]
    # each customer got their own reply, nobody else's
    switch(client, "nizar")
    convo = client.get("/api/atlas/chat").json()
    assert [u["id"] for u in convo["unread"]] == [comp["ticket_id"]] and convo["messages"][-1]["sender"] == "assistant"
    switch(client, "sonia")
    convo = client.get("/api/atlas/chat").json()
    assert [u["id"] for u in convo["unread"]] == [ref["ticket_id"]] and convo["messages"][-1]["sender"] == "assistant"
    switch(client, "hedi")
    assert client.get("/api/atlas/chat").json()["unread"] == []
