"""T27 tests: Agent D's owner screens over the EXISTING core functions, on temporary seeded databases, no model
(llm.chat fails the test; the scan uses template wording).

- who may open them (401 / 403 for customers, the supervisor and the other company's admin; CSRF on POST);
- Check now: the real AgentD scan through callverse.channels.approvals.run_stock_scan, counts back;
- Promotions / Hotel deals: the lists (pending, decided, empty), approve, refuse (reason required), the double
  decision (a second decision is refused, the same request asked again gets the recorded answer, two at once
  decide once), a missing id.

Run: pytest webui/api/tests -q
"""

import threading
import time

import pytest
from conftest import CSRF, login

from webui.api import owner

SHOP = {"list": "/api/admin/promotions", "scan": "/api/admin/stock-check", "admin": "admin", "other_admin": "atlas_admin"}
ATLAS = {"list": "/api/atlas/admin/deals", "scan": "/api/atlas/admin/room-check", "admin": "atlas_admin",
         "other_admin": "admin"}


@pytest.fixture(autouse=True)
def both_dbs(queue_mode, atlas_db_seeded):
    """Seeded temp shopnova.db AND atlas.db; the real scan is put back after each test."""
    yield
    owner.use_scan_fn(None)


def decide(client, base, row_id, approve, reason="", **extra):
    return client.post(f"{base}/{row_id}/decision", json={"approve": approve, "reason": reason, **extra}, headers=CSRF)


def scan(client, side):
    return client.post(side["scan"], headers=CSRF)


@pytest.mark.parametrize("side", [SHOP, ATLAS], ids=["promotions", "deals"])
def test_only_the_company_admin_may_open_them(client, side):
    paths = (side["list"], f"{side['list']}?status=decided")
    for path in paths:
        assert client.get(path).status_code == 401
    assert scan(client, side).status_code == 401
    assert decide(client, side["list"], 1, True).status_code == 401
    for username in ("sara", "hedi", "supervisor", side["other_admin"]):   # customers of both, supervisor, other admin
        login(client, username)
        for path in paths:
            r = client.get(path)
            assert r.status_code == 403 and r.json()["error"] == "admin_only", (username, path)
        assert scan(client, side).status_code == 403, username
        assert decide(client, side["list"], 1, True).status_code == 403, username
        client.post("/api/auth/logout", headers=CSRF)
    login(client, side["admin"])
    assert client.get(side["list"]).status_code == 200
    assert client.post(side["scan"]).status_code == 403                                  # no CSRF header
    assert client.post(f"{side['list']}/1/decision", json={"approve": True}).status_code == 403
    assert client.get(side["list"], params={"status": "weird"}).status_code == 400


@pytest.mark.parametrize("side", [SHOP, ATLAS], ids=["promotions", "deals"])
def test_empty_list_before_any_scan(client, side):
    login(client, side["admin"])
    for status in ("pending", "decided"):
        body = client.get(side["list"], params={"status": status}).json()
        assert body["count"] == 0 and body["items"] == []
    assert decide(client, side["list"], 999, True).status_code == 404


def test_check_now_shopnova_then_promotions_with_facts(client):
    login(client, "admin")
    r = scan(client, SHOP)
    assert r.status_code == 200, r.text
    counts = r.json()["counts"]
    assert set(counts) == {"short", "over", "proposed"} and counts["proposed"] >= 1
    items = client.get(SHOP["list"]).json()["items"]
    assert len(items) == counts["proposed"] and all(p["status"] == "pending" for p in items)
    p = items[0]
    assert p["product_name"] and p["discount_pct"] == 10 and p["note"]
    assert set(p["facts"]) == {"stock", "units_sold_30d", "days_of_cover"} and p["facts"]["stock"] == p["stock"]


def test_check_now_atlas_then_deals_with_facts(client):
    login(client, "atlas_admin")
    r = scan(client, ATLAS)
    assert r.status_code == 200, r.text
    counts = r.json()["counts"]
    assert set(counts) == {"overbooked", "low", "proposed"}
    items = client.get(ATLAS["list"]).json()["items"]
    assert len(items) == counts["proposed"] >= 1
    d = items[0]
    assert d["hotel_name"] and d["nights"] and d["first_night"] == min(d["nights"]) and d["last_night"] == max(d["nights"])
    assert d["facts"]["capacity"] and d["facts"]["min_occupancy_pct"] is not None


@pytest.mark.parametrize("side", [SHOP, ATLAS], ids=["promotions", "deals"])
def test_approve_then_a_second_decision_is_refused(client, side):
    login(client, side["admin"])
    scan(client, side)
    first = client.get(side["list"]).json()["items"][0]
    r = decide(client, side["list"], first["id"], True, client_id="c-1")
    assert r.status_code == 200, r.text
    item = r.json()["item"]
    assert item["status"] == "approved" and item["decided_by"] == side["admin"] and item["decided_at"]
    again = decide(client, side["list"], first["id"], True, client_id="c-1")     # the same request again (lost answer)
    assert again.status_code == 200 and again.json()["recorded"] is True and again.json()["item"]["id"] == first["id"]
    other = decide(client, side["list"], first["id"], False, "changed my mind", client_id="c-2")
    assert other.status_code == 409 and other.json()["error"] == "already_decided"
    reused = decide(client, side["list"], first["id"], False, "x", client_id="c-1")   # same id, other content
    assert reused.status_code == 409 and reused.json()["error"] == "client_id_reused"
    decided = client.get(side["list"], params={"status": "decided"}).json()["items"]
    assert [x["id"] for x in decided] == [first["id"]]
    assert first["id"] not in [x["id"] for x in client.get(side["list"]).json()["items"]]


@pytest.mark.parametrize("side", [SHOP, ATLAS], ids=["promotions", "deals"])
def test_refuse_needs_a_reason(client, side):
    login(client, side["admin"])
    scan(client, side)
    first = client.get(side["list"]).json()["items"][0]
    r = decide(client, side["list"], first["id"], False, "   ")
    assert r.status_code == 400 and r.json()["error"] == "reason_required"
    r = decide(client, side["list"], first["id"], False, "Not this season")
    assert r.status_code == 200 and r.json()["item"]["status"] == "refused" and r.json()["item"]["reason"] == "Not this season"


@pytest.mark.parametrize("side", [SHOP, ATLAS], ids=["promotions", "deals"])
def test_double_click_at_the_same_time_decides_once(client, side, monkeypatch):
    """Two decisions on the same row at the same time: the second gets 409 while the first runs; one write."""
    login(client, side["admin"])
    scan(client, side)
    first = client.get(side["list"]).json()["items"][0]
    name = "decide_promotion" if side is SHOP else "decide_deal"
    real = getattr(owner, name)
    calls = []

    def slow(*args):
        calls.append(args)
        time.sleep(0.4)
        return real(*args)
    monkeypatch.setattr(owner, name, slow)
    answers = []

    def click(cid):
        answers.append(decide(client, side["list"], first["id"], True, client_id=cid).status_code)
    threads = [threading.Thread(target=click, args=(f"x-{i}",)) for i in range(2)]
    for t in threads:
        t.start()
        time.sleep(0.05)
    for t in threads:
        t.join()
    assert sorted(answers) == [200, 409], answers
    assert client.get(side["list"], params={"status": "decided"}).json()["count"] == 1


def test_scan_twice_at_once_runs_once_and_errors_are_shown(client):
    login(client, "admin")
    started = threading.Event()

    def slow_scan(company):
        started.set()
        time.sleep(0.4)
        return {"short": 0, "over": 0, "proposed": 0}
    owner.use_scan_fn(slow_scan)
    answers = []
    t = threading.Thread(target=lambda: answers.append(scan(client, SHOP).status_code))
    t.start()
    started.wait(2)
    second = scan(client, SHOP)
    t.join()
    assert second.status_code == 409 and second.json()["error"] == "scan_in_progress" and answers == [200]

    def broken(company):
        raise RuntimeError("database locked")
    owner.use_scan_fn(broken)
    r = scan(client, SHOP)
    assert r.status_code == 500 and r.json()["error"] == "scan_failed" and "database locked" in r.json()["message"]
    owner.use_scan_fn(lambda company: {"short": 1, "over": 2, "proposed": 0})
    assert scan(client, SHOP).status_code == 200          # the guard was released after the error


def test_urgent_flag_on_console_tickets(client):
    """The Console rows and the ticket detail say `urgent` when the core marked the ticket urgent: Agent C's
    "urgent refund" handover step, or an approval row with urgent = 1. Other tickets are not urgent."""
    from conftest import make_ticket
    from callverse.tickets import store
    plain = make_ticket("shopnova", 1, "Where is my order?")
    by_step = make_ticket("shopnova", 2, "I need it before Friday, else refund me.")
    store.add_step(by_step["id"], None, "route", "pipeline", {"trace_step": "handover", "to": "B", "by": "agent_C",
                                                              "urgent": True, "text": "passed on as urgent"})
    by_approval = make_ticket("atlas", 3, "Refund my flight now.")
    store.create_approval(by_approval["id"], 7006, 1900.0, "AP-9", company="atlas", booking_type="flight", urgent=True)
    login(client, "supervisor")
    rows = {t["id"]: t["urgent"] for t in client.get("/api/console/tickets").json()["tickets"]}
    assert rows == {plain["id"]: False, by_step["id"]: True, by_approval["id"]: True}
    assert client.get(f"/api/console/tickets/{by_step['id']}").json()["urgent"] is True
    assert client.get(f"/api/console/tickets/{plain['id']}").json()["urgent"] is False
    detail = client.get(f"/api/console/tickets/{by_approval['id']}").json()
    assert detail["urgent"] is True and detail["approvals"][0]["urgent"] == 1
