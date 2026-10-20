"""ShopNova platform as a LOCAL web server (FastAPI). Run it with: python scripts/run_platform_server.py

It is only a thin HTTP layer over the existing platform functions; no business rule is written here:
- read endpoints      -> shopnova_tools / policies / reports (anyone on this PC, e.g. the dashboard)
- POST /tools/{name}  -> registry.run_tool(agent, name, args): the agent's allow-list is checked there,
                         exactly as when an agent runs in Python. Refused tool -> HTTP 403.
- Coordinator writes  -> writes.py / layer3.py. They need the header X-Coordinator-Token equal to
                         PLATFORM_COORDINATOR_TOKEN from .env. If that variable is missing or empty, every
                         write is refused (403): writes are OFF by default. A write the function refuses
                         (e.g. safety net) returns its {"error": ...} with HTTP 400.
- GET /               -> a read-only HTML dashboard (dashboard.html, no buttons that write).
Every request is written to the trace (actor "server"), with the agent id when one is given.
The server must only listen on 127.0.0.1 (see scripts/run_platform_server.py).
"""

import os
import secrets
from collections import deque
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from callverse import trace
from callverse.config import PROJECT_ROOT
from callverse.data import db, layer3, reports, writes
from callverse.data.seed import seed
from callverse.kb.policies import get_policy, load_policies
from callverse.tools import registry, shopnova_tools

# Read .env so PLATFORM_COORDINATOR_TOKEN is available (its value is never printed or returned).
load_dotenv(PROJECT_ROOT / ".env")

TOKEN_ENV = "PLATFORM_COORDINATOR_TOKEN"
DASHBOARD = Path(__file__).resolve().parent / "dashboard.html"

app = FastAPI(title="ShopNova platform (local)",
              description="Local mock company for CallVerse. Reads are open on this PC; writes need the "
                          "Coordinator token. Agents call tools through POST /tools/{name}.")


# ---------------------------------------------------------------------------
# Trace: one line per request
# ---------------------------------------------------------------------------
@app.middleware("http")
async def trace_requests(request: Request, call_next):
    response = await call_next(request)
    data = {"method": request.method, "path": request.url.path, "status": response.status_code}
    if request.url.query:
        data["query"] = request.url.query
    agent = getattr(request.state, "agent", None)  # set by POST /tools/{name}
    if agent:
        data["agent"] = agent
    trace.log("http_request", "server", data)
    return response


def _result(result: Any, error_status: int = 404) -> JSONResponse:
    """Return a function's result as JSON; a dict with "error" gets `error_status`."""
    status = error_status if isinstance(result, dict) and "error" in result else 200
    return JSONResponse(result, status_code=status)


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def dashboard() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


@app.get("/company")
def company():
    return _result(shopnova_tools.get_company_profile(), error_status=500)


@app.get("/policies")
def policies():
    return load_policies()


@app.get("/policies/{rule_id}")
def policy(rule_id: str):
    rule = get_policy(rule_id)
    return _result(rule if rule else {"error": f"policy {rule_id} not found"})


@app.get("/orders")
def orders(status: str | None = None, scripted: int | None = None, limit: int = 50):
    return reports.list_orders(status=status, scripted=scripted, limit=limit)


@app.get("/orders/{order_id}")
def order(order_id: int):
    return _result(shopnova_tools.get_order(order_id))


@app.get("/orders/{order_id}/tracking")
def tracking(order_id: int):
    return _result(shopnova_tools.get_tracking(order_id))


@app.get("/orders/{order_id}/refunds")
def refunds(order_id: int):
    return _result(shopnova_tools.get_refunds(order_id))


@app.get("/users/{user_id}")
def user(user_id: int):
    return _result(shopnova_tools.get_user(user_id=user_id))


@app.get("/summary")
def summary():
    return reports.summary()


@app.get("/refunds")
def all_refunds(limit: int = 100):
    return reports.list_rows("refunds", limit)


@app.get("/subscriptions")
def all_subscriptions(limit: int = 100):
    return reports.list_rows("subscriptions", limit)


@app.get("/events")
def all_events(limit: int = 100):
    return reports.list_rows("events", limit)


@app.get("/proposals")
def all_proposals(limit: int = 100):
    return reports.list_rows("proposals", limit)


@app.get("/notifications/pending")
def pending_notifications():
    """Events that match a waiting subscription (what the notifier must send). Read-only."""
    return reports.get_pending_notifications()


@app.get("/traces/recent")
def recent_traces(n: int = 20):
    """Last n lines of this server run's trace file (newest last)."""
    path = trace.current_path()
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [line.rstrip("\n") for line in deque(f, maxlen=max(1, min(n, 200)))]


# ---------------------------------------------------------------------------
# Agent tool calls (allow-list checked by the registry)
# ---------------------------------------------------------------------------
class ToolCall(BaseModel):
    agent: str
    args: dict[str, Any] = {}


@app.post("/tools/{name}")
def call_tool(name: str, call: ToolCall, request: Request):
    request.state.agent = call.agent
    result = registry.run_tool(call.agent, name, call.args)  # checks the allow-list and traces the call
    refused = name not in registry.ALLOW_LISTS.get(call.agent, [])
    # A tool result with "error" (e.g. order not found) is still a normal answer for the agent: HTTP 200.
    return JSONResponse(result, status_code=403 if refused else 200)


# ---------------------------------------------------------------------------
# Coordinator writes (token required)
# ---------------------------------------------------------------------------
def _token_refusal(token: str | None) -> JSONResponse | None:
    """None if the token is right; otherwise a 403 response. Writes are off when the variable is missing."""
    expected = os.getenv(TOKEN_ENV, "")
    if not expected:
        return JSONResponse({"error": f"writes are disabled: {TOKEN_ENV} is not set in .env"}, status_code=403)
    if not token or not secrets.compare_digest(token, expected):
        return JSONResponse({"error": "missing or wrong X-Coordinator-Token"}, status_code=403)
    return None


class RefundIn(BaseModel):
    order_id: int
    amount: Any            # not checked here on purpose: create_refund's own guard decides
    rule_id: str
    proposal_id: str


class DecisionIn(BaseModel):
    decision: str
    reason: str = ""


class SubscriptionIn(BaseModel):
    order_id: int
    event: str
    proposal_id: str | None = None   # required by create_subscription; missing -> refused (400)


class StatusIn(BaseModel):
    new_status: str


class Layer3In(BaseModel):
    order_id: int
    amount: Any
    reason: str = ""


@app.post("/coordinator/refunds")
def coordinator_refund(body: RefundIn, x_coordinator_token: str | None = Header(default=None)):
    if (refusal := _token_refusal(x_coordinator_token)) is not None:
        return refusal
    return _result(writes.create_refund(body.order_id, body.amount, body.rule_id, body.proposal_id), 400)


@app.post("/coordinator/proposals")
def coordinator_proposal(proposal: dict[str, Any], x_coordinator_token: str | None = Header(default=None)):
    """Record an agent proposal. Returns {"id": "P-0001"} or {"error": ...} (400)."""
    if (refusal := _token_refusal(x_coordinator_token)) is not None:
        return refusal
    return _result(writes.record_proposal(proposal), 400)


@app.post("/coordinator/proposals/{proposal_id}/decision")
def coordinator_decision(proposal_id: str, body: DecisionIn, x_coordinator_token: str | None = Header(default=None)):
    if (refusal := _token_refusal(x_coordinator_token)) is not None:
        return refusal
    return _result(writes.record_decision(proposal_id, body.decision, body.reason), 400)


@app.post("/coordinator/subscriptions/{subscription_id}/sent")
def coordinator_subscription_sent(subscription_id: int, x_coordinator_token: str | None = Header(default=None)):
    if (refusal := _token_refusal(x_coordinator_token)) is not None:
        return refusal
    return _result(writes.mark_subscription_sent(subscription_id), 400)


@app.post("/coordinator/subscriptions")
def coordinator_subscription(body: SubscriptionIn, x_coordinator_token: str | None = Header(default=None)):
    if (refusal := _token_refusal(x_coordinator_token)) is not None:
        return refusal
    return _result(writes.create_subscription(body.order_id, body.event, body.proposal_id), 400)


@app.post("/coordinator/orders/{order_id}/status")
def coordinator_status(order_id: int, body: StatusIn, x_coordinator_token: str | None = Header(default=None)):
    if (refusal := _token_refusal(x_coordinator_token)) is not None:
        return refusal
    return _result(writes.set_order_status(order_id, body.new_status), 400)


@app.post("/layer3/decide")
def layer3_decide(body: Layer3In, x_coordinator_token: str | None = Header(default=None)):
    if (refusal := _token_refusal(x_coordinator_token)) is not None:
        return refusal
    return _result(layer3.layer3_decide(body.order_id, body.amount, body.reason), 400)


@app.post("/admin/reset")
def admin_reset(x_coordinator_token: str | None = Header(default=None)):
    """Re-seed the database (fresh demo data)."""
    if (refusal := _token_refusal(x_coordinator_token)) is not None:
        return refusal
    path = seed()
    trace.log("db_reset", "server", {"db": path.name})
    return {"reset": True, "db": db.db_path().name}
