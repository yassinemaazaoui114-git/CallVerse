# I01 compliance review — Voice V01 + Integration I01 vs the approved instructions

Sources: `tasks/V01_voice_channel.md` + `tasks/NEXT_VOICE.md` (approved by Yassine, 2026-10-20; provided by Semah,
not yet in the repository before this work), `ONBOARDING.md` (provided by Semah), `CLAUDE.md`,
`tasks/I01_integration_platform_voice.md` (Git approval relayed by Semah).
Classes: **MUST FIX** (required) · **APPROVED EXTENSION** (authorized by I01) · **NEEDS APPROVAL** (not covered).

## A. Voice V01 (`tasks/V01_voice_channel.md`)

| # | Requirement | Before review | Now | Class | Evidence |
|---|---|---|---|---|---|
| 1 | Branch `feature/voice` from latest `main`, pushed, no merge | only local `feature/multimodal-voice` | **`feature/voice`** from main 22aa220, commit 69cb044, pushed | MUST FIX → done | `git ls-remote`: refs/heads/feature/voice = 69cb044 |
| 2 | STT = Groq `whisper-large-v3-turbo`, OpenAI-compatible endpoint, `GROQ_API_KEY` | web STT only (bytes) | `callverse/channels/voice.py` `transcribe()` | MUST FIX → done | `test_transcribe_with_fake_client` |
| 3 | TTS = `pyttsx3` | Piper only | `speak()` with pyttsx3, rate from config | MUST FIX → done | `test_speak_with_fake_engine`, `test_speak_real_pyttsx3` (real engine, espeak-ng) |
| 4 | `transcribe(audio_path) -> {text, language, audio_seconds, seconds}`; `speak(text, out_path) -> {out_path, seconds}` | missing | exact keys | MUST FIX → done | key sets asserted in tests |
| 5 | `config.yaml` `voice: {stt: {provider: groq, model: whisper-large-v3-turbo}, tts: {engine: pyttsx3, rate: 170}}` | other schema | exact section; the web settings moved to `web_channel:` | MUST FIX → done | `test_voice_config_section` (exact dict) |
| 6 | `scripts/run_voice.py --audio`: STT → Intake → Agent A (pipeline once T04 is in main, one function) → `out/reply.wav` | missing | `respond()` calls `callverse.pipeline.handle()` (T04) | MUST FIX → done | `test_run_voice_flow_with_fakes`; live run stops cleanly without a key |
| 7 | 5 clips of Semah's voice + checks (order number x/y, main reason x/5, STT time, TTS time, reply plays) | synthetic clips only | TTS time measured (Linux espeak: 0.076 s average, 10 replies). **The other checks are PENDING**: they need Semah's voice and a Groq key | PENDING (not fabricated) | `tasks/V01_report.md` §3 |
| 8 | Recordings only in git-ignored `samples/voice/` | not set | `samples/voice/` + `out/` in `.gitignore` | MUST FIX → done | `test_audio_folders_are_git_ignored`; 0 audio files committed |
| 9 | Every STT/TTS call traced `stt_call` / `tts_call`, with duration and seconds | named `stt` / `tts` | V01 + web: `stt_call` / `tts_call` (file name only, no folder) | MUST FIX → done | trace assertions in tests |
| 10 | No change to intake, agents, tools, coordinator, platform, `llm.py` | respected | respected | OK | diff vs main: none of these files |
| 11 | New libraries only `pyttsx3` (+ `soundfile` if needed) | — | V01 adds only `pyttsx3` (`soundfile` not needed: stdlib `wave`) | OK | `feature/voice` requirements diff |
| 12 | `tasks/V01_report.md` (6 sections) + `tasks/NEXT_VOICE.md` WAITING FOR REVIEW | the name was used by the web report | real V01 report on `feature/voice`; web docs renamed **W01** | MUST FIX → done | files on `feature/voice` |

## B. Integration I01 (`integration/platform-voice`)

| # | Item | Class | Status / evidence |
|---|---|---|---|
| 13 | Merge latest `main` (22aa220, T04) with a merge commit, conflicts resolved (config: both; NEXT_PLATFORM: main's) | APPROVED (I01 Git step 1) | merge 91ac9ee |
| 14 | Real T04 router; temporary router removed | APPROVED (I01) | de5d403; `test_routing_uses_the_t04_router` (trace actor `router`) |
| 15 | Web channel (`callverse/web/`: page, browser microphone, identity gate, workflow with real/not-built stages) | APPROVED EXTENSION (I01 "Contents": Voice V01 web work + integration workflow) | tests: `test_web_api`, `test_web_pipeline`, `test_integration_workflow`, browser |
| 16 | P05 platform server + admin dashboard (unreviewed, localhost) | APPROVED EXTENSION (named in I01 "Contents") | `test_server` 15/15; stays on 127.0.0.1 |
| 17 | V01 (`feature/voice`) merged into the integration branch (c0ca4e1); web reads the Groq model from `voice.stt`; web can speak with V01's pyttsx3 (`web_channel.tts.engine`) | NEEDS APPROVAL → **approved (relayed)** | `test_web_tts_can_use_the_v01_pyttsx3_engine` |
| 18 | Extra libraries of the web channel: `faster-whisper`, `av<16`, `piper-tts` (GPL-3.0 engine), `python-multipart` | NEEDS APPROVAL → **approved (relayed)** | `requirements-voice.txt` |
| 19 | Deployment files: `Dockerfile`, `.dockerignore`, `deploy/huggingface/README.md` (nothing deployed) | NEEDS APPROVAL → **approved (relayed)** | files only |
| 20 | New files outside V01's allowed folders (`callverse/web/`, `callverse/integration/`, `docs/*`, README section) | APPROVED EXTENSION for web + integration (I01); docs follow | — |
| 21 | Lane files: `NEXT.md` / `NEXT_PLATFORM.md` untouched (NEXT_PLATFORM = main's version); `NEXT_VOICE.md` WAITING FOR REVIEW (from V01) | OK | diff vs main |

## C. Unresolved exceptions
- **V01 measurements (item 7):** pending until Semah records the 5 clips with a Groq key (steps in `tasks/V01_report.md` §3).
- **Items 17–19:** approved by Yassine on 2026-10-20 (relayed by Semah, not verified on GitHub); `integration/platform-voice` is published as one PR to `main`, not merged.
