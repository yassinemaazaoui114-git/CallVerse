"""Test setup for the web API: temporary accounts file and temporary databases, no model, no real data.

- accounts: a temp YAML in the same format as config/accounts.yaml, with the demo usernames and ONE test-only
  password ("test-only", bcrypt with 4 rounds so the tests stay fast). The real accounts file is never read.
- tickets: a temp callverse.db filled through callverse.tickets.store (the same functions the channel uses), so
  no pipeline, no agent and no model runs. The company databases point at temp paths (the store asks the
  simulation clock, which seeds a temp shopnova.db: that is the fixture's write, never the API's; a test checks
  the files are unchanged after every read).
- llm.chat is replaced by a function that fails the test: the API must never call a model.
"""

import sys
from pathlib import Path

import bcrypt
import pytest
import yaml
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from callverse import llm  # noqa: E402
from callverse.auth import accounts  # noqa: E402
from callverse.data import db as shopnova_db  # noqa: E402
from callverse.data.atlas import db as atlas_db  # noqa: E402
from callverse.tickets import store  # noqa: E402

from webui.api import auth, settings  # noqa: E402
from webui.api.app import create_app  # noqa: E402

PASSWORD = "test-only"
CSRF = {settings.CSRF_HEADER: settings.CSRF_VALUE}


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Temporary accounts + databases for every test; the defaults are put back afterwards."""
    hashed = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
    users = {}
    for username, name, _email, role, user_id in accounts.DEMO_ACCOUNTS:
        users[username] = {"name": name, "roles": [role], "user_id": user_id, "password": hashed,
                           "company": accounts.demo_company(username, role)}
    path = tmp_path / "accounts.yaml"
    path.write_text(yaml.safe_dump({"credentials": {"usernames": users},
                                    "cookie": {"name": "t", "key": "k" * 32, "expiry_days": 1}}), encoding="utf-8")
    accounts.use_accounts(path)
    store.use_db(tmp_path / "callverse_test.db")
    shopnova_db.use_db(tmp_path / "shopnova_never_created.db")
    atlas_db.use_db(tmp_path / "atlas_never_created.db")

    def no_model(*args, **kwargs):
        raise AssertionError("the web API must not call any model")
    monkeypatch.setattr(llm, "chat", no_model)

    yield tmp_path

    accounts.use_accounts(accounts.DEFAULT_ACCOUNTS_PATH)
    store.use_db(store.DEFAULT_DB_PATH)
    shopnova_db.use_db(shopnova_db.DEFAULT_DB_PATH)
    atlas_db.use_db(atlas_db.DEFAULT_DB_PATH)


@pytest.fixture
def shop_db(isolated_env):
    """A seeded TEMPORARY shopnova.db (the sample orders, scripted orders 4505-4515) for the customer routes.
    Seeded here on purpose: callverse.data.db.connect() would otherwise seed a missing file on the first read."""
    from callverse.data.seed import seed
    path = isolated_env / "shopnova_test.db"
    seed(path)
    shopnova_db.use_db(path)
    return path


@pytest.fixture
def client():
    """A fresh app and session store per test (everyone starts logged out)."""
    app = create_app(auth.SessionStore())
    with TestClient(app) as c:
        yield c


def portal_for(username: str) -> str:
    """The sign-in page a demo account uses: the supervisor the Console, Atlas accounts Atlas, the rest ShopNova."""
    if username == "supervisor":
        return "console"
    return "atlas" if username in accounts.ATLAS_ACCOUNTS else "shop"


def login(client: TestClient, username: str, password: str = PASSWORD, portal: str | None = None):
    return client.post("/api/auth/login", headers=CSRF,
                       json={"username": username, "password": password, "portal": portal or portal_for(username)})


@pytest.fixture
def supervisor(client):
    assert login(client, "supervisor").status_code == 200
    return client


def make_ticket(company: str, user_id: int, text: str, outcome: str = "approve", status: str = "Solved",
                reason: str = "refund_request", priority: str = "high", agent: str = "B") -> dict:
    """One ticket with one user message and a short step list, written with the store (no pipeline)."""
    t = store.create_ticket(company, user_id)
    mid = store.add_message(t["id"], "user", text)
    store.add_step(t["id"], mid, "intake", "intake", {"trace_step": "intake_ticket", "main_reason": reason,
                                                      "emotion": {"label": "anger", "score": 0.9},
                                                      "sentiment": "negative", "priority_label": priority,
                                                      "order_id": 4505, "seconds": 0.4})
    store.add_step(t["id"], mid, "route", "router", {"trace_step": "route", "agent": agent, "reason": reason, "layer": 2})
    store.add_step(t["id"], mid, "llm", "agent_b", {"trace_step": "llm_call", "role": "agent_b", "provider": "groq",
                                                   "model": "openai/gpt-oss-120b", "seconds": 2.0,
                                                   "tokens": {"total": 1200}})
    store.add_step(t["id"], mid, "tool_call", agent, {"trace_step": "tool_call", "agent": agent, "tool": "get_order",
                                                      "args": {"order_id": 4505}, "result": {"id": 4505, "status": "late"}})
    store.add_step(t["id"], mid, "search_policy", agent, {"trace_step": "tool_call", "agent": agent, "tool": "search_policy",
                                                          "args": {"query": "late refund"},
                                                          "result": {"results": [{"id": "R-REF-03"}]}})
    store.add_step(t["id"], mid, "proposal", "proposal_tools", {"trace_step": "proposal", "action": "refund",
                                                                "order_id": 4505, "amount": 50.0, "rule_id": "R-REF-03",
                                                                "user_confirmed": True, "facts_used": {"days_late": 8}})
    store.add_step(t["id"], mid, "coordinator", "coordinator", {"trace_step": "coordinator_check", "check": "rule_condition",
                                                                "rule_id": "R-REF-03", "result": "pass", "detail": "8 days late"})
    store.add_step(t["id"], mid, "coordinator", "coordinator", {"trace_step": "coordinator_decision", "outcome": outcome,
                                                                "reason": f"test decision {outcome}", "proposal_id": "P-0001",
                                                                "order_id": 4505})
    store.add_step(t["id"], mid, "slm", "pipeline", {"trace_step": "final_reply", "outcome": outcome,
                                                     "reply_source": "template", "seconds": 0.1})
    store.add_message(t["id"], "assistant", f"Reply for outcome {outcome}.", seconds=3.2)
    store.update_ticket(t["id"], status=status, main_reason=reason, priority=priority, lead_agent=agent)
    return store.get_ticket(t["id"])


@pytest.fixture
def live_server():
    """A real uvicorn server on 127.0.0.1 (random free port) for the tests that READ A STREAM WHILE IT RUNS:
    Starlette's TestClient delivers a streaming response only once it is complete. Same temp accounts and
    databases as the other tests (module-level `use_*` calls are process-wide). Yields the base URL."""
    import socket
    import threading
    import time

    import uvicorn

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = create_app(auth.SessionStore())
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(5)


def pending_approval(user_id: int = 2, order_id: int = 4515, amount: float = 378.0) -> dict:
    """A pending ShopNova approval as the channel makes it (same recipe as tests/test_layer3_queue.py): the
    Coordinator in queue mode records the proposal and answers layer3_pending; a ticket + the approvals row.
    Needs CALLVERSE_LAYER3_MODE=queue (the `queue_mode` fixture) and the seeded shop_db."""
    from callverse.coordinator.coordinator import new_case, review
    proposal = {"agent": "B", "action": "refund", "params": {"order_id": order_id, "amount": amount},
                "rule_id": "R-REF-03", "facts_used": {"days_late": 8, "delivered": False, "paid": amount,
                                                       "refunded_total": 0.0},
                "user_confirmed": True, "user_quote": "I want a refund please."}
    decision = review(proposal, new_case("T-0001"))
    assert decision["outcome"] == "layer3_pending", decision
    ticket = store.create_ticket("shopnova", user_id)
    store.add_message(ticket["id"], "user", f"My order {order_id} is very late, I want a refund please.")
    store.add_step(ticket["id"], None, "intake", "intake",
                   {"style": {"formality": "formal", "length": "short"}, "emotion": {"label": "anger"},
                    "sentiment": {"label": "negative"}, "main_reason": "refund_request"})
    store.update_ticket(ticket["id"], status="Waiting for finance")
    return store.create_approval(ticket["id"], order_id, decision["facts"]["amount_tnd"], decision["proposal_id"])


@pytest.fixture
def queue_mode(monkeypatch, shop_db):
    """Layer 3 in queue mode (the real admin queue), on the seeded temp shop database."""
    monkeypatch.setenv("CALLVERSE_LAYER3_MODE", "queue")
    return shop_db


@pytest.fixture
def atlas_db_seeded(isolated_env, monkeypatch):
    """A seeded TEMPORARY atlas.db (scripted bookings 7001-7012 + real data) in queue mode; the shop DB too."""
    from callverse.data.atlas.seed import seed as atlas_seed
    monkeypatch.setenv("CALLVERSE_LAYER3_MODE", "queue")
    path = isolated_env / "atlas_test.db"
    atlas_seed(path)
    atlas_db.use_db(path)
    return path


def pending_compensation(user_id: int = 5, booking_id: int = 7004) -> dict:
    """A pending Atlas COMPENSATION as the channel makes it: the Atlas Coordinator (queue mode) records the
    proposal, confirms it by code from the client's words, computes the amount and answers layer3_pending; then a
    ticket + the approvals row (company atlas, booking_type flight, action compensation)."""
    from callverse.coordinator import atlas_coordinator
    from callverse.coordinator.coordinator import new_case
    text = f"My flight {booking_id} was delayed for hours, I want a compensation please."
    ticket = store.create_ticket("atlas", user_id)
    store.add_message(ticket["id"], "user", text)
    store.add_step(ticket["id"], None, "intake", "intake",
                   {"style": {"formality": "formal", "length": "short"}, "emotion": {"label": "anger"},
                    "sentiment": {"label": "negative"}, "main_reason": "compensation_request"})
    proposal = {"agent": "B", "action": "compensation", "params": {"booking_type": "flight", "booking_id": booking_id},
                "rule_id": "AT-FLT-03", "facts_used": {"read": True}, "user_confirmed": True,
                "user_quote": "I want a compensation please."}
    case = {**new_case(ticket["id"]), "order_id": booking_id, "booking_type": "flight",
            "main_reason": "compensation_request", "user_message": text, "searched_rules": ["AT-FLT-03"]}
    decision = atlas_coordinator.review(proposal, case)
    assert decision["outcome"] == "layer3_pending", decision
    store.update_ticket(ticket["id"], status="Waiting for finance")
    return store.create_approval(ticket["id"], booking_id, decision["facts"]["amount_tnd"], decision["proposal_id"],
                                 company="atlas", booking_type="flight", action="compensation")


def pending_atlas_refund(user_id: int = 2, booking_id: int = 7006) -> dict:
    """A pending Atlas REFUND as the channel makes it: sonia's flight 7006 (1,900 TND, delayed 5 h or more) under
    AT-FLT-04; above the 1,500 TND finance limit, the Atlas Coordinator answers layer3_pending (seeded data,
    no core change, no model)."""
    from callverse.coordinator import atlas_coordinator
    from callverse.coordinator.coordinator import new_case
    text = f"My flight booking {booking_id} left hours late, I want a refund please."
    ticket = store.create_ticket("atlas", user_id)
    store.add_message(ticket["id"], "user", text)
    store.add_step(ticket["id"], None, "intake", "intake",
                   {"style": {"formality": "formal", "length": "short"}, "emotion": {"label": "anger"},
                    "sentiment": {"label": "negative"}, "main_reason": "refund_request"})
    proposal = {"agent": "B", "action": "refund", "params": {"booking_type": "flight", "booking_id": booking_id},
                "rule_id": "AT-FLT-04", "facts_used": {"read": True}, "user_confirmed": True,
                "user_quote": "I want a refund please."}
    case = {**new_case(ticket["id"]), "order_id": booking_id, "booking_type": "flight",
            "main_reason": "refund_request", "user_message": text, "searched_rules": ["AT-FLT-04"]}
    decision = atlas_coordinator.review(proposal, case)
    assert decision["outcome"] == "layer3_pending", decision
    store.update_ticket(ticket["id"], status="Waiting for finance")
    return store.create_approval(ticket["id"], booking_id, decision["facts"]["amount_tnd"], decision["proposal_id"],
                                 company="atlas", booking_type="flight", action="refund")
