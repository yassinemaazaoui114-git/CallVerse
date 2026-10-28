"""T13c tests: the "claims a proposal" safety net in pipeline.run_agent_with_coordinator. No API, no Ollama.

The agent's answer SAYS it proposes something ("I propose ...", "sent for checking") but it called no proposal
tool: the same agent runs once more with a short note. A claim WITH a proposal tool call, or no claim at all,
runs no retry. The net never writes anything itself: only a real proposal tool call reaches the Coordinator.
The net is OFF by default (config.yaml pipeline.proposal_claim_retry: false); the tests below turn it on.
"""

import json
from types import SimpleNamespace

import pytest

from callverse import pipeline, trace
from callverse.config import load_config


def text_reply(text):
    return SimpleNamespace(content=text, tool_calls=None)


def tool_call_reply(name, arguments):
    tc = SimpleNamespace(id="c1", function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))
    return SimpleNamespace(content=None, tool_calls=[tc])


def steps():
    return [json.loads(x)["step"] for x in trace.current_path().read_text(encoding="utf-8").splitlines()]


def ticket(text, order_id=4510):
    return {"ticket_id": "T-C", "text": text, "order_id": order_id, "main_reason": "order_status",
            "priority_label": "low", "style": {"formality": "neutral", "length": "short", "shouting": False},
            "emotion": {"label": "neutral"}, "sentiment": {"label": "neutral"}}


def fake_agent(first_tool, final_texts):
    """A fake LLM: each agent run calls first_tool once, then answers with the next text of final_texts."""
    runs = []

    def agent(role_key, messages, tools=None):
        last = messages[-1]
        if last["role"] == "user":
            runs.append(last["content"])
            return tool_call_reply(*first_tool)
        return text_reply(final_texts[min(len(runs), len(final_texts)) - 1])

    return agent, runs


@pytest.fixture
def net_on(monkeypatch):
    """Turn the safety net on for one test (the cached config is put back after the test)."""
    monkeypatch.setitem(load_config(), "pipeline", {"proposal_claim_retry": True})


def test_net_is_off_by_default_so_a_claim_runs_no_retry():
    assert load_config()["pipeline"]["proposal_claim_retry"] is False
    agent, runs = fake_agent(("get_tracking", {"order_id": 4510}), ["I propose a notification."])
    pipeline.handle_ticket(ticket("Tell me when 4510 arrives"), chat_fn=agent)
    assert len(runs) == 1 and "proposal_claim_retry" not in steps()


def test_claim_without_a_proposal_tool_runs_the_agent_once_more(net_on):
    agent, runs = fake_agent(("get_tracking", {"order_id": 4510}),
                             ["I propose to notify you when it arrives. This is sent for checking.",
                              "Order 4510 is shipped and on time."])
    out = pipeline.handle_ticket(ticket("Tell me when 4510 arrives"), chat_fn=agent)
    assert len(runs) == 2 and "no proposal tool was called" in runs[1]
    assert steps().count("proposal_claim_retry") == 1 and out["proposal"] is None


def test_at_most_one_claim_retry_even_if_the_second_answer_claims_again(net_on):
    agent, runs = fake_agent(("get_tracking", {"order_id": 4510}), ["I propose a notification."])
    pipeline.handle_ticket(ticket("Tell me when 4510 arrives"), chat_fn=agent)
    assert len(runs) == 2 and steps().count("proposal_claim_retry") == 1


def test_claim_with_a_proposal_tool_call_runs_no_retry(net_on):
    # The tool is called (here with a wrong event, so it is refused): no retry, the net only looks at the call.
    agent, runs = fake_agent(("propose_subscription", {"order_id": 4510, "event": "lunch"}),
                             ["I propose a notification. This is sent for checking."])
    pipeline.handle_ticket(ticket("Tell me when 4510 arrives"), chat_fn=agent)
    assert len(runs) == 1 and "proposal_claim_retry" not in steps()


def test_no_claim_runs_no_retry(net_on):
    agent, runs = fake_agent(("get_tracking", {"order_id": 4510}), ["Order 4510 is shipped and on time."])
    pipeline.handle_ticket(ticket("Where is 4510?"), chat_fn=agent)
    assert len(runs) == 1 and "proposal_claim_retry" not in steps()


def test_claim_phrases():
    assert pipeline.claims_proposal("I can propose a full refund under the rule.")
    assert pipeline.claims_proposal("Your request was submitted to the team for review.")
    assert pipeline.claims_proposal("A refund proposal was made.")
    assert not pipeline.claims_proposal("Order 4510 is shipped and on time.")
