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
