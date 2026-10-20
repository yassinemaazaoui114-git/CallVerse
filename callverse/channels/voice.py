"""Voice channel (task V01): speech in, speech out. The rest of CallVerse does not change.

    transcribe(audio_path) -> {text, language, audio_seconds, seconds}    speech-to-text (STT)
    speak(text, out_path)  -> {out_path, seconds}                        text-to-speech (TTS), to a .wav file

Why these tools (config.yaml -> voice):
- STT = Groq Whisper (whisper-large-v3-turbo) through the OpenAI-compatible audio endpoint: the same provider and
  key (GROQ_API_KEY in .env) as the agents, so no new account and no new library (the `openai` SDK is already used).
- TTS = pyttsx3: offline and free; it uses the computer's own voices (Windows: SAPI5, Linux: espeak-ng).
Every call is traced: `stt_call` and `tts_call`, with the audio duration and the processing time.
Privacy: the trace keeps the file NAME, never the folder or the audio itself. Recordings live in samples/voice/
(git-ignored), replies in out/ (git-ignored).
"""

import os
import time
import wave
from pathlib import Path

from callverse import trace
from callverse.config import load_config

# Groq answers with the language's English name ("English"); the rest of CallVerse uses ISO codes.
LANGUAGE_CODES = {"english": "en", "french": "fr", "arabic": "ar"}


class VoiceError(RuntimeError):
    """Speech-to-text or text-to-speech could not run (missing key, unreadable file, no TTS engine)."""


def wav_seconds(path: str | Path) -> float | None:
    """Length of a .wav file in seconds (standard library only); None for other formats."""
    try:
        with wave.open(str(path), "rb") as w:
            return round(w.getnframes() / float(w.getframerate()), 2)
    except (wave.Error, EOFError, OSError):
        return None


def _stt_client():
    """OpenAI-compatible client for the STT provider of config.yaml (base_url + key from .env)."""
    from openai import OpenAI

    from callverse import llm  # noqa: F401  (importing llm loads .env, where the key lives)

    cfg = load_config()
    provider = cfg["providers"][cfg["voice"]["stt"]["provider"]]
    api_key = os.getenv(provider["key_env"])
    if not api_key:
        raise VoiceError(f"missing {provider['key_env']} in .env (needed for speech-to-text)")
    return OpenAI(base_url=provider["base_url"], api_key=api_key, max_retries=0, timeout=60)


def transcribe(audio_path: str | Path, client=None) -> dict:
    """Speech-to-text of one recording. `client` lets the tests plug in a fake (no API call)."""
    path = Path(audio_path)
    if not path.is_file():
        raise VoiceError(f"audio file not found: {path.name}")
    stt = load_config()["voice"]["stt"]
    client = client or _stt_client()

    start = time.perf_counter()
    with open(path, "rb") as f:
        result = client.audio.transcriptions.create(model=stt["model"], file=f,
                                                    response_format="verbose_json", temperature=0)
    seconds = round(time.perf_counter() - start, 3)

    language = (getattr(result, "language", None) or "").lower()
    audio_seconds = wav_seconds(path) or getattr(result, "duration", None)
    out = {"text": (result.text or "").strip(), "language": LANGUAGE_CODES.get(language, language[:2] or None),
           "audio_seconds": audio_seconds, "seconds": seconds}
    trace.log("stt_call", "voice", {"provider": stt["provider"], "model": stt["model"], "file": path.name, **out})
    return out


def _wait_until_written(path: Path, timeout: float = 10.0) -> None:
    """Wait until the file exists and its size stops changing (checked every 50 ms), or the timeout passes."""
    deadline, last = time.monotonic() + timeout, -1
    while time.monotonic() < deadline:
        size = path.stat().st_size if path.is_file() else -1
        if size > 0 and size == last:
            return
        last = size
        time.sleep(0.05)


def _tts_engine():
    import pyttsx3
    try:
        return pyttsx3.init()
    except RuntimeError as e:   # e.g. Linux without espeak-ng
        raise VoiceError(f"text-to-speech engine unavailable: {e}")


def speak(text: str, out_path: str | Path, engine=None) -> dict:
    """Text-to-speech of `text` into a .wav file. `engine` lets the tests plug in a fake."""
    if not text or not text.strip():
        raise VoiceError("nothing to say")
    tts = load_config()["voice"]["tts"]
    if tts["engine"] != "pyttsx3":
        raise VoiceError(f"unknown TTS engine {tts['engine']!r} (V01 supports pyttsx3)")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    engine = engine or _tts_engine()

    out.unlink(missing_ok=True)       # never mistake an old reply for the new one
    start = time.perf_counter()
    engine.setProperty("rate", tts["rate"])
    engine.save_to_file(text, str(out))
    engine.runAndWait()
    _wait_until_written(out)          # some drivers (espeak) finish writing after runAndWait() returns
    seconds = round(time.perf_counter() - start, 3)
    if not out.is_file() or out.stat().st_size == 0:
        raise VoiceError("the TTS engine wrote no audio")

    result = {"out_path": str(out), "seconds": seconds}
    trace.log("tts_call", "voice", {"engine": tts["engine"], "rate": tts["rate"], "chars": len(text),
                                    "file": out.name, "audio_seconds": wav_seconds(out), "seconds": seconds})
    return result
