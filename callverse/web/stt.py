"""Speech-to-text: voice message (bytes) -> text, with a backup chain like llm.py.

Providers are tried in the order of config.yaml (voice.stt.providers):
  - groq           Whisper large-v3-turbo on Groq's API. Reuses the providers/key_env of config.yaml
                   (the same GROQ_API_KEY as the agents); the key stays on the server, never in the browser.
  - faster_whisper The open-source Whisper model running inside our own server (CPU). Works with no key.
We move to the next provider when one is unavailable (no key, rate limit, server or network error).
A recording that no provider can understand gives SpeechError.
"""

import io
import os
import threading
import time
from functools import lru_cache

from callverse import trace
from callverse.config import load_config
from callverse.web.models import whisper_dir

# Groq answers with the language's English name; the rest of the app uses ISO codes.
LANGUAGE_CODES = {"english": "en", "french": "fr", "arabic": "ar"}


class SpeechError(Exception):
    """Speech-to-text failed for every provider, or heard nothing. `message` is safe to show the user."""

    def __init__(self, code: str, message: str, details: list[str] | None = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or []


class ProviderUnavailable(Exception):
    """This provider cannot be used right now; try the next one."""


def _groq(audio: bytes, fmt: str, mime: str, language: str | None) -> tuple[str, str | None]:
    from openai import APIConnectionError, APIStatusError, OpenAI

    cfg = load_config()
    entry = cfg["voice"]["stt"]["groq"]
    provider = cfg["providers"][entry["provider"]]
    api_key = os.getenv(provider["key_env"])
    if not api_key:
        raise ProviderUnavailable(f"missing {provider['key_env']}")

    client = OpenAI(base_url=provider["base_url"], api_key=api_key, max_retries=0, timeout=30)
    request = {"model": entry["model"], "file": (f"voice.{fmt}", audio, mime),
               "response_format": "verbose_json", "temperature": 0}
    if language:
        request["language"] = language
    try:
        result = client.audio.transcriptions.create(**request)
    except APIConnectionError as e:
        raise ProviderUnavailable(f"connection error: {type(e).__name__}")
    except APIStatusError as e:
        if e.status_code == 429 or e.status_code >= 500 or e.status_code in (401, 403, 404):
            raise ProviderUnavailable(f"HTTP {e.status_code}")
        raise SpeechError("stt_rejected", "The recording could not be transcribed. Please try again.",
                          [f"groq HTTP {e.status_code}"])
    detected = getattr(result, "language", None)
    if detected:
        detected = LANGUAGE_CODES.get(detected.lower(), detected.lower()[:2])
    return result.text, detected


_model_lock = threading.Lock()


@lru_cache(maxsize=1)
def _whisper_model():
    from faster_whisper import WhisperModel

    cfg = load_config()["voice"]["stt"]["faster_whisper"]
    return WhisperModel(cfg["model"], device="cpu", compute_type=cfg["compute_type"],
                        cpu_threads=cfg["cpu_threads"], download_root=str(whisper_dir()))


def _faster_whisper(audio: bytes, fmt: str, mime: str, language: str | None) -> tuple[str, str | None]:
    try:
        with _model_lock:  # load once, even if two requests arrive together
            model = _whisper_model()
    except Exception as e:
        raise ProviderUnavailable(f"model not available: {type(e).__name__}")
    segments, info = model.transcribe(io.BytesIO(audio), language=language, beam_size=1,
                                      condition_on_previous_text=False)
    return " ".join(s.text.strip() for s in segments), info.language


PROVIDERS = {"groq": _groq, "faster_whisper": _faster_whisper}


def transcribe(audio: bytes, fmt: str, mime: str, language: str | None = None) -> dict:
    """Return {"text", "language", "provider", "seconds"}. `language` = "en"/"fr" hint, or None to detect."""
    errors = []
    for name in load_config()["voice"]["stt"]["providers"]:
        start = time.perf_counter()
        try:
            text, detected = PROVIDERS[name](audio, fmt, mime, language)
        except ProviderUnavailable as e:
            errors.append(f"{name}: {e}")
            trace.log("stt_skip", "web", {"provider": name, "reason": str(e)})
            continue
        seconds = round(time.perf_counter() - start, 3)
        text = (text or "").strip()
        trace.log("stt", "web", {"provider": name, "language": detected, "seconds": seconds, "text": text})
        if not text:
            raise SpeechError("no_speech", "I could not hear any words. Please try again closer to the microphone.")
        return {"text": text, "language": detected or language, "provider": name, "seconds": seconds}
    raise SpeechError("stt_unavailable", "Speech recognition is unavailable right now. Please type your message.",
                      errors)


def available_providers() -> list[str]:
    """Providers that look usable now (for /api/health): groq needs its key; faster_whisper needs the library."""
    cfg = load_config()
    found = []
    for name in cfg["voice"]["stt"]["providers"]:
        if name == "groq":
            key_env = cfg["providers"][cfg["voice"]["stt"]["groq"]["provider"]]["key_env"]
            if os.getenv(key_env):
                found.append(name)
        elif name == "faster_whisper":
            try:
                import faster_whisper  # noqa: F401
                found.append(name)
            except ImportError:
                pass
    return found
