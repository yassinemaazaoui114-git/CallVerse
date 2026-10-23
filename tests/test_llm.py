"""The fallback rule of llm.chat(), tested with a FAKE OpenAI client (no API call, no key needed).

Rule: move to the next model on 429 / 404 / 5xx; do NOT move on 400 (that is our own bug).
"""

from types import SimpleNamespace

import openai
import pytest

# The openai SDK builds its errors from an HTTP response object. Recent SDK versions use the
# `httpx2` library for this, older ones `httpx`; both come installed with the SDK.
try:
    import httpx2 as httpx
except ImportError:
    import httpx

from callverse import llm

FAKE_CONFIG = {
    "providers": {"fake": {"base_url": "https://fake.example", "key_env": "FAKE_API_KEY"}},
    "models": {"agents": [{"provider": "fake", "model": "first"},
                          {"provider": "fake", "model": "second"}]},
}


def status_error(error_class, code):
    """Build the error the openai SDK raises for an HTTP status code."""
    response = httpx.Response(code, request=httpx.Request("POST", "https://fake.example"))
    return error_class("fake error", response=response, body=None)


def install_fake_client(monkeypatch, first_model_error):
    """Make llm.chat() use a fake client: model "first" raises the error, model "second" answers."""
    called = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, model, messages, **kwargs):
            called.append(model)
            if model == "first":
                raise first_model_error
            message = SimpleNamespace(content=f"answer from {model}", tool_calls=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)

    monkeypatch.setattr(llm, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(llm, "load_config", lambda: FAKE_CONFIG)
    monkeypatch.setenv("FAKE_API_KEY", "not-a-real-key")
    return called


@pytest.mark.parametrize("error_class, code", [
    (openai.RateLimitError, 429),
    (openai.NotFoundError, 404),
    (openai.InternalServerError, 500),
    (openai.InternalServerError, 503),
])
def test_falls_back_on_provider_errors(monkeypatch, error_class, code):
    called = install_fake_client(monkeypatch, status_error(error_class, code))

    reply = llm.chat("agents", [{"role": "user", "content": "hi"}])

    assert called == ["first", "second"]
    assert reply.content == "answer from second"


def test_does_not_fall_back_on_400(monkeypatch):
    called = install_fake_client(monkeypatch, status_error(openai.BadRequestError, 400))

    with pytest.raises(openai.BadRequestError):
        llm.chat("agents", [{"role": "user", "content": "hi"}])

    assert called == ["first"]  # the second model was never tried


# ---------- T07: rate limit with "retry-after" ----------

def rate_limit_error(retry_after: str):
    response = httpx.Response(429, headers={"retry-after": retry_after},
                              request=httpx.Request("POST", "https://fake.example"))
    return openai.RateLimitError("rate limit", response=response, body=None)


def install_rate_limited_client(monkeypatch, retry_after: str):
    """Model "first" answers 429 (with retry-after) the first time, then answers; "second" always answers."""
    called, waits = [], []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, model, messages, **kwargs):
            called.append(model)
            if model == "first" and called.count("first") == 1:
                raise rate_limit_error(retry_after)
            message = SimpleNamespace(content=f"answer from {model}", tool_calls=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)

    monkeypatch.setattr(llm, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(llm, "load_config", lambda: {**FAKE_CONFIG, "llm": {"max_retry_wait_s": 20}})
    monkeypatch.setattr(llm, "_sleep", waits.append)      # record the wait instead of sleeping
    monkeypatch.setenv("FAKE_API_KEY", "not-a-real-key")
    return called, waits


def test_short_retry_after_waits_and_retries_the_same_model(monkeypatch):
    called, waits = install_rate_limited_client(monkeypatch, "2")
    reply = llm.chat("agents", [{"role": "user", "content": "hi"}])
    assert waits == [2.0] and called == ["first", "first"]
    assert reply.content == "answer from first"


def test_long_retry_after_moves_to_the_next_model(monkeypatch):
    called, waits = install_rate_limited_client(monkeypatch, "60")
    reply = llm.chat("agents", [{"role": "user", "content": "hi"}])
    assert waits == [] and called == ["first", "second"]
    assert reply.content == "answer from second"


def test_forced_model_is_the_only_one_tried(monkeypatch):
    called = install_fake_client(monkeypatch, status_error(openai.RateLimitError, 429))
    monkeypatch.setenv("CALLVERSE_FORCE_AGENTS_MODEL", "second")
    assert llm.chat("agents", [{"role": "user", "content": "hi"}]).content == "answer from second"
    assert called == ["second"]


def test_tool_call_extras_kept_only_for_providers_that_need_them():
    messages = [{"role": "assistant", "content": "", "tool_calls": [
        {"id": "1", "type": "function", "function": {"name": "f", "arguments": "{}"}, "extra_content": {"x": 1}}]}]
    assert "extra_content" in llm.messages_for({"tool_call_extras": True}, messages)[0]["tool_calls"][0]
    assert "extra_content" not in llm.messages_for({}, messages)[0]["tool_calls"][0]


# ---------- T10: a model's broken tool call (Groq 400 "tool_use_failed") falls back ----------

def test_tool_use_failed_400_falls_back_but_other_400_does_not(monkeypatch):
    response = httpx.Response(400, request=httpx.Request("POST", "https://fake.example"))
    broken = openai.BadRequestError("tool call validation failed", response=response,
                                    body={"error": {"code": "tool_use_failed", "message": "bad tool name"}})
    called = install_fake_client(monkeypatch, broken)
    assert llm.chat("agents", [{"role": "user", "content": "hi"}]).content == "answer from second"
    assert called == ["first", "second"]


def test_foreign_tool_calls_get_a_placeholder_signature_for_gemini():
    messages = [{"role": "assistant", "content": "", "tool_calls": [
        {"id": "1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]}]
    fixed = llm.messages_for({"tool_call_extras": True}, messages)
    assert fixed[0]["tool_calls"][0]["extra_content"] == llm.FOREIGN_SIGNATURE
    assert "extra_content" not in messages[0]["tool_calls"][0]       # the original is not changed


# ---------- T10b: daily quota (429 "tokens per day") is detected and remembered ----------

def test_daily_limit_is_detected_and_remembered(monkeypatch):
    response = httpx.Response(429, request=httpx.Request("POST", "https://fake.example"))
    daily = openai.RateLimitError("Rate limit reached on tokens per day (TPD): Limit 200000", response=response, body=None)
    called = install_fake_client(monkeypatch, daily)
    monkeypatch.setattr(llm, "DAILY_LIMIT_HITS", [])
    assert llm.chat("agents", [{"role": "user", "content": "hi"}]).content == "answer from second"
    assert called == ["first", "second"] and llm.DAILY_LIMIT_HITS == ["fake/first"]


def test_per_minute_limit_is_not_daily():
    response = httpx.Response(429, request=httpx.Request("POST", "https://fake.example"))
    assert not llm.is_daily_limit(openai.RateLimitError("tokens per minute (TPM): Limit 8000", response=response, body=None))
    assert llm.is_daily_limit(openai.RateLimitError("You exceeded your current quota", response=response, body=None))
