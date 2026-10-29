"""T16: Agent B has its own model list (models.agent_b, Groq), so it can stay on the API while Intake + Agent A
run locally. All offline: a fake LLM records which role each call asks for; no API, no Ollama.

- Agent B's turns ask role "agent_b"; its "ask Agent A" sub-call too; Agent A's own turns keep "agents".
- Switches: none / CALLVERSE_AGENTS_SET=local / + CALLVERSE_AGENT_B_SET=local / CALLVERSE_FORCE_AGENT_B_MODEL.
- B's list never has a Gemini entry; agent_b_local is the same list as agents_local.
- Live check pause: 5 s while any agent role is on the API, 0 s only when both are local.
"""

import json
from types import SimpleNamespace

import pytest

from callverse import llm
from callverse.agents import ask
from callverse.agents.agent_a import AgentA
from callverse.agents.agent_b import AgentB
from callverse.config import load_config
from scripts import run_live_check as live

SWITCHES = ("CALLVERSE_AGENTS_SET", "CALLVERSE_AGENT_B_SET",
            "CALLVERSE_FORCE_AGENTS_MODEL", "CALLVERSE_FORCE_AGENT_B_MODEL")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in SWITCHES:
        monkeypatch.delenv(name, raising=False)


def text_reply(text):
    return SimpleNamespace(content=text, tool_calls=None)


def ask_a_reply():
    args = json.dumps({"agent": "A", "question": "Is order 4512 late?"})
    tc = SimpleNamespace(id="c1", function=SimpleNamespace(name="ask_agent", arguments=args))
    return SimpleNamespace(content=None, tool_calls=[tc])


def recording_chat(replies):
    """A fake llm.chat: gives the replies in order and records the role of every call."""
    roles, queue = [], list(replies)

    def chat(role_key, messages, tools=None, **kwargs):
        roles.append(role_key)
        return queue.pop(0)
    return chat, roles


def names(entries):
    return [(e["provider"], e["model"]) for e in entries]


# ---------- who asks which role ----------

def test_agent_b_turn_asks_role_agent_b():
    chat, roles = recording_chat([text_reply("No refund applies to this order.")])
    AgentB(chat_fn=chat).run("I want a refund for order 4512")
    assert roles == ["agent_b"]


def test_agent_b_sub_call_to_agent_a_asks_role_agent_b():
    # B asks A (tool ask_agent) -> A answers -> B answers. All three calls on B's models.
    chat, roles = recording_chat([ask_a_reply(), text_reply("It is late."), text_reply("Done.")])
    result = AgentB(chat_fn=chat).run("Refund for order 4512 please")
    assert [c["tool"] for c in result["tool_calls"]] == ["ask_agent"]
    assert roles == ["agent_b", "agent_b", "agent_b"]


def test_ask_agent_alone_uses_the_asker_role():
    chat, roles = recording_chat([text_reply("It is late.")])
    ask.ask_agent("A", "Is order 4512 late?", chat_fn=chat)
    assert roles == ["agent_b"]


def test_agent_a_own_turn_keeps_role_agents():
    chat, roles = recording_chat([text_reply("Your order is on its way.")])
    AgentA(chat_fn=chat).run("Where is order 4510?")
    assert roles == ["agents"]
    assert AgentA.role_key == "agents"     # the sub-call changed only its own instance


# ---------- which list each switch combination picks ----------

def test_no_switch_is_todays_behaviour():
    cfg = load_config()
    assert names(llm.models_for("agents", cfg)) == [
        ("groq", "openai/gpt-oss-120b"), ("groq", "openai/gpt-oss-20b"), ("google", "gemini-3.5-flash")]
    assert names(llm.models_for("agent_b", cfg)) == [("groq", "openai/gpt-oss-120b"), ("groq", "openai/gpt-oss-20b")]


def test_agents_local_moves_a_but_not_b(monkeypatch):
    monkeypatch.setenv("CALLVERSE_AGENTS_SET", "local")
    cfg = load_config()
    assert all(e["provider"] == "ollama" for e in llm.models_for("agents", cfg))
    assert names(llm.models_for("agent_b", cfg)) == [("groq", "openai/gpt-oss-120b"), ("groq", "openai/gpt-oss-20b")]


def test_both_local(monkeypatch):
    monkeypatch.setenv("CALLVERSE_AGENTS_SET", "local")
    monkeypatch.setenv("CALLVERSE_AGENT_B_SET", "local")
    cfg = load_config()
    assert names(llm.models_for("agent_b", cfg)) == names(cfg["models"]["agents_local"])
    assert all(e["provider"] == "ollama" for e in llm.models_for("agent_b", cfg))


def test_force_b_model_and_force_agents_does_not_touch_b(monkeypatch):
    cfg = load_config()
    monkeypatch.setenv("CALLVERSE_FORCE_AGENT_B_MODEL", "openai/gpt-oss-20b")
    assert names(llm.models_for("agent_b", cfg)) == [("groq", "openai/gpt-oss-20b")]
    assert len(llm.models_for("agents", cfg)) == 3                    # A not affected
    monkeypatch.delenv("CALLVERSE_FORCE_AGENT_B_MODEL")
    monkeypatch.setenv("CALLVERSE_FORCE_AGENTS_MODEL", "gemini-3.5-flash")
    assert names(llm.models_for("agents", cfg)) == [("google", "gemini-3.5-flash")]
    assert len(llm.models_for("agent_b", cfg)) == 2                   # B not affected


def test_agent_b_lists_never_have_gemini():
    models = load_config()["models"]
    for key in ("agent_b", "agent_b_local"):
        assert all(e["provider"] != "google" for e in models[key]), key


def test_agent_b_local_is_the_same_list_as_agents_local():
    models = load_config()["models"]
    assert models["agent_b_local"] == models["agents_local"]


# ---------- live check pause ----------

@pytest.mark.parametrize("agents_local, b_local, pause", [
    (False, False, 5), (True, False, 5), (False, True, 5), (True, True, 0)])
def test_pause_only_when_both_roles_are_local(monkeypatch, agents_local, b_local, pause):
    if agents_local:
        monkeypatch.setenv("CALLVERSE_AGENTS_SET", "local")
    if b_local:
        monkeypatch.setenv("CALLVERSE_AGENT_B_SET", "local")
    assert live.pause_seconds() == pause
