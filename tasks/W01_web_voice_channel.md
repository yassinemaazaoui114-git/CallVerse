# W01 — Web voice + text customer channel (Semah's lane; extension of V01, part of I01)

> Renamed from "V01" to **W01** so it does not clash with the approved task `tasks/V01_voice_channel.md`
> (CLI voice channel, branch `feature/voice`). Built before that task file was known, on the local branch
> `feature/multimodal-voice`; it reaches GitHub only as part of I01. Its extra libraries need approval (I01 report).

## Why
Customers must be able to type **or speak** to CallVerse and hear the answer. Voice must be a channel
adapter (same business logic as text), fully cloud-hostable, with no paid service.

## Hard limits (respected)
- No change to agents, `llm.py`, tools, registry, data, intake, Coordinator, `main` or other branches.
- No RAG, no new business rules. Facts only from Agent A's read tools; MOCK mode reads nothing.
- The spoken audio is made from exactly the displayed reply (fixed pronunciation pass only).
- No secrets in files; no admin routes in the public app; no raw audio stored.
- New libraries only in `requirements-voice.txt` (core `requirements.txt` unchanged):
  fastapi, uvicorn, python-multipart, httpx, faster-whisper, av (<16), piper-tts.

## Done when
- Text and voice turns work in a browser (desktop + mobile), with transcript, reply, audio, replay.
- REAL (Agent A + identity check) and MOCK modes; MOCK clearly labelled.
- All old tests pass; new unit, API, speech and browser tests pass; Docker image runs.

## Git (TO BE APPROVED BY YASSINE)
- Commit on branch `feature/multimodal-voice` (from `main` fb187b5): all files listed in `tasks/W01_report.md`.
- Push `feature/multimodal-voice`; open a PR to `main` for review. **Do not merge.**
