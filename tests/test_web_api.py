"""Web channel HTTP API, with FastAPI's TestClient. Speech models are replaced by fakes here (fast, no
download); test_web_speech.py and test_web_browser.py use the real ones."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")   # voice dependencies: pip install -r requirements-voice.txt
pytest.importorskip("av")

from fastapi.testclient import TestClient  # noqa: E402

from callverse import llm  # noqa: E402
from callverse.web import app as web  # noqa: E402
from callverse.web import pipeline, stt, tts  # noqa: E402
from callverse.web.sessions import RateLimiter  # noqa: E402
from tests.test_web_pipeline import fake_intake_process  # noqa: E402
from tests.test_web_speech import make_wav  # noqa: E402

FAKE_WAV = make_wav(0.5, rate=8000)


@pytest.fixture
def client(monkeypatch):
    """A client in MOCK mode with fake speech services, a fake Intake (fast) and fresh rate limits."""
    from callverse.intake import intake
    monkeypatch.setattr(intake, "process", fake_intake_process)
    monkeypatch.setattr(pipeline, "resolve_mode", lambda: "mock")
    monkeypatch.setattr(stt, "transcribe", lambda data, fmt, mime, language=None:
                        {"text": "Hello, where is my order 4512?", "language": "en",
                         "provider": "fake", "seconds": 0.01})
    monkeypatch.setattr(tts, "synthesize", lambda text, language=None:
                        {"wav": FAKE_WAV, "voice": "fake-voice", "seconds": 0.5, "synthesis_seconds": 0.01,
                         "spoken_text": tts.speech_text(text)})
    for name, limit in (("per_session", 30), ("per_ip", 120), ("everyone", 600), ("new_sessions_per_ip", 30)):
        monkeypatch.setattr(web, name, RateLimiter(limit, 600))
    return TestClient(web.app)


def session_id(client) -> str:
    return client.post("/api/session").json()["session_id"]


def test_page_and_security_headers(client):
    page = client.get("/")
    assert page.status_code == 200 and "CallVerse" in page.text
    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["permissions-policy"].startswith("microphone=(self)")
    assert page.headers["x-frame-options"] == "DENY"
    for asset in ("/static/app.js", "/static/style.css"):
        assert client.get(asset).status_code == 200


def test_no_admin_write_or_docs_routes(client):
    for method, path in [("get", "/docs"), ("get", "/openapi.json"), ("post", "/admin/reset"),
                         ("post", "/coordinator/refunds"), ("get", "/traces/recent"), ("get", "/orders/4512"),
                         ("post", "/tools/get_order")]:
        assert getattr(client, method)(path).status_code in (404, 405), path


def test_no_secret_in_browser_files():
    for f in (Path(web.STATIC)).iterdir():
        text = f.read_text(encoding="utf-8")
        assert "GROQ_API_KEY" not in text and "gsk_" not in text and "api_key" not in text.lower()


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["mode"] == "mock" and body["limits"]["max_audio_seconds"] == 30
    assert body["components"] == {"intake": "built", "agent_a": "built", "router": "built",
                                  "coordinator": "not built", "slm": "not built", "agent_b": "not built"}


def test_text_turn_with_audio_matching_the_text(client):
    sid = session_id(client)
    body = client.post("/api/turn/text", json={"session_id": sid, "text": "Hello, can you help me?"}).json()
    assert body["mode"] == "mock" and body["reply"]["kind"] == "mock"
    assert body["route"]["agent"] == "A" and body["ticket"]["reasons"] == ["other"]
    assert [s["status"] for s in body["steps"]] == ["real", "real", "mock", "not built", "not built"]
    assert body["text_sha256"] == hashlib.sha256(body["reply"]["text"].encode()).hexdigest()
    assert body["audio"]["spoken_text"] == tts.speech_text(body["reply"]["text"])
    clip = client.get(body["audio"]["url"])
    assert clip.status_code == 200 and clip.headers["content-type"] == "audio/wav" and clip.content == FAKE_WAV
    assert client.get("/api/audio/not-a-real-id").status_code == 404


def test_audio_turn(client):
    sid = session_id(client)
    r = client.post("/api/turn/audio", data={"session_id": sid, "lang": "auto"},
                    files={"audio": ("voice.wav", make_wav(1.0), "audio/wav")})
    body = r.json()
    assert r.status_code == 200
    assert body["transcript"]["text"] == "Hello, where is my order 4512?"
    assert body["transcript"]["audio_seconds"] == pytest.approx(1.0, abs=0.05)
    assert "4512" in body["reply"]["text"] and body["audio"]["url"].startswith("/api/audio/")


@pytest.mark.parametrize("payload, status, code", [
    (b"not audio", 415, "unsupported_format"),
    (b"", 400, "empty_audio"),
])
def test_audio_turn_refuses_bad_files(client, payload, status, code):
    sid = session_id(client)
    r = client.post("/api/turn/audio", data={"session_id": sid}, files={"audio": ("x.webm", payload, "audio/webm")})
    assert r.status_code == status and r.json()["error"]["code"] == code


def test_oversized_request_refused_before_reading(client):
    r = client.post("/api/turn/audio", content=b"x" * 10, headers={"content-length": "9000000",
                                                                   "content-type": "multipart/form-data; boundary=x"})
    assert r.status_code == 413


def test_text_limits_and_expired_session(client):
    sid = session_id(client)
    assert client.post("/api/turn/text", json={"session_id": sid, "text": "   "}).status_code == 400
    assert client.post("/api/turn/text", json={"session_id": sid, "text": "a" * 1001}).status_code == 413
    r = client.post("/api/turn/text", json={"session_id": "unknown", "text": "hi"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "session_expired"


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(web, "per_session", RateLimiter(2, 600))
    sid = session_id(client)
    codes = [client.post("/api/turn/text", json={"session_id": sid, "text": "hi"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_speech_to_text_failure_is_a_clear_error(client, monkeypatch):
    def fail(*args, **kwargs):
        raise stt.SpeechError("stt_unavailable", "Speech recognition is unavailable right now. Please type your message.")
    monkeypatch.setattr(stt, "transcribe", fail)
    r = client.post("/api/turn/audio", data={"session_id": session_id(client)},
                    files={"audio": ("v.wav", make_wav(1.0), "audio/wav")})
    assert r.status_code == 503 and "type your message" in r.json()["error"]["message"]


def test_tts_failure_keeps_the_text_reply(client, monkeypatch):
    def fail(text, language=None):
        raise tts.TTSError("voice missing")
    monkeypatch.setattr(tts, "synthesize", fail)
    body = client.post("/api/turn/text", json={"session_id": session_id(client), "text": "hi"}).json()
    assert body["reply"]["text"] and body["audio"] is None and body["audio_error"]


def test_session_keeps_the_conversation(client):
    sid = session_id(client)
    for text in ("first", "second"):
        client.post("/api/turn/text", json={"session_id": sid, "text": text})
    session = web.sessions.get(sid)
    assert [m["content"] for m in session.history if m["role"] == "user"] == ["first", "second"]


def test_real_mode_over_http_with_fake_llm(client, monkeypatch):
    """REAL: question -> email asked (no LLM) -> email -> Agent A answers with its tools."""
    monkeypatch.setattr(pipeline, "resolve_mode", lambda: "real")
    replies = [SimpleNamespace(content=None, tool_calls=[SimpleNamespace(
                   id="c1", function=SimpleNamespace(name="get_tracking", arguments=json.dumps({"order_id": 4512})))]),
               SimpleNamespace(content="Your order 4512 is stuck at the depot and is 6 days late.", tool_calls=None)]
    monkeypatch.setattr(llm, "chat", lambda role_key, messages, tools=None: replies.pop(0))

    sid = session_id(client)
    first = client.post("/api/turn/audio", data={"session_id": sid},
                        files={"audio": ("v.wav", make_wav(1.0), "audio/wav")}).json()
    assert first["mode"] == "real" and first["reply"]["kind"] == "channel" and "email" in first["reply"]["text"]

    second = client.post("/api/turn/text", json={"session_id": sid, "text": "sara@example.com"}).json()
    assert second["reply"]["kind"] == "agent" and second["reply"]["agent"] == "A"
    assert second["reply"]["tools_used"] == ["get_tracking"]
    assert "6 days late" in second["reply"]["text"]
    assert {st["name"]: st["status"] for st in second["steps"]} == {
        "intake": "real", "router": "real", "agent": "real", "coordinator": "not built", "response": "not built"}
    assert second["audio"]["spoken_text"] == tts.speech_text(second["reply"]["text"])
