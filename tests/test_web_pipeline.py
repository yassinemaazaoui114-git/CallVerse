"""Web channel pipeline: order numbers in speech-to-text output, the identity gate, MOCK isolation, and
REAL mode through the unified workflow with Agent A and a FAKE LLM (no API call).

Intake is replaced here by `fake_intake` (keyword rules, instant) so these tests stay fast and only test
the channel; tests/test_integration_workflow.py runs the REAL Intake models."""

import json
from types import SimpleNamespace

import pytest

from callverse import llm, trace
from callverse.web import pipeline
from callverse.web.sessions import Session


# ---------- reading order numbers and language ----------
@pytest.mark.parametrize("text, expected", [
    ("Hello, where is my order 4512?", [4512]),
    ("Hello, where is my order 4,512?", [4512]),          # Whisper, English
    ("Bonjour, où est ma commande 4.512 ?", [4512]),       # Whisper, French
    ("ma commande 4 512", [4512]),
    ("where is my order 4, 5, 1, 2?", [4512]),            # number read digit by digit
    ("order 45 12 please", [4512]),
    ("it was 2 or 3 days ago", []),                        # too few digits: not an order number
    ("between 2026-10-03 and 10-09", []),
    ("order #4510 and order 4512", [4510, 4512]),
    ("I paid 59.90 TND", []),
    ("I paid 1500 TND for it", []),
    ("promised on 2026-10-03", []),
    ("no number here", []),
])
def test_find_order_ids(text, expected):
    assert pipeline.find_order_ids(text) == expected


def test_find_email_and_language():
    assert pipeline.find_email("It's Sara@Example.com thanks") == "sara@example.com"
    assert pipeline.find_email("no email") is None
    assert pipeline.guess_language("Bonjour, où est ma commande 4512 ?") == "fr"
    assert pipeline.guess_language("Hello, where is my order 4512?") == "en"


# ---------- fake LLM for Agent A ----------
def tool_call(name, args, call_id="call_1"):
    return SimpleNamespace(content=None, tool_calls=[
        SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(args)))])


def scripted_llm(*replies):
    """A fake llm.chat that returns the given replies in order and records each call."""
    queue = list(replies)
    calls = []

    def chat(role_key, messages, tools=None):
        calls.append(list(messages))   # a copy: the agent loop keeps appending to the same list
        return queue.pop(0)
    chat.calls = calls
    return chat


def no_llm(role_key, messages, tools=None):
    raise AssertionError("the LLM must not be called")


def fake_intake_process(text, use_llm=True, chat_fn=None):
    """A stand-in for intake.process with the same ticket shape (TEST ONLY)."""
    t = text.lower()
    reasons = [r for r, words in (("refund_request", ("refund", "money back")), ("late_delivery", ("late",)),
                                  ("order_status", ("where", "status"))) if any(w in t for w in words)] or ["other"]
    ids = pipeline.find_order_ids(text)
    return {"ticket_id": "T-test", "order_id": ids[0] if ids else None,
            "reasons": [{"reason": r, "score": 0.8, "sentence": text} for r in reasons], "main_reason": reasons[0],
            "emotion": {"label": "neutral", "score": 0.9}, "sentiment": {"label": "neutral", "score": 0.9},
            "priority_label": "medium", "priority_score": 0.5, "needs_llm": False}


@pytest.fixture(autouse=True)
def fake_intake(monkeypatch):
    from callverse.intake import intake
    monkeypatch.setattr(intake, "process", fake_intake_process)


def verified(session_id="s"):
    """A session whose customer already proved order 4512 (Sara, user 1)."""
    return Session(id=session_id, verified_user_id=1, verified_orders={4512})


def trace_steps():
    return [json.loads(line) for line in trace.current_path().read_text(encoding="utf-8").splitlines()]


# ---------- MOCK ----------
def test_mock_still_asks_for_identity_first():
    session = Session(id="s")
    reply = pipeline.handle_turn(session, "Hello, where is my order 4512?", mode="mock", chat_fn=no_llm)
    assert reply["kind"] == "channel" and "email" in reply["text"]


def test_mock_is_labelled_and_the_agent_is_not_called():
    session = verified()
    reply = pipeline.handle_turn(session, "Hello, where is my order 4512?", mode="mock", chat_fn=no_llm)
    assert reply["mode"] == "mock" and reply["kind"] == "mock"
    assert reply["text"].startswith("Demo mode") and "Agent A" in reply["text"]
    assert "stuck" not in reply["text"].lower() and "6" not in reply["text"]   # no order facts at all
    assert reply["tools_used"] == [] and reply["agent"] is None
    assert not [s for s in trace_steps() if s["actor"] == "registry"]          # no agent tool call
    statuses = {s["name"]: s["status"] for s in reply["steps"]}
    assert statuses["agent"] == "mock" and statuses["intake"] == "real"


def test_mock_french():
    reply = pipeline.handle_turn(verified(), "Bonjour, où est ma commande 4512 ?", lang="fr", mode="mock")
    assert reply["language"] == "fr" and reply["text"].startswith("Mode démo")


# ---------- REAL: identity guard ----------
def test_real_asks_for_email_before_reading_the_order():
    session = Session(id="s")
    reply = pipeline.handle_turn(session, "Hello, where is my order 4512?", mode="real", chat_fn=no_llm)
    assert reply["kind"] == "channel" and "email" in reply["text"]
    assert session.pending_orders == [4512] and not session.verified_orders


@pytest.mark.parametrize("email", ["nobody@example.com", "youssef@example.com"])   # unknown / another client
def test_real_wrong_email_is_refused(email):
    session = Session(id="s")
    pipeline.handle_turn(session, "Where is my order 4512?", mode="real", chat_fn=no_llm)
    reply = pipeline.handle_turn(session, email, mode="real", chat_fn=no_llm)
    assert reply["kind"] == "channel" and "does not match" in reply["text"]
    assert not session.verified_orders


def test_real_answer_after_email_uses_agent_a_and_the_tools():
    session = Session(id="s")
    pipeline.handle_turn(session, "Hello, where is my order 4512?", mode="real", chat_fn=no_llm)
    fake = scripted_llm(tool_call("get_tracking", {"order_id": 4512}),
                        SimpleNamespace(content="Your order 4512 is stuck at the depot and 6 days late.",
                                        tool_calls=None))
    reply = pipeline.handle_turn(session, "sara@example.com", mode="real", chat_fn=fake)

    assert reply["kind"] == "agent" and reply["agent"] == "A"
    assert reply["tools_used"] == ["get_tracking"]
    assert reply["text"] == "Your order 4512 is stuck at the depot and 6 days late."
    assert session.verified_orders == {4512}
    # The agent got the WAITING question (+ the Intake note), not the email, and the conversation so far.
    assert fake.calls[0][-1]["content"].startswith("Hello, where is my order 4512?")
    assert "Intake note: order 4512" in fake.calls[0][-1]["content"]
    assert [s["name"] for s in reply["steps"]] == ["intake", "router", "agent", "coordinator", "response"]
    assert any(m["role"] == "assistant" for m in fake.calls[0][1:-1])


def test_real_email_and_question_in_one_message():
    session = Session(id="s")
    fake = scripted_llm(SimpleNamespace(content="Order 4512 is stuck at the depot.", tool_calls=None))
    reply = pipeline.handle_turn(session, "I'm sara@example.com, where is order 4512?", mode="real", chat_fn=fake)
    assert reply["kind"] == "agent" and session.verified_orders == {4512}


def test_real_blocks_an_answer_about_an_order_not_proved():
    session = verified()
    fake = scripted_llm(tool_call("get_order", {"order_id": 4510}),           # Youssef's order
                        SimpleNamespace(content="Order 4510 is shipped.", tool_calls=None))
    reply = pipeline.handle_turn(session, "And my other order?", mode="real", chat_fn=fake)
    assert reply["kind"] == "channel" and "verified" in reply["text"]
    assert "4510" not in reply["text"]
    assert any(s["step"] == "identity_block" for s in trace_steps())


def test_real_reports_llm_outage_without_falling_back_to_mock():
    def down(role_key, messages, tools=None):
        raise llm.AllModelsFailed("no model")
    session = verified()
    reply = pipeline.handle_turn(session, "Where is order 4512?", mode="real", chat_fn=down)
    assert reply["mode"] == "real" and reply["kind"] == "channel"
    assert "unavailable" in reply["text"] and reply["error"] == "agent_unavailable"


def test_real_wrong_api_key_gives_a_clear_message():
    import openai
    try:
        import httpx2 as httpx
    except ImportError:
        import httpx

    def unauthorized(role_key, messages, tools=None):
        response = httpx.Response(401, request=httpx.Request("POST", "https://fake"))
        raise openai.AuthenticationError("bad key", response=response, body=None)
    session = verified()
    reply = pipeline.handle_turn(session, "Where is order 4512?", mode="real", chat_fn=unauthorized)
    assert reply["kind"] == "channel" and reply["error"] == "agent_unavailable"


def test_real_handover_from_a_to_b_is_recorded_not_decided():
    fake = scripted_llm(SimpleNamespace(content="I will pass your request to the refund team. [HANDOVER: B]",
                                        tool_calls=None))
    reply = pipeline.handle_turn(verified(), "Where is order 4512? Is it delivered?", mode="real", chat_fn=fake)
    assert reply["kind"] == "handover" and reply["handover"] == "B"
    assert reply["text"] == "Your request is passed to our refund team."
    assert {s["name"]: s["status"] for s in reply["steps"]}["agent_b"] == "not built"


def test_refund_request_is_routed_to_b_without_calling_agent_a():
    reply = pipeline.handle_turn(verified(), "I want my money back for 4512", mode="real", chat_fn=no_llm)
    assert reply["route"]["agent"] == "B" and reply["kind"] == "handover"


def test_history_is_kept_and_bounded():
    session = Session(id="s")
    for i in range(15):
        pipeline.handle_turn(session, f"message {i}", mode="mock")
    assert len(session.history) == 20                       # max_history_turns = 10 pairs
    assert session.history[-2] == {"role": "user", "content": "message 14"}
    assert session.turns == 15
