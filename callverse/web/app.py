"""CallVerse customer website: text + voice chat (FastAPI). Run it with: python -m scripts.run_web

Public routes only (this app is meant to be reachable from the internet):
  GET  /                      the chat page (static/index.html)
  GET  /api/health            is the app up, which mode, which speech providers/voices are installed
  POST /api/session           start a conversation -> {"session_id"}
  POST /api/turn/text         {"session_id", "text", "lang"}               -> reply (+ audio)
  POST /api/turn/audio        form: session_id, lang, audio (file)         -> transcript + reply (+ audio)
  GET  /api/audio/{clip_id}   the reply audio (WAV), for playing and replaying
There are NO admin, database-write or Coordinator routes here, on purpose. The platform server and its
admin dashboard (callverse/server, P05) are a SEPARATE app that stays on localhost (scripts/run_platform_server.py).

Secrets (GROQ_API_KEY) are read from the environment on the server only; nothing secret is sent to the browser.
"""

import hashlib
import threading
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from callverse import trace
from callverse.config import load_config
from callverse.web import audio as audio_check
from callverse.web import pipeline, stt, tts
from callverse.web.sessions import AudioStore, RateLimiter, SessionStore

STATIC = Path(__file__).resolve().parent / "static"
LIMITS = load_config()["voice"]["limits"]

app = FastAPI(title="CallVerse customer channel (text + voice)", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")

sessions = SessionStore(LIMITS["session_ttl_minutes"])
clips = AudioStore()
per_session = RateLimiter(LIMITS["turns_per_session_per_10min"], 600)
per_ip = RateLimiter(LIMITS["turns_per_ip_per_hour"], 3600)
# A hard ceiling for the whole site, whatever the visitor's address: protects the shared API quota.
everyone = RateLimiter(LIMITS["turns_global_per_hour"], 3600)
new_sessions_per_ip = RateLimiter(LIMITS["sessions_per_ip_per_hour"], 3600)
# Speech models use the CPU heavily: at most 2 at a time, others wait (keeps a small server responsive).
speech_slots = threading.BoundedSemaphore(2)

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; media-src 'self' blob:; img-src 'self' data:; "
                               "style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "microphone=(self), camera=(), geolocation=()",
    "X-Frame-Options": "DENY",
}


@app.middleware("http")
async def guard(request: Request, call_next):
    # Refuse oversized bodies before reading them (the audio limit + room for the form fields).
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > LIMITS["max_audio_bytes"] + 100_000:
        return _error(413, "request_too_large", "The request is too large.")
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/audio/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _client_ip(request: Request) -> str:
    # Behind the hosting proxy, the visitor's address is the LAST entry of X-Forwarded-For (added by the
    # proxy itself); earlier entries are written by the client and could be faked.
    forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
    return forwarded[-1] if forwarded else (request.client.host if request.client else "unknown")


def _start_turn(request: Request, session_id: str):
    """Return (session, None) or (None, error response): unknown session, or too many turns."""
    session = sessions.get(session_id)
    if session is None:
        return None, _error(404, "session_expired", "Your conversation expired. A new one has been started.")
    if not (per_session.allow(session.id) and per_ip.allow(_client_ip(request)) and everyone.allow("all")):
        return None, _error(429, "rate_limited", "Too many messages. Please wait a few minutes.")
    return session, None


def _speak(reply: dict) -> dict:
    """Add audio for the reply text. If synthesis fails, the reply is still shown as text."""
    try:
        with speech_slots:
            speech = tts.synthesize(reply["text"], reply["language"])
    except tts.TTSError as e:
        trace.log("tts_error", "web", {"error": str(e)})
        return {"audio": None, "audio_error": "Audio is unavailable for this reply."}
    return {"audio": {"url": f"/api/audio/{clips.put(speech['wav'])}", "voice": speech["voice"],
                      "seconds": speech["seconds"], "synthesis_seconds": speech["synthesis_seconds"],
                      # The spoken text is the displayed text with the fixed pronunciation pass (tts.speech_text).
                      "spoken_text": speech["spoken_text"]}}


def _response(reply: dict, extra: dict | None = None) -> dict:
    body = {"reply": {k: reply[k] for k in ("text", "kind", "agent", "handover", "language", "tools_used")
                      if k in reply} | ({"notice": reply["notice"]} if reply.get("notice") else {}),
            "mode": reply["mode"],
            # How CallVerse handled the turn: one entry per stage, marked real / interim / mock / not built / skipped.
            "steps": reply.get("steps", []),
            "ticket": reply.get("ticket"),        # Intake labels only (reasons, emotion, priority), never order facts
            "route": reply.get("route"),
            # Proof for the trace and the tests: the audio is made from exactly this text.
            "text_sha256": hashlib.sha256(reply["text"].encode("utf-8")).hexdigest(),
            "seconds": {"pipeline": reply["seconds"]}}
    body.update(extra or {})
    body.update(_speak(reply))
    return body


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html", media_type="text/html")


@app.get("/api/health")
def health():
    from callverse.integration import components
    return {"status": "ok", "mode": pipeline.resolve_mode(), "languages": load_config()["voice"]["languages"],
            "components": {"intake": "built", "agent_a": "built", **components.status()},
            "stt_providers": stt.available_providers(), "tts_voices": tts.available_voices(),
            "limits": {"max_audio_seconds": LIMITS["max_audio_seconds"],
                       "max_audio_bytes": LIMITS["max_audio_bytes"], "max_text_chars": LIMITS["max_text_chars"]}}


@app.post("/api/session")
def new_session(request: Request):
    if not new_sessions_per_ip.allow(_client_ip(request)):
        return _error(429, "rate_limited", "Too many conversations started. Please wait a few minutes.")
    session = sessions.create()
    return {"session_id": session.id, "mode": pipeline.resolve_mode()}


class TextTurn(BaseModel):
    session_id: str
    text: str
    lang: str | None = None


@app.post("/api/turn/text")
def turn_text(body: TextTurn, request: Request):
    session, refusal = _start_turn(request, body.session_id)
    if refusal:
        return refusal
    text = body.text.strip()
    if not text:
        return _error(400, "empty_text", "Please type a message.")
    if len(text) > LIMITS["max_text_chars"]:
        return _error(413, "text_too_long", f"Messages are limited to {LIMITS['max_text_chars']} characters.")
    lang = body.lang if body.lang in ("en", "fr") else None
    reply = pipeline.handle_turn(session, text, lang=lang, channel="text")
    return _response(reply)


@app.post("/api/turn/audio")
def turn_audio(request: Request, session_id: str = Form(...), lang: str = Form("auto"),
               audio: UploadFile = File(...)):
    session, refusal = _start_turn(request, session_id)
    if refusal:
        return refusal
    data = audio.file.read(LIMITS["max_audio_bytes"] + 1)   # never read more than the limit + 1 byte
    try:
        info = audio_check.validate(data)
    except audio_check.AudioError as e:
        return _error(e.status, e.code, e.message)

    hint = lang if lang in ("en", "fr") else None
    try:
        with speech_slots:
            heard = stt.transcribe(data, info["format"], info["mime"], language=hint)
    except stt.SpeechError as e:
        trace.log("stt_error", "web", {"code": e.code, "details": e.details})
        return _error(422 if e.code == "no_speech" else 503, e.code, e.message)
    finally:
        del data  # the raw recording is not kept anywhere

    language = heard["language"] if heard["language"] in ("en", "fr") else hint
    reply = pipeline.handle_turn(session, heard["text"], lang=language, channel="voice")
    return _response(reply, {"transcript": {"text": heard["text"], "language": heard["language"],
                                            "provider": heard["provider"], "seconds": heard["seconds"],
                                            "audio_seconds": info["seconds"]}})


@app.get("/api/audio/{clip_id}")
def get_audio(clip_id: str):
    data = clips.get(clip_id)
    if data is None:
        return _error(404, "audio_expired", "This audio is no longer available.")
    return Response(data, media_type="audio/wav", headers={"Cache-Control": "private, max-age=900"})
