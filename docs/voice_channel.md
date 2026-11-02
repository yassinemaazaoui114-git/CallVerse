# Voice + text customer channel (`callverse/web/`)

A website where a ShopNova customer **types or speaks** to CallVerse and gets a **written and spoken**
answer. It is a **channel adapter**, not an agent: it turns audio into text and the approved reply into
audio. All business logic stays in the agents (and later in the Coordinator).

## 1. Flow

```
Browser (microphone, MediaRecorder: WebM/Opus, Ogg or MP4, max 30 s)
   │  POST /api/turn/audio            (or POST /api/turn/text for typed messages)
   ▼
audio.py      checks the upload: real format from its first bytes, size ≤ 5 MB, length ≤ 30 s
   ▼
stt.py        speech-to-text, backup chain:  1. Groq Whisper large-v3-turbo (API, GROQ_API_KEY)
              (same idea as llm.py)          2. faster-whisper "base" inside our server (CPU, no key)
   ▼  transcript (shown to the customer)
pipeline.py   handle_turn(session, text)  ◄── the SAME function for text and voice
   │   REAL: identity check (email of the order) → Agent A (read tools + M2) → check of what it read
   │   MOCK: fixed demo text, no agent, no data
   ▼  reply text (the one shown on screen)
tts.py        Piper voice (en_GB-cori / fr_FR-upmc) on the server CPU → WAV
   ▼
Browser       shows the text, plays the audio, replay button
```

Every step is traced (`traces/*.jsonl`): `stt`, `identity`, agent steps, `tool_call`, `tts`, `web_turn`.
The raw recording is never written to disk and is dropped after transcription.

## 2. Why these choices

| Choice | Why |
|---|---|
| Voice = channel adapter | One business logic for text and voice; the voice layer can never take a decision. |
| Groq Whisper first | Same provider and key as the agents (M2), free tier, best accuracy (large-v3-turbo). |
| faster-whisper `base` as backup | Works with no key and no paid service, inside the cloud container. In our round-trip test it was as accurate as `small` and 3x faster on 2 CPUs. |
| Piper for speech | Open source, fast on CPU (about 0.2 s per sentence when warm), English + French voices, no API, no cost. |
| Voices `en_GB-cori-medium`, `fr_FR-upmc-medium` | Best round trip (Piper → Whisper) of the voices we tried, and clear data licences (see §7). |
| One CallVerse voice per language | The customer hears the approved message, not an agent; a voice per agent would suggest separate authorities. |
| Order numbers read digit by digit | "4 5 1 2" is understood far more reliably than "four thousand five hundred twelve" (round-trip test). |
| Identity check before any order data | Agent A can read any order; a public website must only show customers their own orders. |
| REAL / MOCK modes | The speech features can be tested and demonstrated without an API key, and a demo reply can never be mistaken for a real decision. |

## 3. REAL and MOCK

`config.yaml` → `voice.mode`: `auto` (default) = REAL when `GROQ_API_KEY` is set, otherwise MOCK; or force `real` / `mock`.

- **REAL** – Agent A (Status & Tracking), the only agent that exists today, answers with its read tools.
  - **Identity check:** when a message names an order, CallVerse first asks for the email address of that order and checks it with the read tools (`get_user`, `get_order`). Only then does the agent run, on the question that was waiting.
  - **Out-of-scope reads:** after the agent answers, the channel checks which orders and clients its tools read. If anything was outside what the customer proved, the answer is withheld.
  - **Refunds:** Agent A's handover to the refund team (`[HANDOVER: B]`) is flagged in the reply (`handover: "B"` + a notice), because Agent B does not exist yet. Nothing is forwarded.
  - **Outages:** if the LLM is unavailable (all models down, wrong key), the customer gets "temporarily unavailable". It never falls back to MOCK.
- **MOCK** – a fixed text that says it is a demo. No agent, no LLM, no database read (tested). The UI shows a yellow **Demo (MOCK)** badge and a `MOCK` tag on every reply.

When the full chain (Intake → Queues → Agents → Coordinator → SLM) exists, only `pipeline.real_reply()` changes: it must return the Coordinator-approved final text. The web app, the browser and the speech code stay the same.

## 4. API

All JSON errors have the shape `{"error": {"code", "message"}}`, and `message` is safe to show.

| Route | Input | Output |
|---|---|---|
| `GET /` | – | the chat page |
| `GET /api/health` | – | `status`, `mode`, `languages`, `stt_providers`, `tts_voices`, `limits` |
| `POST /api/session` | – | `{"session_id", "mode"}` (keep the id; it is a secret) |
| `POST /api/turn/text` | JSON `{"session_id", "text", "lang": "auto"\|"en"\|"fr"}` | turn (below) |
| `POST /api/turn/audio` | multipart: `session_id`, `lang`, `audio` (file) | turn + `transcript` |
| `GET /api/audio/{clip_id}` | – | `audio/wav` (kept 15 min, for replay) |

Turn response:
```json
{"mode": "real|mock",
 "reply": {"text": "...", "kind": "agent|channel|mock", "agent": "A|null", "handover": "B|null",
           "language": "en|fr", "tools_used": ["get_tracking"], "notice": "(optional)"},
 "text_sha256": "<sha256 of reply.text>",
 "transcript": {"text", "language", "provider", "seconds", "audio_seconds"},   // audio turns only
 "audio": {"url", "voice", "seconds", "synthesis_seconds", "spoken_text"} | null,
 "audio_error": "(only when audio is null)",
 "seconds": {"pipeline": 0.24}}
```
`spoken_text` is `reply.text` after the fixed pronunciation pass (`tts.speech_text`: order numbers digit by digit, markdown symbols removed). No words are added or removed.

Error codes:
- 400: `empty_text`, `empty_audio`, `unreadable_audio`, `audio_too_short`, `no_audio`
- 404: `session_expired`, `audio_expired`
- 413: `text_too_long`, `audio_too_large`, `audio_too_long`, `request_too_large`
- 415: `unsupported_format`
- 422: `no_speech`
- 429: `rate_limited`
- 503: `stt_unavailable`, `stt_rejected`

There are **no** admin, database-write, Coordinator or `/docs` routes in this app (tested).

## 5. Run it

**On your computer:**
```bash
pip install -r requirements-voice.txt
python -m scripts.download_voice_models   # once, about 210 MB, into ./models (git-ignored)
python -m scripts.run_web                 # http://127.0.0.1:8080/
```
Without `GROQ_API_KEY` in `.env` the app runs in MOCK mode, and speech-to-text uses the in-server model.

**With Docker** (the same image runs in the cloud):
```bash
docker build -t callverse-voice .
docker run -p 7860:7860 -e GROQ_API_KEY=... callverse-voice    # omit the key for MOCK mode
```

**Tests:**
- `python -m pytest -q` runs everything. Voice tests skip when the voice libraries are not installed, and tests that need the real models skip until they are downloaded.
- Browser test (Chromium, fake microphone, real models): `RUN_BROWSER_TESTS=1 python -m pytest tests/test_web_browser.py` (optional `CHROMIUM_PATH=...`).

## 6. Deploy to Hugging Face Spaces (free CPU)

The free "CPU basic" hardware (2 vCPU, 16 GB RAM) runs the whole container: about 0.5 GB RAM in use, about 2.4 s per voice turn when warm (measured in Docker with 2 CPUs).

1. On huggingface.co: **New Space** → SDK **Docker** → template **Blank** → hardware **CPU basic (free)**.
2. Space → **Settings** → **Variables and secrets** → **New secret** `GROQ_API_KEY` (optional: without it, the Space runs in MOCK mode).
3. Push the code (the Space README needs its own header):
   ```bash
   git clone https://huggingface.co/spaces/<user>/<space> space && cd space
   git -C ../CallVerse archive feature/multimodal-voice | tar -x   # once the branch is committed
   cp deploy/huggingface/README.md README.md
   git add . && git commit -m "CallVerse voice channel" && git push
   ```
4. Wait for the build (installs the libraries and downloads the models), then open the Space URL.
   `GET /api/health` should report `"tts_voices"` with 2 voices.

Limits of the free tier:
- The Space **sleeps after 48 h without visitors** and needs a few minutes to wake up. Open it before a demo.
- Its disk is not persistent: the demo database is re-seeded and traces start fresh at each restart.

Groq's free tier has its own rate limits (check them in the Groq console). The app also caps traffic itself (§8).

Not suitable: Render's free plan (512 MB RAM, about 0.1 CPU) is too small to run the speech models.

## 7. Licences

| Part | Licence |
|---|---|
| Piper engine (`piper-tts`, OHF-Voice/piper1-gpl) | GPL-3.0. Running it as a web service is fine; redistributing a binary build would trigger GPL obligations. |
| Voice `en_GB-cori-medium` | trained on LibriVox recordings (public domain) |
| Voice `fr_FR-upmc-medium` | UPMC data, CC BY-SA 4.0 |
| faster-whisper / Whisper `base` | MIT |

Most Piper voices (including fr_FR-upmc) were fine-tuned from the `lessac` voice, whose dataset has a research licence. That is fine for this university prototype, but check it again before any commercial use.

## 8. Security and privacy

- **Keys:** API keys stay on the server (environment / Space secrets). The browser only talks to `/api`, and no key appears in the static files (tested).
- **Upload checks:** format by magic bytes, size checked before and after reading, length measured by decoding, broken files refused.
- **Abuse limits** (all in `config.yaml`): 30 turns per session per 10 min, 120 per IP per hour, 600 for the whole site per hour, 30 new sessions per IP per hour. Heavy speech work is limited to 2 at a time.
- **Data retention:** no raw audio is stored. Reply audio is kept in memory for 15 min (for replay) under an unguessable id. Sessions live in memory and expire after 60 min.
- **Identity:** order data is shown only after the email of the order is proved, and agent reads outside that scope are withheld.
- **Browser hardening:** strict Content-Security-Policy (no inline script), `X-Frame-Options: DENY`, `nosniff`, microphone allowed only for this site.
- **Admin surface:** none in this app. The platform server must stay on localhost.

## 9. Known limits

- **REAL mode with Groq was not run live during development** (no key available). The REAL path is tested end to end with a fake LLM, over HTTP too, and in Docker it degrades cleanly with an invalid key.
- **French:** detection, French replies and the French voice work. With the in-server Whisper (`base` or `small`), French order numbers in synthetic test speech were often misheard ("4.52"). Groq's large-v3-turbo is expected to do better (not measured). A misheard number cannot leak data: the identity check fails.
- **Intake is not used yet:** Intake is still on the unmerged `feature/intake` branch, and its models are English-only.
- **Single process:** sessions, rate limits and the audio cache live in one process's memory. Use Redis before scaling out.
- **Fake microphone:** Chromium's fake microphone loops the test clip, so browser-test transcripts can repeat words ("Hello … Hello").
- **Browsers:** Firefox and Safari recording were not tested (only Chromium). Safari records MP4, which the server accepts.
