"""The unified workflow with the REAL Intake models (M3 + M4), Yassine's T04 router and the real platform data;
only the LLM is a fake (no API call). Also: the team's missing components plug in when they exist."""

import json
import sys
import types
from types import SimpleNamespace

import pytest

pytest.importorskip("sentence_transformers")

from callverse import trace  # noqa: E402
from callverse.integration import components  # noqa: E402
from callverse.web import pipeline  # noqa: E402
from callverse.web.sessions import Session  # noqa: E402


def text_reply(text):
    return SimpleNamespace(content=text, tool_calls=None)


def tool_call(name, args):
    return SimpleNamespace(content=None, tool_calls=[
        SimpleNamespace(id="c1", function=SimpleNamespace(name=name, arguments=json.dumps(args)))])


INTAKE_PROMPT_START = "You sort customer messages"   # Intake's M2 fallback (callverse/intake/llm_fallback.py)


def intake_fallback(messages):
    """Intake asks M2 only for unclear messages; the fake answers like the real model would: reason 'other'."""
    if messages and messages[0]["content"].startswith(INTAKE_PROMPT_START):
        return text_reply('{"reasons": ["other"], "order_id": null}')
    return None


def scripted(*replies):
    """Fake LLM for the AGENT: returns the replies in order (Intake's fallback is answered separately)."""
    queue, calls = list(replies), []

    def chat(role_key, messages, tools=None):
        if (answer := intake_fallback(messages)) is not None:
            return answer
        calls.append(list(messages))
        return queue.pop(0)
    chat.calls = calls
    return chat


def no_llm(role_key, messages, tools=None):
    """No AGENT call allowed (Intake's fallback may still run)."""
    if (answer := intake_fallback(messages)) is not None:
        return answer
    raise AssertionError("the agent LLM must not be called")


def statuses(reply):
    return {s["name"]: s["status"] for s in reply["steps"]}


# ---------- the router is Yassine's T04 router ----------
def test_routing_uses_the_t04_router():
    session = Session(id="s", verified_user_id=1, verified_orders={4512})
    pipeline.handle_turn(session, "Order 4512 is a week late. I want my money back.", mode="real", chat_fn=no_llm)
    steps = [json.loads(line) for line in trace.current_path().read_text(encoding="utf-8").splitlines()]
    routes = [s for s in steps if s["step"] == "route"]
    assert routes and routes[-1]["actor"] == "router"                   # callverse/queues/router.py traced it
    assert routes[-1]["data"]["agent"] == "B"
    assert components.status()["router"] == "built"


# ---------- the whole chain with the real Intake ----------
def test_status_question_goes_through_intake_router_and_agent_a():
    session = Session(id="s", verified_user_id=1, verified_orders={4512})
    fake = scripted(tool_call("get_tracking", {"order_id": 4512}),
                    text_reply("Your order 4512 is stuck at the depot and 6 days late."))
    reply = pipeline.handle_turn(session, "Hi, where is my order 4512?", mode="real", chat_fn=fake)

    assert reply["route"]["agent"] == "A" and reply["agent"] == "A" and reply["tools_used"] == ["get_tracking"]
    assert reply["ticket"]["priority"] in ("high", "medium", "low") and reply["ticket"]["reasons"]
    assert statuses(reply) == {"intake": "real", "router": "real", "agent": "real",
                               "coordinator": "not built", "response": "not built"}
    assert "6 days late" in reply["text"]


def test_late_and_refund_goes_to_b_and_is_recorded_t04_check():
    session = Session(id="s", verified_user_id=1, verified_orders={4512})
    reply = pipeline.handle_turn(session, "Order 4512 is a week late. I want my money back.", mode="real",
                                 chat_fn=no_llm)
    assert "refund_request" in reply["ticket"]["reasons"]
    assert reply["route"] == {"agent": "B", "layer": "L1", "reason": "refund_request",
                              "priority_label": reply["ticket"]["priority"]}
    assert reply["kind"] == "handover" and reply["handover"] == "B"
    assert statuses(reply)["agent_b"] == "not built"


def test_multi_turn_conversation_keeps_context():
    session = Session(id="s")
    first = pipeline.handle_turn(session, "Hello, where is my order 4512?", mode="real", chat_fn=no_llm)
    assert first["kind"] == "channel"                                    # identity first
    fake = scripted(tool_call("get_tracking", {"order_id": 4512}),
                    text_reply("Your order 4512 is stuck at the depot and 6 days late."),
                    tool_call("get_order", {"order_id": 4512}),
                    text_reply("It was promised for 2026-10-03."))
    second = pipeline.handle_turn(session, "sara@example.com", mode="real", chat_fn=fake)
    assert second["kind"] == "agent"
    third = pipeline.handle_turn(session, "And when was it promised?", mode="real", chat_fn=fake)
    assert third["kind"] == "agent" and "2026-10-03" in third["text"]
    # The agent saw the earlier turns as context in the third turn.
    contents = [m.get("content") or "" for m in fake.calls[2]]
    assert any("stuck at the depot" in c for c in contents)
    assert len(session.history) == 6


def test_mock_mode_runs_intake_and_router_for_real_but_not_the_agent():
    session = Session(id="s", verified_user_id=1, verified_orders={4512})
    reply = pipeline.handle_turn(session, "Hi, where is my order 4512?", mode="mock", chat_fn=no_llm)
    assert reply["kind"] == "mock" and statuses(reply)["intake"] == "real" and statuses(reply)["agent"] == "mock"
    assert reply["route"]["agent"] == "A"


# ---------- the team's components plug in when they exist ----------
def install(monkeypatch, module_name, **attrs):
    module = types.ModuleType(module_name)
    for k, v in attrs.items():
        setattr(module, k, v)
    monkeypatch.setitem(sys.modules, module_name, module)


class ProposingAgent:
    """A fake agent that proposes an action (what Agent B will do)."""

    def __init__(self, chat_fn=None):
        pass

    def run(self, text, history=None):
        return {"answer": "I propose a refund.", "tool_calls": [], "stopped_by": "final_answer",
                "proposal": {"action": "refund", "params": {"order_id": 4512, "amount": 59.90}}}


def test_a_proposal_is_never_executed_without_a_coordinator(monkeypatch):
    install(monkeypatch, "callverse.agents.agent_b", AgentB=ProposingAgent)
    session = Session(id="s", verified_user_id=1, verified_orders={4512})
    reply = pipeline.handle_turn(session, "I want my money back for order 4512", mode="real", chat_fn=no_llm)
    assert reply["kind"] == "channel" and "I propose" not in reply["text"]      # the proposal is not shown as done
    assert "review" in reply["text"] and statuses(reply)["coordinator"] == "not built"
    from callverse.tools.shopnova_tools import get_refunds
    assert get_refunds(4512)["refunds"] == []                            # nothing was written


def test_coordinator_and_slm_are_used_when_built(monkeypatch):
    install(monkeypatch, "callverse.agents.agent_b", AgentB=ProposingAgent)
    install(monkeypatch, "callverse.coordinator.coordinator",
            review=lambda proposal: {"outcome": "ask_user", "order_id": 4512, "facts": {}, "next_step": "Confirm."})
    install(monkeypatch, "callverse.slm.writer",
            write_reply=lambda decision, history=None: {"reply": "Please confirm the refund.", "used_template": False})
    session = Session(id="s", verified_user_id=1, verified_orders={4512})
    reply = pipeline.handle_turn(session, "I want my money back for order 4512", mode="real", chat_fn=no_llm)
    assert statuses(reply)["coordinator"] == "real" and statuses(reply)["response"] == "real"
    assert reply["text"] == "Please confirm the refund."


def test_a_broken_component_is_not_hidden(monkeypatch):
    """A module that exists but fails to import must raise, not silently count as 'not built'."""
    def broken():
        raise ModuleNotFoundError("No module named 'numpyy'", name="numpyy")
    monkeypatch.setattr(components.importlib, "import_module", lambda name: broken())
    with pytest.raises(ModuleNotFoundError):
        components.get("router")


# ---------- voice end to end: Piper -> Whisper -> gate -> Intake -> Router -> Agent A -> Piper ----------
def test_voice_turn_end_to_end_with_real_models(monkeypatch):
    pytest.importorskip("fastapi")
    from callverse.web.models import piper_dir
    if not (piper_dir() / "en_GB-cori-medium.onnx").exists():
        pytest.skip("speech models not installed")
    from fastapi.testclient import TestClient

    from callverse import llm
    from callverse.web import app as web
    from callverse.web.sessions import RateLimiter
    from tests.test_web_speech import steady_clip

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(pipeline, "resolve_mode", lambda: "real")
    replies = [tool_call("get_tracking", {"order_id": 4512}),
               text_reply("Your order 4512 is stuck at the depot and is 6 days late.")]
    monkeypatch.setattr(llm, "chat", lambda role_key, messages, tools=None: replies.pop(0))
    for name in ("per_session", "per_ip", "everyone", "new_sessions_per_ip"):
        monkeypatch.setattr(web, name, RateLimiter(100, 600))
    client = TestClient(web.app)

    sid = client.post("/api/session").json()["session_id"]
    first = client.post("/api/turn/audio", data={"session_id": sid},
                        files={"audio": ("q.wav", steady_clip("Hello, where is my order 4512?"), "audio/wav")}).json()
    assert pipeline.find_order_ids(first["transcript"]["text"]) == [4512]
    assert first["reply"]["kind"] == "channel" and first["audio"]["voice"] == "en_GB-cori-medium"

    second = client.post("/api/turn/text", json={"session_id": sid, "text": "sara@example.com"}).json()
    assert second["reply"]["kind"] == "agent" and second["route"]["agent"] == "A"
    assert {s["name"]: s["status"] for s in second["steps"]}["intake"] == "real"
    assert second["audio"]["seconds"] > 1
    assert client.get(second["audio"]["url"]).headers["content-type"] == "audio/wav"
