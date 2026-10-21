"""P09: demo screen routes. No API call, no local model: fake LLM, fake Intake, stubbed policy search,
offline SLM (conftest -> template). Temporary DB and trace folder only (conftest)."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from callverse import llm, pipeline, trace
from callverse.config import load_config
from callverse.data import clock
from callverse.kb import search
from callverse.server import demo
from callverse.server.app import app
from callverse.tools.shopnova_tools import get_order

client = TestClient(app)
S1_TEXT = "Order 4512 is a week late. I want my money back."
GOOD = {"order_id": 4512, "amount": 59.90, "rule_id": "R-REF-03",
        "facts_used": {"days_late": 6, "delivered": False, "paid": 59.90, "refunded_total": 0.0},
        "user_confirmed": True, "user_quote": "I want my money back."}


def text_reply(text):
    return SimpleNamespace(content=text, tool_calls=None)


def tool_reply(name, arguments):
    tc = SimpleNamespace(id="c1", function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))
    return SimpleNamespace(content=None, tool_calls=[tc])


def fake_llm(role_key, messages, tools=None):
    """Stateless fake: the step of an agent run = how many tool results it has already seen,
    so a new run (e.g. after a send-back) starts again from step 0."""
    step = sum(1 for m in messages if m.get("role") == "tool")
    if messages[0]["content"].startswith("You are Agent A"):
        order = 4510 if "4510" in json.dumps(messages) else 4512
        steps = [tool_reply("get_tracking", {"order_id": order}), text_reply(f"Order {order}: status checked.")]
    else:
        steps = [tool_reply("get_order", {"order_id": 4512}),
                 tool_reply("ask_agent", {"agent": "A", "question": "Delivery status of order 4512?"}),
                 tool_reply("get_refunds", {"order_id": 4512}),
                 tool_reply("search_policy", {"query": "refund for a late order"}),
                 tool_reply("propose_refund", GOOD)]
    return steps[step] if step < len(steps) else text_reply("Sent for checking.")


def fake_intake(text, use_llm=True, chat_fn=None):
    """Stands in for Intake (its local models are not needed here); writes the same trace line."""
    order = 4510 if "4510" in text else 4512
    refund = "money" in text.lower() or "refund" in text.lower()
    ticket = {"ticket_id": "T-demo", "text": text, "order_id": order,
              "reasons": [{"reason": "refund_request" if refund else "order_status", "score": 0.8, "sentence": text}],
              "main_reason": "refund_request" if refund else "order_status",
              "emotion": {"label": "neutral", "score": 0.9}, "sentiment": {"label": "neutral", "score": 0.8},
              "priority_label": "high" if refund else "low", "priority_score": 0.7 if refund else 0.2,
              "style": {"formality": "neutral", "length": "short", "shouting": False}, "needs_llm": False}
    trace.log("intake_ticket", "intake", ticket)
    return ticket


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setitem(load_config()["server"], "demo_enabled", True)
    monkeypatch.setattr(llm, "chat", fake_llm)
    monkeypatch.setattr(pipeline.intake, "process", fake_intake)
    monkeypatch.setattr(search, "search_policy",
                        lambda query, k=3: [{"id": "R-REF-03", "title": "", "text": "", "score": 1.0}])


def stage(data, name):
    return next((s for s in data["stages"] if s["name"] == name), {"items": []})


# --- message and stages -------------------------------------------------------

def test_message_s1_returns_reply_and_stages(demo_on):
    r = client.post("/demo/message", json={"text": S1_TEXT})
    data = r.json()
    assert r.status_code == 200
    assert "Your refund of 59.90 TND is approved." in data["final_reply"]
    assert data["route"]["agent"] == "B" and data["decision"]["outcome"] == "approve"
    assert data["run_id"].startswith("run_") and isinstance(data["seconds"], float)
    names = [s["name"] for s in data["stages"]]
    assert len(names) >= 5
    assert names[:6] == ["Intake", "Route", "Agent", "Coordinator", "Platform writes", "Final reply"]
    checks = [i for i in stage(data, "Coordinator")["items"] if "PASS" in i["text"] or "FAIL" in i["text"]]
    assert checks and all(i["status"] == "pass" for i in checks)
    writes = " ".join(i["text"] for i in stage(data, "Platform writes")["items"])
    assert "record_proposal" in writes and "create_refund" in writes
    assert get_order(4512)["status"] == "refunded"


def test_run_stages_can_be_read_again_and_ids_are_safe(demo_on):
    run_id = client.post("/demo/message", json={"text": S1_TEXT}).json()["run_id"]
    again = client.get(f"/demo/runs/{run_id}")
    assert again.status_code == 200 and len(again.json()["stages"]) >= 5
    for bad in ("..%2F..%2Fconfig", "run_..", "abc", "run_x%2F..%2Fy", "run_does_not_exist"):
        assert client.get(f"/demo/runs/{bad}").status_code == 404, bad


def test_each_request_has_its_own_run_and_the_server_trace_comes_back(demo_on):
    before = trace.current_path()
    a = client.post("/demo/message", json={"text": S1_TEXT}).json()["run_id"]
    b = client.post("/demo/story/S0").json()["run_id"]
    assert a != b and trace.current_path() == before
    assert all(json.loads(x)["run_id"] == a for x in (before.parent / f"{a}.jsonl").read_text(encoding="utf-8").splitlines())


# --- stories -------------------------------------------------------------------

def test_s2_shows_one_send_back_then_approve_and_does_not_leak_into_s1(demo_on):
    original = pipeline.review
    s2 = client.post("/demo/story/S2").json()
    decisions = [i["text"] for i in stage(s2, "Coordinator")["items"] if i["text"].startswith("DECISION")]
    assert [d.split()[1] for d in decisions] == ["SEND_BACK", "APPROVE"]
    assert any("INJECTED ERROR" in i["text"] for i in stage(s2, "Agent")["items"])
    assert pipeline.review is original                                  # restored after the request
    s1 = client.post("/demo/story/S1").json()
    decisions = [i["text"] for i in stage(s1, "Coordinator")["items"] if i["text"].startswith("DECISION")]
    assert [d.split()[1] for d in decisions] == ["APPROVE"]             # no send-back: nothing leaked
    assert not any("INJECTED" in i["text"] for s in s1["stages"] for i in s["items"])


def test_stories_start_from_fresh_data(demo_on):
    for _ in range(2):   # S1 twice: the second one is approved too because the data is re-seeded
        assert client.post("/demo/story/S1").json()["decision"]["outcome"] == "approve"


def test_s0_is_an_info_answer(demo_on):
    data = client.post("/demo/story/S0").json()
    assert data["route"]["agent"] == "A" and data["decision"]["outcome"] == "info"
    assert "4510" in data["final_reply"]


def test_story_not_available_yet_does_not_crash(demo_on):
    r = client.post("/demo/story/S3")
    assert r.status_code == 200 and r.json()["error"] == "not available yet"
    r = client.post("/demo/notifier/run")
    assert r.status_code == 200 and r.json()["error"] == "not available yet"


# --- clock and reset ---------------------------------------------------------

def test_reset_puts_data_and_clock_back(demo_on):
    client.post("/demo/message", json={"text": S1_TEXT})
    assert client.post("/demo/clock/advance", json={"hours": 24}).json()["applied"][0]["status"] == "out_for_delivery"
    assert get_order(4512)["status"] == "refunded" and clock.now().isoformat() == "2026-10-10T09:00:00"
    r = client.post("/demo/reset").json()
    assert r["reset"] is True and r["clock"] == "2026-10-09T09:00:00"
    assert get_order(4512)["status"] == "stuck_at_depot" and get_order(4510)["status"] == "shipped"


def test_clock_routes(demo_on):
    assert client.post("/demo/clock/advance", json={"hours": -1}).status_code == 400
    assert client.post("/demo/clock/advance", json={"hours": 30}).status_code == 200
    assert client.post("/demo/clock/reset").json()["now"] == "2026-10-09T09:00:00"


# --- guards ------------------------------------------------------------------

def test_demo_routes_are_404_when_off(monkeypatch):
    monkeypatch.setitem(load_config()["server"], "demo_enabled", False)
    assert client.get("/demo").status_code == 404
    for path in ("/demo/message", "/demo/story/S1", "/demo/reset", "/demo/clock/reset", "/demo/notifier/run"):
        body = {"text": "hi"} if path == "/demo/message" else None
        assert client.post(path, json=body).status_code == 404, path
    assert client.post("/demo/clock/advance", json={"hours": 1}).status_code == 404
    assert client.get("/demo/runs/run_20261021_000000_000000").status_code == 404
    assert client.get("/clock").status_code == 200                      # normal read routes still work


def test_default_config_has_the_demo_off():
    from pathlib import Path
    import yaml
    config = yaml.safe_load((Path(__file__).resolve().parent.parent / "config.yaml").read_text(encoding="utf-8"))
    assert config["server"]["demo_enabled"] is False


def test_cross_site_post_is_refused(demo_on):
    evil = client.post("/demo/reset", headers={"Origin": "http://evil.example"})
    assert evil.status_code == 403
    same = client.post("/demo/reset", headers={"Origin": "http://testserver"})
    assert same.status_code == 200
    assert client.post("/demo/reset").status_code == 200                 # no Origin header (curl, tests): allowed


def test_busy_lock_gives_409(demo_on):
    assert demo.LOCK.acquire(blocking=False)
    try:
        assert client.post("/demo/message", json={"text": S1_TEXT}).status_code == 409
    finally:
        demo.LOCK.release()


def test_no_response_contains_a_key(demo_on, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_TESTSECRET1234567890")
    bodies = [client.post("/demo/message", json={"text": S1_TEXT}).text, client.post("/demo/story/S2").text,
              client.get("/demo").text, client.post("/demo/reset").text]

    def leaky(text, **kwargs):
        raise RuntimeError("provider said: invalid key gsk_TESTSECRET1234567890 / AIzaSyTESTSECRET123456")
    monkeypatch.setattr(pipeline, "handle", leaky)
    failed = client.post("/demo/message", json={"text": S1_TEXT})
    bodies.append(failed.text)
    assert failed.status_code == 200 and "error" in failed.json() and "[redacted]" in failed.text
    for body in bodies:
        assert "gsk_" not in body and "AIza" not in body


def test_page_has_the_buttons(demo_on):
    page = client.get("/demo").text
    for label in ("S0", "S1", "S2", "S4", "S3", "+24 h", "Send notifications", "Reset demo", "AI assistant"):
        assert label in page
