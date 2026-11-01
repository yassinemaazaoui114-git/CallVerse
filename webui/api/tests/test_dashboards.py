"""Step 6 tests: the Console Dashboard / Agents / Groq routes and the two admin dashboards, on temporary
databases. The numbers themselves are the core's (tests/test_console.py checks the math); here: every route,
roles and company isolation, the period filters as each read defines them, empty data, unknown values passed
through, and that the reads create nothing.

Run: pytest webui/api/tests -q
"""

import hashlib

import pytest
from conftest import CSRF, login, make_ticket

from callverse.tickets import store

CONSOLE = ("/api/console/dashboard", "/api/console/agents", "/api/console/groq")


def test_console_routes_need_the_supervisor(client):
    for path in CONSOLE:
        assert client.get(path).status_code == 401, path
    for username in ("sara", "admin", "atlas_admin", "hedi"):
        login(client, username)
        for path in CONSOLE:
            r = client.get(path)
            assert r.status_code == 403 and r.json()["error"] == "forbidden", (username, path)
        client.post("/api/auth/logout", headers=CSRF)


def test_console_dashboard_empty_then_numbers_and_periods(supervisor):
    body = supervisor.get("/api/console/dashboard").json()
    assert body["has_tickets"] is False and body["dashboard"] is None and body["no_tickets_message"]
    assert body["periods"] == {"All": None, "Last 7 days": 7, "Last 30 days": 30} and body["clock"] == "computer time"
    agents = supervisor.get("/api/console/agents").json()
    assert agents["has_tickets"] is False and agents["agents"] == []

    make_ticket("shopnova", 1, "I want a refund")
    make_ticket("atlas", 2, "Rebook me", outcome="escalate", status="Escalated", reason="rebooking", agent="A")
    body = supervisor.get("/api/console/dashboard").json()
    d = body["dashboard"]
    assert body["has_tickets"] is True and d["tickets"] == 2 and d["escalated"] == 1
    assert d["per_company"] == [{"company": "atlas", "tickets": 1}, {"company": "shopnova", "tickets": 1}]
    assert d["groq_today"]["limit"] == 200000 and d["groq_today"]["total"] >= 0
    assert "review_avg" in d and "reviews" in d                      # satisfaction, as the core returns it
    # the period filter is the core's: 7 / 30 / all, computer time; anything else is refused
    assert supervisor.get("/api/console/dashboard", params={"days": "7"}).json()["days"] == 7
    assert supervisor.get("/api/console/dashboard", params={"days": "all"}).json()["days"] is None
    r = supervisor.get("/api/console/dashboard", params={"days": "90"})
    assert r.status_code == 400 and r.json()["error"] == "bad_period"
    # a ticket older than 7 days falls out of "7" but stays in "all"
    with __import__("contextlib").closing(__import__("sqlite3").connect(store.db_path())) as con:
        con.execute("UPDATE tickets SET created_real = '2020-01-01T00:00:00' WHERE id = 'T-0001'")
        con.commit()
    assert supervisor.get("/api/console/dashboard", params={"days": "7"}).json()["dashboard"]["tickets"] == 1
    assert supervisor.get("/api/console/dashboard").json()["dashboard"]["tickets"] == 2


def test_console_agents_and_groq(supervisor):
    make_ticket("shopnova", 1, "I want a refund")
    cards = supervisor.get("/api/console/agents").json()["agents"]
    assert [c["agent"] for c in cards] == ["intake", "A", "B", "coordinator", "writer"]
    b = next(c for c in cards if c["agent"] == "B")
    assert b["tickets"] == 1 and b["tokens"] == 1200 and b["models"] == ["groq/openai/gpt-oss-120b"]
    assert next(c for c in cards if c["agent"] == "coordinator")["models"] == ["rules (no LLM)"]
    assert next(c for c in cards if c["agent"] == "writer")["avg_seconds"] is None or isinstance(
        next(c for c in cards if c["agent"] == "writer")["avg_seconds"], float)   # None passes through, never 0
    g = supervisor.get("/api/console/groq").json()["groq_today"]
    assert set(g) == {"tickets", "system", "total", "limit"}            # the core's numbers, nothing added
    assert supervisor.get("/api/console/agents", params={"days": "x"}).status_code == 400


def test_console_reads_create_no_company_file(supervisor, isolated_env):
    make_ticket("shopnova", 1, "hi")
    before = hashlib.sha256(store.db_path().read_bytes()).hexdigest()
    for path in CONSOLE:
        assert supervisor.get(path).status_code == 200, path
    assert hashlib.sha256(store.db_path().read_bytes()).hexdigest() == before
    assert not (isolated_env / "atlas_never_created.db").exists()


# ---------- the two admin dashboards ----------

def test_shop_dashboard_roles_periods_and_shape(client, shop_db):
    for username, code in (("sara", "admin_only"), ("atlas_admin", "admin_only"), ("supervisor", "admin_only")):
        login(client, username)
        r = client.get("/api/admin/dashboard")
        assert r.status_code == 403 and r.json()["error"] == code, username
        client.post("/api/auth/logout", headers=CSRF)
    assert client.get("/api/admin/dashboard").status_code == 401
    login(client, "admin")
    body = client.get("/api/admin/dashboard").json()
    assert body["days"] == 30 and body["periods"] == [7, 30, 90] and body["clock"] == "simulation clock"
    d = body["dashboard"]
    assert d["today"] == "2026-10-09" and d["days"] == 30 and len(d["sales_per_day"]) == 30
    assert set(d) >= {"orders", "sales_tnd", "orders_by_status", "late", "late_orders", "stuck", "refunds_paid",
                      "top_products", "top_categories", "review_scores", "review_average", "review_count", "low_stock"}
    assert client.get("/api/admin/dashboard", params={"days": 7}).json()["dashboard"]["days"] == 7
    assert len(client.get("/api/admin/dashboard", params={"days": 90}).json()["dashboard"]["sales_per_day"]) == 90
    r = client.get("/api/admin/dashboard", params={"days": 14})
    assert r.status_code == 400 and r.json()["error"] == "bad_period"


def test_shop_dashboard_unknown_values_pass_through(client, shop_db, monkeypatch):
    """A period with no review has review_average None: the API must not turn it into 0."""
    from callverse.data import admin_reads
    real = admin_reads.dashboard
    monkeypatch.setattr(admin_reads, "dashboard", lambda days: {**real(days), "review_average": None, "review_count": 0})
    login(client, "admin")
    d = client.get("/api/admin/dashboard").json()["dashboard"]
    assert d["review_average"] is None and d["review_count"] == 0


def test_atlas_dashboard_roles_periods_and_shape(client, atlas_db_seeded):
    for username in ("sara", "admin", "supervisor", "hedi"):
        login(client, username)
        assert client.get("/api/atlas/admin/dashboard").status_code == 403, username
        client.post("/api/auth/logout", headers=CSRF)
    login(client, "atlas_admin")
    body = client.get("/api/atlas/admin/dashboard").json()
    assert body["days"] is None and body["periods"] == {"Last 7 days": 7, "Last 30 days": 30, "All": None}
    d = body["dashboard"]
    assert d["start"] is None and d["today"] == "2026-10-09" and d["upcoming_until"] == "2026-10-23"
    assert set(d) >= {"hotel_by_status", "flight_by_status", "hotel_cancellation_rate", "flight_delay_rate",
                      "flight_cancellation_rate", "refunds_paid", "compensation_paid", "upcoming_arrivals",
                      "upcoming_departures"}
    week = client.get("/api/atlas/admin/dashboard", params={"days": "7"}).json()
    assert week["days"] == 7 and week["dashboard"]["start"] == "2026-10-03"
    assert client.get("/api/atlas/admin/dashboard", params={"days": "90"}).status_code == 400
    # the ShopNova admin: not this company
    client.post("/api/auth/logout", headers=CSRF)
    login(client, "admin")
    assert client.get("/api/atlas/admin/dashboard").status_code == 403


def test_admin_dashboards_need_the_company_file(client, isolated_env):
    login(client, "admin")
    r = client.get("/api/admin/dashboard")
    assert r.status_code == 503 and r.json()["error"] == "setup_required"
    assert not (isolated_env / "shopnova_never_created.db").exists()
    client.post("/api/auth/logout", headers=CSRF)
    login(client, "atlas_admin")
    assert client.get("/api/atlas/admin/dashboard").status_code == 503
    assert not (isolated_env / "atlas_never_created.db").exists()
