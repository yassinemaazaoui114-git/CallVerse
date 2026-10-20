"""Voice channel (V01): transcribe and speak with FAKES (no API call, no sound card), the config section, the
git-ignored audio folder, traces, and the run_voice flow with a fake LLM. One extra test uses the real pyttsx3
engine when it is installed (Windows voices, or espeak-ng on Linux)."""

import io
import json
import math
import struct
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from callverse import trace
from callverse.channels import voice
from callverse.config import PROJECT_ROOT, load_config


def write_wav(path: Path, seconds: float, rate: int = 16000) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(6000 * math.sin(i / 9))) for i in range(int(seconds * rate))))
    return path


class FakeSTTClient:
    """Shaped like openai.OpenAI(...).audio.transcriptions.create, as Groq answers (verbose_json)."""

    def __init__(self, text="Hi, where is my order 4512?", language="English"):
        self.requests = []
        self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self.create))
        self.text, self.language = text, language

    def create(self, **request):
        self.requests.append(request)
        return SimpleNamespace(text=self.text, language=self.language, duration=1.5)


class FakeTTSEngine:
    """Shaped like a pyttsx3 engine: setProperty, save_to_file, runAndWait (writes a short .wav)."""

    def __init__(self):
        self.props, self.saved = {}, []

    def setProperty(self, name, value):
        self.props[name] = value

    def save_to_file(self, text, path):
        self.saved.append((text, path))

    def runAndWait(self):
        for _, path in self.saved:
            write_wav(Path(path), 0.8)


def trace_steps():
    return [json.loads(line) for line in trace.current_path().read_text(encoding="utf-8").splitlines()]


# ---------- config ----------
def test_voice_config_section():
    assert load_config()["voice"] == {"stt": {"provider": "groq", "model": "whisper-large-v3-turbo"},
                                      "tts": {"engine": "pyttsx3", "rate": 170}}
    assert load_config()["voice"]["stt"]["provider"] in load_config()["providers"]


def test_audio_folders_are_git_ignored():
    lines = [line.strip() for line in (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()]
    assert "samples/voice/" in lines and "out/" in lines


# ---------- transcribe ----------
def test_transcribe_with_fake_client(tmp_path):
    clip = write_wav(tmp_path / "clip1.wav", 2.0)
    client = FakeSTTClient()
    out = voice.transcribe(clip, client=client)

    assert out["text"] == "Hi, where is my order 4512?" and out["language"] == "en"
    assert out["audio_seconds"] == 2.0 and out["seconds"] >= 0
    assert set(out) == {"text", "language", "audio_seconds", "seconds"}
    assert client.requests[0]["model"] == "whisper-large-v3-turbo"
    step = [s for s in trace_steps() if s["step"] == "stt_call"][-1]
    assert step["data"]["file"] == "clip1.wav" and str(tmp_path) not in json.dumps(step)   # name only, no folder
    assert step["data"]["audio_seconds"] == 2.0


def test_transcribe_missing_key_and_missing_file(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(voice.VoiceError, match="GROQ_API_KEY"):
        voice.transcribe(write_wav(tmp_path / "a.wav", 0.5))
    with pytest.raises(voice.VoiceError, match="not found"):
        voice.transcribe(tmp_path / "missing.wav", client=FakeSTTClient())


# ---------- speak ----------
def test_speak_with_fake_engine(tmp_path):
    engine = FakeTTSEngine()
    out = voice.speak("Your order 4512 is stuck at the depot.", tmp_path / "out" / "reply.wav", engine=engine)
    assert set(out) == {"out_path", "seconds"} and Path(out["out_path"]).is_file()
    assert engine.props["rate"] == 170
    step = [s for s in trace_steps() if s["step"] == "tts_call"][-1]
    assert step["data"]["engine"] == "pyttsx3" and step["data"]["audio_seconds"] == 0.8


def test_speak_refuses_empty_text(tmp_path):
    with pytest.raises(voice.VoiceError):
        voice.speak("  ", tmp_path / "x.wav", engine=FakeTTSEngine())


def test_speak_real_pyttsx3(tmp_path):
    pytest.importorskip("pyttsx3")
    try:
        out = voice.speak("Your order 4512 is stuck at the depot.", tmp_path / "reply.wav")
    except voice.VoiceError as e:
        pytest.skip(f"no system voice here: {e}")
    assert voice.wav_seconds(out["out_path"]) > 1


# ---------- run_voice: STT -> pipeline (Intake -> Router -> Agent A) -> TTS ----------
def test_run_voice_flow_with_fakes(tmp_path, monkeypatch):
    pytest.importorskip("sentence_transformers")
    from scripts import run_voice

    replies = [SimpleNamespace(content="Your order 4512 is stuck at the depot and 6 days late.", tool_calls=None)]

    def fake_llm(role_key, messages, tools=None):
        if messages[0]["content"].startswith("You sort customer messages"):   # Intake's M2 fallback
            return SimpleNamespace(content='{"reasons": ["order_status"], "order_id": 4512}', tool_calls=None)
        return replies.pop(0)

    clip = write_wav(tmp_path / "clip.wav", 1.0)
    r = run_voice.run(clip, tmp_path / "reply.wav", chat_fn=fake_llm, stt_client=FakeSTTClient(),
                      tts_engine=FakeTTSEngine())
    assert r["heard"]["text"] == "Hi, where is my order 4512?"
    assert r["result"]["ticket"]["order_id"] == 4512 and r["result"]["route"]["agent"] == "A"
    assert "6 days late" in r["result"]["answer"]
    assert Path(r["spoken"]["out_path"]).is_file()
    steps = [s["step"] for s in trace_steps()]
    assert steps.index("stt_call") < steps.index("route") < steps.index("tts_call")
