"""Web channel pipeline: order numbers in speech-to-text output, MOCK isolation, REAL mode with Agent A
and a FAKE LLM (no API call), and the identity guard."""

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


def trace_steps():
    return [json.loads(line) for line in trace.current_path().read_text(encoding="utf-8").splitlines()]


# ---------- MOCK ----------
def test_mock_is_labelled_and_reads_nothing():
    session = Session(id="s")
    reply = pipeline.handle_turn(session, "Hello, where is my order 4512?", mode="mock", chat_fn=no_llm)
    assert reply["mode"] == "mock" and reply["kind"] == "mock"
    assert reply["text"].startswith("Demo mode")
    assert "4512" in reply["text"]
    assert "stuck" not in reply["text"].lower()                 # no invented order status
    assert reply["tools_used"] == [] and reply["agent"] is None
    assert not [s for s in trace_steps() if s["step"] == "tool_call"]   # no database read at all


def test_mock_french():
    reply = pipeline.handle_turn(Session(id="s"), "Bonjour, où est ma commande 4512 ?", mode="mock")
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
    # The agent got the WAITING question, not the email, and the conversation so far as context.
    assert fake.calls[0][-1]["content"] == "Hello, where is my order 4512?"
    assert any(m["role"] == "assistant" for m in fake.calls[0][1:-1])


def test_real_email_and_question_in_one_message():
    session = Session(id="s")
    fake = scripted_llm(SimpleNamespace(content="Order 4512 is stuck at the depot.", tool_calls=None))
    reply = pipeline.handle_turn(session, "I'm sara@example.com, where is order 4512?", mode="real", chat_fn=fake)
    assert reply["kind"] == "agent" and session.verified_orders == {4512}


def test_real_blocks_an_answer_about_an_order_not_proved():
    session = Session(id="s", verified_user_id=1, verified_orders={4512})
    fake = scripted_llm(tool_call("get_order", {"order_id": 4510}),           # Youssef's order
                        SimpleNamespace(content="Order 4510 is shipped.", tool_calls=None))
    reply = pipeline.handle_turn(session, "And my other order?", mode="real", chat_fn=fake)
    assert reply["kind"] == "channel" and "verified" in reply["text"]
    assert "4510" not in reply["text"]
    assert any(s["step"] == "identity_block" for s in trace_steps())


def test_real_reports_llm_outage_without_falling_back_to_mock():
    def down(role_key, messages, tools=None):
        raise llm.AllModelsFailed("no model")
    session = Session(id="s", verified_user_id=1, verified_orders={4512})
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
    session = Session(id="s", verified_user_id=1, verified_orders={4512})
    reply = pipeline.handle_turn(session, "Where is order 4512?", mode="real", chat_fn=unauthorized)
    assert reply["kind"] == "channel" and reply["error"] == "agent_unavailable"


def test_real_handover_to_b_is_flagged_but_not_forwarded():
    session = Session(id="s", verified_user_id=1, verified_orders={4512})
    fake = scripted_llm(SimpleNamespace(content="I will pass your request to the refund team. [HANDOVER: B]",
                                        tool_calls=None))
    reply = pipeline.handle_turn(session, "I want my money back for 4512", mode="real", chat_fn=fake)
    assert reply["handover"] == "B" and "[HANDOVER" not in reply["text"]
    assert "not built yet" in reply["notice"]


def test_history_is_kept_and_bounded():
    session = Session(id="s")
    for i in range(15):
        pipeline.handle_turn(session, f"message {i}", mode="mock")
    assert len(session.history) == 20                       # max_history_turns = 10 pairs
    assert session.history[-2] == {"role": "user", "content": "message 14"}
    assert session.turns == 15
