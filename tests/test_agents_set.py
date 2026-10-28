"""T13: the switch to the LOCAL test models of the agents (CALLVERSE_AGENTS_SET=local). All offline.

- No env var: the agents chain is exactly the normal one (gpt-oss-120b -> gpt-oss-20b -> gemini-3.5-flash).
- Switch on: every "agents" call uses models.agents_local only (Ollama, no API).
- CALLVERSE_FORCE_AGENTS_MODEL still keeps one model alone, inside the chosen set. T13c: in the local set an
  unlisted name is accepted as an Ollama model (never an API model); in the default set it must be listed.
- The quota guard checks only the local models when the switch is on, and keeps the forced model.
"""

import pytest

from callverse import llm
from callverse.config import load_config
from scripts import quota_check


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("CALLVERSE_AGENTS_SET", raising=False)
    monkeypatch.delenv("CALLVERSE_FORCE_AGENTS_MODEL", raising=False)


def names(entries):
    return [(e["provider"], e["model"]) for e in entries]


def test_default_chain_is_unchanged():
    assert names(llm.models_for("agents", load_config())) == [
        ("groq", "openai/gpt-oss-120b"), ("groq", "openai/gpt-oss-20b"), ("google", "gemini-3.5-flash")]


def test_switch_on_uses_only_local_models(monkeypatch):
    monkeypatch.setenv("CALLVERSE_AGENTS_SET", "local")
    entries = llm.models_for("agents", load_config())
    assert entries and all(e["provider"] == "ollama" for e in entries)
    assert names(entries) == names(load_config()["models"]["agents_local"])


def test_force_picks_one_model_in_the_local_set(monkeypatch):
    monkeypatch.setenv("CALLVERSE_AGENTS_SET", "local")
    first = load_config()["models"]["agents_local"][0]["model"]
    monkeypatch.setenv("CALLVERSE_FORCE_AGENTS_MODEL", first)
    assert [e["model"] for e in llm.models_for("agents", load_config())] == [first]


def test_forcing_an_api_model_in_the_local_set_fails(monkeypatch):
    monkeypatch.setenv("CALLVERSE_AGENTS_SET", "local")
    monkeypatch.setenv("CALLVERSE_FORCE_AGENTS_MODEL", "openai/gpt-oss-120b")
    with pytest.raises(llm.AllModelsFailed):
        llm.models_for("agents", load_config())


def test_force_accepts_an_unlisted_ollama_name_in_the_local_set(monkeypatch):
    # T13c: e.g. a temporary Ollama copy for a benchmark; it gets the settings of the first local entry.
    monkeypatch.setenv("CALLVERSE_AGENTS_SET", "local")
    monkeypatch.setenv("CALLVERSE_FORCE_AGENTS_MODEL", "cv-test-copy")
    first = load_config()["models"]["agents_local"][0]
    assert llm.models_for("agents", load_config()) == [{**first, "model": "cv-test-copy"}]


def test_force_of_an_unlisted_name_still_fails_in_the_default_set(monkeypatch):
    monkeypatch.setenv("CALLVERSE_FORCE_AGENTS_MODEL", "cv-test-copy")
    with pytest.raises(llm.AllModelsFailed):
        llm.models_for("agents", load_config())


def test_other_roles_are_not_switched(monkeypatch):
    monkeypatch.setenv("CALLVERSE_AGENTS_SET", "local")
    cfg = load_config()
    assert llm.models_for("slm", cfg) == cfg["models"]["slm"]


def test_quota_guard_checks_only_local_models_and_keeps_the_forced_one(monkeypatch):
    called = []

    def fake_chat(role_key, messages, **kwargs):
        # The model the real chat() would use for this call.
        called.append([e["model"] for e in llm.models_for(role_key, load_config())])

    monkeypatch.setattr(quota_check.llm, "chat", fake_chat)
    monkeypatch.setattr(quota_check.trace, "log", lambda *a, **k: None)
    monkeypatch.setenv("CALLVERSE_AGENTS_SET", "local")
    local = [e["model"] for e in load_config()["models"]["agents_local"]]

    results = quota_check.check_models()
    assert [r["model"] for r in results] == local and called == [[m] for m in local]

    monkeypatch.setenv("CALLVERSE_FORCE_AGENTS_MODEL", local[-1])
    called.clear()
    results = quota_check.check_models()
    assert [r["model"] for r in results] == [local[-1]]
    assert quota_check.os.environ["CALLVERSE_FORCE_AGENTS_MODEL"] == local[-1]   # not removed


def test_quota_guard_default_set_is_unchanged(monkeypatch):
    monkeypatch.setattr(quota_check.llm, "chat", lambda *a, **k: None)
    monkeypatch.setattr(quota_check.trace, "log", lambda *a, **k: None)
    results = quota_check.check_models()
    assert [r["model"] for r in results] == ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "gemini-3.5-flash"]
    assert "CALLVERSE_FORCE_AGENTS_MODEL" not in quota_check.os.environ
