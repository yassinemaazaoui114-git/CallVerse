"""The agent loop, tested with a FAKE LLM (no API call, no key needed)."""

from types import SimpleNamespace

from callverse.agents.agent_a import AgentA
from callverse.agents.base_agent import MAX_STEPS


def tool_call_reply(name, arguments, call_id="call_1"):
    """A fake model reply that asks for one tool, shaped like the openai SDK object."""
    tool_call = SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments))
    return SimpleNamespace(content=None, tool_calls=[tool_call])


def text_reply(text):
    """A fake model reply with a final text answer."""
    return SimpleNamespace(content=text, tool_calls=None)


def test_loop_stops_after_5_steps():
    calls = []

    def always_wants_a_tool(role_key, messages, tools=None):
        calls.append(role_key)
        return tool_call_reply("get_order", '{"order_id": 4512}')

    result = AgentA(chat_fn=always_wants_a_tool).run("Where is my order 4512?")

    assert len(calls) == MAX_STEPS == 5
    assert result["stopped_by"] == "max_steps"


def test_tool_result_then_final_answer():
    replies = iter([
        tool_call_reply("get_tracking", '{"order_id": 4512}'),
        text_reply("Your order 4512 is stuck at the depot and 6 days late."),
    ])
    result = AgentA(chat_fn=lambda role_key, messages, tools=None: next(replies)).run("Where is 4512?")

    assert result["stopped_by"] == "final_answer"
    assert result["tool_calls"][0]["result"]["days_late"] == 6
    assert result["handover"] is None


def test_refund_request_gives_handover_to_b():
    fake = lambda role_key, messages, tools=None: text_reply(
        "I will hand your request to the refund team. [HANDOVER: B]")
    result = AgentA(chat_fn=fake).run("I want my money back for 4512")

    assert result["handover"] == "B"
    assert "[HANDOVER" not in result["answer"]
