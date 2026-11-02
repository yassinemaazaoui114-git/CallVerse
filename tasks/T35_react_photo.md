# T35 — Photo upload in the React Help chat (ShopNova + Atlas, port 5173)

## Why
Audit (Brain, 2 Nov 22:15 UTC, main 01a1836): vision is merged in the back end (`callverse/vision`,
`web_chat.send(image=...)`), but the React UI used for the demo has no photo upload: `webui/api/app.py` `ChatIn` has
no image field and `webui/frontend/src/screens/Chat.jsx` has no file input. A photo works only in the Streamlit Help
chat (8501/8503) and Molka's voice site (8080). Yassine approved the fix (2 Nov 22:14: "fix it in the react").

## Design choice (Brain ⭐, approved with the task)
- ⭐ **Base64 photo inside the existing JSON send** (`ChatIn.image_b64: str | None`), decoded in the API, passed to
  `web_chat.send(image=bytes)`. Reason: no new package (multipart would need `python-multipart`), the SSE job flow,
  client_id dedupe and tests stay the same. Cost: ~33% larger request; fine under the 5 MB limit.
- Not chosen: a separate multipart upload route (new dependency, a second job path).

## Hard limits
- Branch `feat/t35-react-photo` (the Brain created it from main 01a1836; continue on it). Claude Code never merges into
  main. **Dali's OK is needed before the merge** (his UI, `webui/`): list it in the report.
- No change to agents, prompts, Coordinator rules, `callverse/vision/*` or `config.yaml`. Only: `webui/api/*`
  (field, decode, validation, pass-through), `webui/frontend/src/*` (file input, preview, send), their tests, docs.
- The photo is **never stored** (same rule as the channel): not in the tickets DB, not in the job registry after
  the run, not in traces, not in logs. The saved user message shows `[Photo attached]` (the channel already does this).
- Same limits as the channel: JPEG / PNG / WebP only, at most 5 MB (`vision` config / `PHOTO_ERROR_REPLY`); one photo
  per message; a photo with no text is allowed (the channel handles it). Validate size and type in the API first
  (400 `photo_too_large` / `photo_type`) before starting a job.
- client_id dedupe: the payload compared for a retry must include a hash of the photo (sha256), never the bytes.
- No new npm or Python packages. Never read `.env`. No force push.
- RAM (7.7 GB PC): run the live check with only the React UI + API + Ollama open (no Streamlit apps, no browser tabs
  besides one). The first photo loads the vision model (~25 s, ~2.2 GB VRAM).

## What to do
0. Write `tasks/T35_progress.md`, set NEXT.md IN PROGRESS (WIP protocol: commit + push after each step).
1. API (`webui/api/app.py`, `webui/api/chat.py`): `image_b64` on `ChatIn`; decode + validate (type by magic bytes,
   size); allow empty text when a photo is sent; pass `image` through the Job to `web_chat.send`; payload dedupe with
   the photo hash; drop the bytes from the Job when it ends. Same for `/api/atlas/chat` (shared `register_chat`).
   Tests in `webui/api/tests/test_chat.py`: photo passed to the channel (fake send), too large, wrong type, photo-only
   message, same client_id + same photo = same job, + other photo = 409.
2. Frontend (`Chat.jsx`, both companies): a paperclip/photo button next to the input (`accept="image/jpeg,image/png,
   image/webp"`), a small preview with a remove ×, client-side size check (5 MB) with a plain error text, send as
   base64 with the message, disabled while a send runs. Keep the existing tokens/styles (`ui-ux-pro-max` plugin OK).
   Vitest: choose a photo → preview → send body has `image_b64`; too big → error, nothing sent; remove → not sent.
3. Full suite (Python + `npm test`) green; `npm run build` OK.
4. Live check (once, local models): sara, ShopNova, message `My order 4509 arrived damaged, see the photo. I want a
   refund.` + a cracked-phone photo; and one Atlas photo message. Record what the chat shows (photo_check step,
   reply, outcome; T34 expected: photo seen, case passed to a colleague, no refund written) and RAM/VRAM peak.
   Also one message with NO photo: same as before (no regression).
5. Docs: README (one line), `docs/DEMO_RUNBOOK.md` (photo step now in the React chat).
   Report `tasks/T35_report.md` (CLAUDE.md format), NEXT.md
   WAITING FOR REVIEW, push.

## Time box
1.5 hours. The report lists the merge line for Yassine (Brain review + Dali's OK first).
