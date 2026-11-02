"""Speech services: audio upload checks, speech-to-text backup chain and errors, text-to-speech text rules.
Tests that need the real models run only when the models are installed (scripts/download_voice_models.py)."""

import io
import math
import struct
import wave
from types import SimpleNamespace

import pytest

pytest.importorskip("av")   # voice dependencies: pip install -r requirements-voice.txt

from callverse.web import audio, stt, tts  # noqa: E402
from callverse.web.models import piper_dir  # noqa: E402


def make_wav(seconds: float, rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 8))) for i in range(int(seconds * rate))))
    return buffer.getvalue()


# ---------- audio checks ----------
def test_valid_wav():
    info = audio.validate(make_wav(1.5))
    assert info["format"] == "wav" and info["mime"] == "audio/wav" and abs(info["seconds"] - 1.5) < 0.05


@pytest.mark.parametrize("data, status, code", [
    (b"", 400, "empty_audio"),
    (b"hello, this is not audio at all", 415, "unsupported_format"),
    (b"RIFF\x00\x00\x00\x00WAVEbroken", 400, "unreadable_audio"),
    (b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 5_000_100, 413, "audio_too_large"),
])
def test_refused_uploads(data, status, code):
    with pytest.raises(audio.AudioError) as e:
        audio.validate(data)
    assert (e.value.status, e.value.code) == (status, code)


def test_too_long_and_too_short():
    with pytest.raises(audio.AudioError) as e:
        audio.validate(make_wav(31))
    assert e.value.code == "audio_too_long"
    with pytest.raises(audio.AudioError) as e:
        audio.validate(make_wav(0.1))
    assert e.value.code == "audio_too_short"


def test_sniff_browser_formats():
    assert audio.sniff_format(b"\x1a\x45\xdf\xa3....") == "webm"
    assert audio.sniff_format(b"OggS....") == "ogg"
    assert audio.sniff_format(b"\x00\x00\x00\x20ftypM4A ") == "mp4"
    assert audio.sniff_format(b"ID3\x04....") == "mp3"


# ---------- speech-to-text chain ----------
def fake_provider(result=None, error=None):
    def provider(data, fmt, mime, language):
        if error:
            raise error
        return result
    return provider


def test_next_provider_when_first_is_unavailable(monkeypatch):
    monkeypatch.setattr(stt, "PROVIDERS", {"groq": fake_provider(error=stt.ProviderUnavailable("missing key")),
                                           "faster_whisper": fake_provider(("Where is my order 4512?", "en"))})
    heard = stt.transcribe(b"x", "wav", "audio/wav")
    assert heard == {"text": "Where is my order 4512?", "language": "en", "provider": "faster_whisper",
                     "seconds": heard["seconds"]}


def test_all_providers_unavailable(monkeypatch):
    down = fake_provider(error=stt.ProviderUnavailable("down"))
    monkeypatch.setattr(stt, "PROVIDERS", {"groq": down, "faster_whisper": down})
    with pytest.raises(stt.SpeechError) as e:
        stt.transcribe(b"x", "wav", "audio/wav")
    assert e.value.code == "stt_unavailable" and len(e.value.details) == 2


def test_silence_gives_no_speech(monkeypatch):
    monkeypatch.setattr(stt, "PROVIDERS", {"groq": fake_provider(("  ", "en")),
                                           "faster_whisper": fake_provider(("x", "en"))})
    with pytest.raises(stt.SpeechError) as e:
        stt.transcribe(b"x", "wav", "audio/wav")
    assert e.value.code == "no_speech"


def test_groq_without_key_is_skipped(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(stt.ProviderUnavailable):
        stt._groq(b"x", "wav", "audio/wav", None)


def _install_fake_groq(monkeypatch, outcome):
    import openai
    try:
        import httpx2 as httpx
    except ImportError:
        import httpx

    class FakeClient:
        def __init__(self, **kwargs):
            self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self.create))

        def create(self, **request):
            assert request["model"] == "whisper-large-v3-turbo" and request["file"][0] == "voice.wav"
            if isinstance(outcome, int):
                response = httpx.Response(outcome, request=httpx.Request("POST", "https://fake"))
                raise openai.APIStatusError("fake", response=response, body=None)
            return outcome

    monkeypatch.setattr(openai, "OpenAI", FakeClient)
    monkeypatch.setenv("GROQ_API_KEY", "not-a-real-key")


def test_groq_success_maps_language(monkeypatch):
    _install_fake_groq(monkeypatch, SimpleNamespace(text="Où est ma commande 4512 ?", language="French"))
    assert stt._groq(b"x", "wav", "audio/wav", None) == ("Où est ma commande 4512 ?", "fr")


@pytest.mark.parametrize("status, unavailable", [(429, True), (503, True), (401, True), (400, False)])
def test_groq_errors(monkeypatch, status, unavailable):
    _install_fake_groq(monkeypatch, status)
    with pytest.raises(stt.ProviderUnavailable if unavailable else stt.SpeechError):
        stt._groq(b"x", "wav", "audio/wav", None)


# ---------- text-to-speech text ----------
@pytest.mark.parametrize("text, spoken", [
    ("Your order 4512 is late.", "Your order 4 5 1 2 is late."),
    ("Promised on 2026-10-03, paid 59.90 TND.", "Promised on 2026-10-03, paid 59.90 TND."),
    ("**Order 4512** is _stuck_", "Order 4 5 1 2 is stuck"),
    ("In 2026 we deliver.", "In 2026 we deliver."),
])
def test_speech_text_changes_only_pronunciation(text, spoken):
    assert tts.speech_text(text) == spoken


def test_missing_voice_is_a_tts_error(monkeypatch, tmp_path):
    monkeypatch.setenv("CALLVERSE_MODELS_DIR", str(tmp_path))
    tts._voice.cache_clear()
    with pytest.raises(tts.TTSError):
        tts.synthesize("Hello", "en")
    tts._voice.cache_clear()


# ---------- real models (only when installed) ----------
needs_models = pytest.mark.skipif(not (piper_dir() / "en_GB-cori-medium.onnx").exists(),
                                  reason="speech models not installed (python -m scripts.download_voice_models)")


@needs_models
@pytest.mark.parametrize("lang, voice", [("en", "en_GB-cori-medium"), ("fr", "fr_FR-upmc-medium")])
def test_real_piper_synthesis(lang, voice):
    out = tts.synthesize("Your order 4512 is stuck at the depot." if lang == "en"
                         else "Votre commande 4512 est bloquée au dépôt.", lang)
    assert out["voice"] == voice and out["seconds"] > 1
    with wave.open(io.BytesIO(out["wav"])) as w:
        assert w.getnframes() > 0


def steady_clip(text: str, voice: str = "en_GB-cori-medium") -> bytes:
    """Piper speech WITHOUT its random variation (noise 0), so a test hears exactly the same audio every run."""
    from piper import PiperVoice
    from piper.config import SynthesisConfig
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        PiperVoice.load(piper_dir() / f"{voice}.onnx").synthesize_wav(
            tts.speech_text(text), w, syn_config=SynthesisConfig(noise_scale=0.0, noise_w_scale=0.0))
    return buffer.getvalue()


@needs_models
def test_real_round_trip_piper_to_whisper(monkeypatch):
    """Piper says the demo question, the in-server Whisper model transcribes it, the order number survives."""
    from callverse.web import pipeline
    monkeypatch.delenv("GROQ_API_KEY", raising=False)        # force the in-server model
    clip = steady_clip("Hello, where is my order 4512?")
    info = audio.validate(clip)
    heard = stt.transcribe(clip, info["format"], info["mime"])
    assert heard["provider"] == "faster_whisper" and heard["language"] == "en"
    assert pipeline.find_order_ids(heard["text"]) == [4512]
    assert "where" in heard["text"].lower()
