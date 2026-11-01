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
def client():
    """A fresh app and session store per test (everyone starts logged out)."""
    app = create_app(auth.SessionStore())
    with TestClient(app) as c:
        yield c


def login(client: TestClient, username: str, password: str = PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password}, headers=CSRF)


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
