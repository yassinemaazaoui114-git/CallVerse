"""Text-to-speech: the APPROVED reply text -> WAV audio, with Piper (open source, runs on the server CPU).

Rule: the audio says exactly the reply shown on screen. The only change before synthesis is a fixed
pronunciation pass (speech_text below): it adds no words, only changes how symbols are read, e.g.
order numbers are read digit by digit ("4 5 1 2"), the way a call center reads them, because
"four thousand five hundred twelve" was often misheard in our round-trip test.
"""

import io
import re
import threading
import time
import wave
from functools import lru_cache

from callverse import trace
from callverse.config import load_config
from callverse.web.models import piper_dir

MAX_TTS_CHARS = 1500


class TTSError(Exception):
    """Synthesis failed; the reply is still shown as text."""


# 4-6 digit numbers that are not part of an amount (1500.50) or a date (2026-10-03), and not a year (2026).
_ORDER_NUMBER = re.compile(r"(?<![\d.,/-])(?!(?:19|20)\d\d\b)(\d{4,6})(?![\d]|[.,/-]\d)")
_MARKDOWN = re.compile(r"[*_`#>|]+")


def speech_text(text: str) -> str:
    """How the reply is read aloud. Same words as the screen; only symbols and digits are changed."""
    spoken = _MARKDOWN.sub(" ", text)
    spoken = _ORDER_NUMBER.sub(lambda m: " ".join(m.group(1)), spoken)
    return re.sub(r"\s+", " ", spoken).strip()[:MAX_TTS_CHARS]


def voice_for(language: str | None) -> str:
    voices = load_config()["web_channel"]["tts"]["voices"]
    return voices.get(language or "en", voices["en"])


_load_lock = threading.Lock()


@lru_cache(maxsize=4)
def _voice(name: str):
    from piper import PiperVoice

    path = piper_dir() / f"{name}.onnx"
    if not path.exists():
        raise TTSError(f"voice model {name} is not installed (run scripts/download_voice_models.py)")
    return PiperVoice.load(path)


def synthesize(text: str, language: str | None = None) -> dict:
    """Return {"wav": bytes, "voice", "seconds" (audio length), "synthesis_seconds", "spoken_text"}."""
    name = voice_for(language)
    spoken = speech_text(text)
    if not spoken:
        raise TTSError("nothing to say")
    start = time.perf_counter()
    try:
        with _load_lock:
            voice = _voice(name)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            voice.synthesize_wav(spoken, wav)
    except TTSError:
        raise
    except Exception as e:  # onnxruntime / espeak errors: the reply stays available as text
        raise TTSError(f"{type(e).__name__}: {e}")
    data = buffer.getvalue()
    with wave.open(io.BytesIO(data)) as wav:
        seconds = wav.getnframes() / float(wav.getframerate())
    result = {"wav": data, "voice": name, "seconds": round(seconds, 2),
              "synthesis_seconds": round(time.perf_counter() - start, 3), "spoken_text": spoken}
    trace.log("tts_call", "web", {k: v for k, v in result.items() if k != "wav"})
    return result


def available_voices() -> list[str]:
    """Voices of config.yaml whose model file is installed (for /api/health)."""
    return [v for v in load_config()["web_channel"]["tts"]["voices"].values() if (piper_dir() / f"{v}.onnx").exists()]
