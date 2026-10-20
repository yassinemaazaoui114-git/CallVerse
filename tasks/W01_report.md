# W01 report — Web voice + text customer channel (formerly "V01", see tasks/W01_web_voice_channel.md)

## 1. In plain words
CallVerse now has a customer website. A client can type a message or press the microphone and speak. The
voice message is turned into text, shown on screen, and handled exactly like a typed message. The answer
appears as text and is also read aloud by a computer voice, with a replay button. With an API key, Agent A
answers, but only after the client proves the order is theirs by giving its email. Without a key, the site
runs in a clearly labelled demo mode that reads no data. Everything runs in one container that a free
cloud service can host.

## 2. Done
**New package `callverse/web/`:**
- `audio.py`: upload checks. Real format from the first bytes (WebM, Ogg, WAV, MP4, MP3), ≤ 5 MB, ≤ 30 s measured by decoding, broken files refused.
- `stt.py`: speech-to-text backup chain (like `llm.py`): Groq Whisper large-v3-turbo, then faster-whisper `base` inside the server.
- `tts.py`: Piper voices (EN `en_GB-cori-medium`, FR `fr_FR-upmc-medium`), plus a fixed pronunciation pass (order numbers digit by digit, markdown symbols removed).
- `pipeline.py`: `handle_turn()`, shared by text and voice.
  - REAL = identity check, then Agent A, then a check of what the agent read.
  - MOCK = fixed demo text.
  - Order numbers are read from STT output ("4,512", "4.512", "4, 5, 1, 2", "45 12").
- `sessions.py`: in-memory sessions (history = context for the agent), rate limits, and the replay-audio store.
- `app.py`: FastAPI with public routes only (`/`, `/api/health`, `/api/session`, `/api/turn/text`, `/api/turn/audio`, `/api/audio/{id}`), strict security headers, and a body-size guard.
- `static/`: chat page in plain HTML/CSS/JS, no build step.
  - Text input; microphone recording with timer, level meter, stop/send and cancel; transcription status.
  - Chat bubbles; audio player with play/pause and replay.
  - Error bubbles with retry; REAL/MOCK badge and tags; language choice (Auto/EN/FR).
  - Responsive layout with light/dark themes and accessible labels.

**Other new files:**
- `scripts/run_web.py`, `scripts/download_voice_models.py`
- `Dockerfile`, `.dockerignore`, `deploy/huggingface/README.md` (Space header), `requirements-voice.txt`
- Tests: `tests/test_web_pipeline.py` (26), `tests/test_web_speech.py` (24), `tests/test_web_api.py` (15), `tests/test_web_browser.py` (2, opt-in)
- Docs: `docs/voice_channel.md` (flow, choices, API, run, deploy, licences, security, limits), and this report plus `tasks/W01_web_voice_channel.md`

**Changed:**
- `config.yaml`: new web section (now named `web_channel:`, so V01 owns `voice:`).
- `.gitignore`: `models/`.
- `README.md`: one section and one folder-map line.

**Not changed:** agents, `llm.py`, tools, registry, data, intake, `tasks/NEXT.md`, other branches.

## 3. Evidence
**Tests:**

| Run | Result |
|---|---|
| Baseline before any change (`main`) | 14/14 |
| Full suite with the voice libraries and models | **79/79 passed**, 1 module skipped (browser, opt-in). Earlier: 78/78 three runs in a row, before the last test was added |
| Browser (Chromium + fake microphone + real models) | **2/2 passed**, 6 runs in a row |
| Core-only environment (`requirements.txt` only) | **40 passed, 3 voice modules skipped** |

**Demo scenario "Hello, where is my order 4512?" (MOCK, no key):**
- Browser test: the fake microphone plays a Piper clip, MediaRecorder captures it, the transcript shows "4512", the MOCK reply mentions order 4512, its audio plays, and replay works.
- No JS errors and no CSP violations.

**Docker** (`python:3.12-slim`, user 1000, 2 CPUs):
- Image 1.49 GB; about 0.5 GB RAM in use.
- Cold first voice turn 8.1 s; warm voice turn **2.4 s** (STT + reply + TTS); warm text turn 0.9 s.
- `/admin/reset` → 404.

**REAL wiring in Docker (invalid key):**
- Mode REAL. STT skipped Groq and fell back to faster-whisper.
- The question triggered the email request; after the email, the reply was "temporarily unavailable" (HTTP 200, spoken).
- The first image crashed here with HTTP 500. Fixed (agent `APIError` caught) and a test added.

**Round-trip voice choice** (Piper → Whisper, 3 EN / 3 FR sentences, 5 voices): cori (EN) and upmc (FR) were the clearest. Whisper `base` matched `small` on these clips at about 1/3 of the time.

Secret scan of the working tree: 0 matches. `git status`: only the files above.

## 4. Problems
- **Not committed or pushed** (CLAUDE.md rule 1: a commit or push needs an approved task-file Git section from Yassine). The work exists only in this session's working tree and in the patch file given to Semah.
- **REAL mode with Groq never ran live** (no key in this environment). It is tested with a fake LLM, also over HTTP.
- **French numbers:** with the in-server Whisper, French order numbers in synthetic speech were often misheard. Groq should be better (not measured).
- **Random voice variation:** Piper adds random variation to each synthesis. That made the round-trip tests flaky until the test clips used noise 0. Production speech keeps the natural variation.
- **PyAV:** PyAV ≥ 16 breaks faster-whisper 1.2.1 (`metadata_errors`), so `av` is pinned `<16`.
- **Single process:** sessions, rate limits and the audio cache live in memory.

## 5. Questions for the Brain
1. Approve the Git section of `tasks/W01_web_voice_channel.md` (commit, push `feature/multimodal-voice`, PR to `main`, no merge)?
2. Is the identity check (email of the order) the right rule for the prototype, or should it move into a shared "customer identity" step later used by Intake?
3. When the Coordinator and SLM exist: should `pipeline.real_reply()` call one orchestrator function (proposal: `handle_turn(session_id, text, channel, lang) -> {final_text, ...}`)?
4. Create a lane file (`tasks/NEXT_VOICE.md`) for Semah, like Dali's platform lane?

## 6. Next step
Approve and push the branch, then deploy to a Hugging Face Space (steps in `docs/voice_channel.md` §6) with the `GROQ_API_KEY` secret. Then run the REAL demo live and measure French with Groq Whisper.
