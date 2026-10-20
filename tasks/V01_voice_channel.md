# V01 — Voice channel (speech in, speech out)  ·  Semah's lane

## Why
CallVerse simulates a customer **call** center. Voice is just another **channel**: we convert speech to text at the
door and text to speech at the exit, so the rest of the system (Intake → agents → Coordinator → SLM) does not change.
This shows the architecture is channel-independent, with almost no risk to the core.

## Hard limits
- Branch **`feature/voice`** from the latest `main`. Do **not** merge into `main`.
- Do **not** change intake, agents, tools, coordinator, platform or `llm.py` logic. Allowed: a new provider/role entry
  in `config.yaml` and new files under `callverse/channels/`, `scripts/`, `tests/`.
- Speech-to-text (STT): Groq Whisper (`whisper-large-v3-turbo`) through the OpenAI-compatible audio endpoint, key
  `GROQ_API_KEY` from `.env`. Text-to-speech (TTS): `pyttsx3` (offline, uses Windows voices). New libraries allowed:
  `pyttsx3`, `soundfile` (only if needed).
- Audio recordings are personal data: record **only team members' voices**, keep them in `samples/voice/` and add that
  folder to `.gitignore` (commit at most one short demo clip, with the speaker's OK).
- No secrets in files. Every STT/TTS call traced (`stt_call`, `tts_call`) with duration and seconds.

## What to do
1. `callverse/channels/voice.py`:
   - `transcribe(audio_path) -> {text, language, audio_seconds, seconds}` (STT).
   - `speak(text, out_path) -> {out_path, seconds}` (TTS to a .wav file).
2. `config.yaml`: section `voice: {stt: {provider: groq, model: whisper-large-v3-turbo}, tts: {engine: pyttsx3, rate: 170}}`.
3. `scripts/run_voice.py --audio <file.wav>`: transcribe → pass the text to the existing Intake (`callverse.intake`)
   and print the ticket → run the existing Agent A demo on the text → `speak()` the answer to `out/reply.wav`.
   (When the pipeline from T04 is in `main`, this script will call the pipeline instead; keep the call in one function.)
4. Record **5 short clips** (your voice, English): e.g. "Hi, where is my order 4512?", "My order 4512 is a week late,
   I want my money back", "The speaker from order 4507 arrived broken", and 2 of your own.
5. Tests (no API calls): `transcribe` and `speak` with fakes; config section loads; audio folder is git-ignored.

## Checks (with numbers)
- Order number heard correctly in the clips that contain one (report x/y).
- Intake gives the expected main reason on the transcribed text (report x/5).
- Average STT time per clip and TTS time per reply (report seconds).
- Reply audio file plays (report its length).
- All tests pass (report x/y); 0 audio files committed except an approved demo clip.

## Time box and stop rule
2 hours. If Groq audio is not available on the free tier or the key fails, stop and report.

## Git (approved by Yassine, 2026-10-20)
Create `feature/voice` from latest `main`, commit, push the branch. No merge. Write `tasks/V01_report.md` (6-section
format from `CLAUDE.md`) and a lane file `tasks/NEXT_VOICE.md` set to WAITING FOR REVIEW.
