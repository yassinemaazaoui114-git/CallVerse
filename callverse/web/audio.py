"""Checks on an uploaded voice message, BEFORE it is sent to speech-to-text.

Why: the upload comes from the internet, so we never trust its file name or declared type.
We look at the first bytes of the file ("magic bytes") to know its real format, refuse empty,
too big or too long recordings, and refuse files that cannot be decoded as audio.
Nothing is written to disk: the audio stays in memory and is dropped after transcription.
"""

import io

from callverse.config import load_config


class AudioError(Exception):
    """A problem with the uploaded audio. `status` is the HTTP code, `code` a short machine name."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# Formats browsers record (MediaRecorder) or users may upload, recognised by their first bytes.
def sniff_format(data: bytes) -> str | None:
    """Return "webm", "ogg", "wav", "mp4" or "mp3" from the file's first bytes, or None if unknown."""
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"                       # Matroska/WebM (Chrome, Firefox, Edge)
    if data[:4] == b"OggS":
        return "ogg"                        # Ogg/Opus (Firefox)
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[4:8] == b"ftyp":
        return "mp4"                        # MP4/M4A (Safari)
    if data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0):
        return "mp3"
    return None


MIME_TYPES = {"webm": "audio/webm", "ogg": "audio/ogg", "wav": "audio/wav", "mp4": "audio/mp4", "mp3": "audio/mpeg"}


def duration_seconds(data: bytes, stop_after: float) -> float:
    """Length of the recording in seconds, measured by decoding it (PyAV).

    Browser recordings (WebM from MediaRecorder) usually have no duration in their header, so we
    count the decoded samples. We stop as soon as the length passes `stop_after` (no need to decode
    a 10-minute file to know it is too long).
    """
    import av  # imported here so the rest of the web app loads without the speech libraries

    total = 0.0
    with av.open(io.BytesIO(data), mode="r") as container:
        if not container.streams.audio:
            raise AudioError(400, "no_audio", "The file contains no audio track.")
        stream = container.streams.audio[0]
        for frame in container.decode(stream):
            total += frame.samples / float(frame.sample_rate or 1)
            if total > stop_after:
                break
    return total


def validate(data: bytes) -> dict:
    """Check an upload and return {"format", "mime", "seconds", "bytes"}; raise AudioError if refused."""
    limits = load_config()["web_channel"]["limits"]
    if not data:
        raise AudioError(400, "empty_audio", "The recording is empty.")
    if len(data) > limits["max_audio_bytes"]:
        raise AudioError(413, "audio_too_large",
                         f"The recording is larger than {limits['max_audio_bytes'] // 1_000_000} MB.")

    fmt = sniff_format(data)
    if fmt is None:
        raise AudioError(415, "unsupported_format", "Unsupported audio format (use WebM, Ogg, WAV, MP4 or MP3).")

    try:
        seconds = duration_seconds(data, stop_after=limits["max_audio_seconds"])
    except AudioError:
        raise
    except Exception:  # PyAV raises many error types for broken files; all mean the same for the user
        raise AudioError(400, "unreadable_audio", "The recording could not be read. Please try again.")

    if seconds > limits["max_audio_seconds"]:
        raise AudioError(413, "audio_too_long", f"Voice messages are limited to {limits['max_audio_seconds']} seconds.")
    if seconds < 0.3:
        raise AudioError(400, "audio_too_short", "The recording is too short. Please speak a little longer.")
    return {"format": fmt, "mime": MIME_TYPES[fmt], "seconds": round(seconds, 2), "bytes": len(data)}
