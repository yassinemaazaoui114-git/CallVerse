# V01 report — Voice channel (speech in, speech out)

## 1. In plain words
CallVerse can now take a spoken question and give a spoken answer. A recording is turned into text by Groq's
Whisper (the same provider as the agents), the text goes through the existing pipeline (Intake, then the router,
then Agent A), and the answer is read aloud by the computer's own voice (pyttsx3) into a sound file. Nothing in
Intake, the agents or the platform changed: voice is only a door in and a door out. The code is done and tested,
but the 5 real recordings and their measurements still need Semah's own voice and a Groq key, so those checks are
pending (not invented).

## 2. Done
- `callverse/channels/voice.py`: `transcribe(audio_path) -> {text, language, audio_seconds, seconds}` (Groq
  `whisper-large-v3-turbo`, OpenAI-compatible audio endpoint, key `GROQ_API_KEY` from `.env`) and
  `speak(text, out_path) -> {out_path, seconds}` (pyttsx3, rate from config, to a .wav).
  - Every call is traced (`stt_call`, `tts_call`) with the audio duration and the processing time.
  - Privacy: only the file name is traced, never the folder or the audio.
  - `wav_seconds()` uses the standard library `wave`, so `soundfile` is not needed.
- `config.yaml`: `voice: {stt: {provider: groq, model: whisper-large-v3-turbo}, tts: {engine: pyttsx3, rate: 170}}`.
  The STT provider is a key of `providers`, so base URL and key name come from the existing entry.
- `scripts/run_voice.py --audio <file.wav> [--out out/reply.wav]`: transcribe → `respond()` → speak, then print
  transcript, ticket (reasons, main reason, priority, emotion, sentiment), route, answer and trace path.
  - T04 is already in `main`, so `respond()` calls `callverse.pipeline.handle()` (Intake → Router → Agent A or
    the handover to B), in one function as asked.
- `.gitignore`: `samples/voice/` (recordings = personal data) and `out/` (generated replies).
- `requirements.txt`: `pyttsx3` (allowed by the task). On Linux it needs the system package `espeak-ng`; on
  Windows it uses the built-in SAPI5 voices.
- `tests/test_voice_channel.py` (8 tests, no API call):
  - config section; audio folders git-ignored;
  - `transcribe` with a fake client (result keys, language code, trace without the folder); missing key / missing file;
  - `speak` with a fake engine (rate 170, trace); empty text refused;
  - real pyttsx3 when a system voice exists;
  - the `run_voice` flow (STT → T04 pipeline with the real Intake and router, fake LLM → TTS), checking the trace order `stt_call` < `route` < `tts_call`.
- `tasks/V01_voice_channel.md` (the task file) and `tasks/NEXT_VOICE.md` (lane file), set to WAITING FOR REVIEW.

Not changed: Intake, agents, tools, registry, Coordinator, platform, `llm.py`.

## 3. Evidence

| Check (from the task) | Result |
|---|---|
| All tests pass | **109/109** (main's 101 + 8 new), `python -m pytest -q` |
| Audio files committed | **0** (`samples/voice/` and `out/` are git-ignored, tested) |
| TTS time per reply | **0.076 s average** (10 replies, 2.6–9.9 s of audio, 0 failures). Linux sandbox, espeak-ng voice, not the Windows voices: re-measure on Windows |
| Reply audio file plays | valid .wav files of 2.6–9.9 s (read back with `wave`). Not listened to on Windows yet |
| Order number heard correctly in the clips that contain one | **PENDING**: needs the 5 recordings |
| Intake main reason on the transcribed text | **PENDING**: needs the 5 recordings |
| Average STT time per clip | **PENDING**: needs a Groq key |

STT stop rule: no `GROQ_API_KEY` was available where this was built. `python -m scripts.run_voice --audio …`
stops cleanly with "Voice error: missing GROQ_API_KEY in .env (needed for speech-to-text)", as the task's stop
rule asks. No recording was made and no result was invented.

**To finish the checks, on Semah's PC:**
1. Put `GROQ_API_KEY` in `.env`.
2. Record the 5 clips into `samples/voice/clip1.wav … clip5.wav` (16 kHz mono WAV is fine): "Hi, where is my order
   4512?", "My order 4512 is a week late, I want my money back", "The speaker from order 4507 arrived broken",
   and 2 of your own.
3. For each clip: `python -m scripts.run_voice --audio samples/voice/clipN.wav --out out/replyN.wav`.
   Copy the "Heard", "Ticket" and timing lines into this table, and listen to `out/replyN.wav`.

## 4. Problems
- **pyttsx3 + espeak write the .wav after `runAndWait()` returns.** The first measurement showed 0.01 s and one
  missing file out of three. `speak()` now waits until the file exists and its size is stable (up to 10 s).
  After the fix: 10/10 files written.
- **Platform dependence:** pyttsx3 on Linux needs `espeak-ng` (a system package, not pip). Its voice is robotic
  compared with Windows SAPI5. Fine for the demo PC (Windows), weak for a cloud server.
- `transcribe` uses the `.wav` header for `audio_seconds`; for other formats it falls back to the duration Groq returns.
- An earlier, wider build (web page, browser microphone, Piper voices, faster-whisper, Docker) was made before this
  task file was known, on the unpublished branch `feature/multimodal-voice`. It is **not** part of this branch.
  It is kept separately for the integration work (I01), which needs its own approval for the extra libraries.

## 5. Questions for the Brain
1. OK to mark the 3 measurement checks as pending until Semah records the clips on his PC (the code is ready)?
2. The cloud/web version (I01) uses Piper for speech because pyttsx3 needs system voices that cloud servers lack.
   Keep pyttsx3 for the CLI and Piper for the web channel, both switchable in `config.yaml`?

## 6. Next step
Semah records the 5 clips with a Groq key and fills in the 3 pending checks. Then review of `feature/voice`, and
the I01 integration on top of it.
