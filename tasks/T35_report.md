# T35 report — Photo upload in the React Help chat (ShopNova + Atlas)

Branch `feat/t35-react-photo` (from main 01a1836). Not merged.

## 1. In plain words
The web Help chat (port 5173) now has a **Photo** button for ShopNova and Atlas customers. The customer picks one
photo, sees a small preview (with a × to remove it), and sends it with the message. A photo with no text works too.
The screen refuses a photo that is too big (over 5 MB) or of the wrong kind, and the server checks again before
anything runs. The photo goes to the same photo check as in the Streamlit chat, and it is never saved anywhere: the
conversation shows "[Photo attached]". One problem from T34 is now visible: while a photo message is handled, the
chat shows only "Sending…" and no live steps (details in Problems).

## 2. Done
- **API** (`webui/api/chat.py`, `webui/api/app.py`):
  - `ChatIn.image_b64` (optional). The browser's `data:image/...;base64,` form is accepted.
  - `chat.decode_photo`: base64 decode, then a size check (at most `MAX_PHOTO_BYTES` = 5 MB, the same as
    `callverse/vision/model.py`). The type comes from the first bytes of the file (JPEG / PNG / WebP), not from the
    browser. A refused photo gets 400 `photo_too_large` or `photo_type` **before** any job starts.
  - Empty text is allowed when a photo is sent. `empty_text` now says "Please type a message or add a photo."
  - The `Job` holds the bytes only while the run lasts. `run_job` passes `image=` to `web_chat.send` and then drops
    the bytes (also when the run fails). With no photo, the channel is called exactly as before (no `image` argument).
  - The duplicate rule: a `client_id` is now bound to (text, ticket, order, **sha256 of the photo**). Same id + same
    photo = the same job. Same id + another photo (or no photo) = 409 `client_id_reused`.
  - `GET .../chat/job` shows `has_photo` (true / false), never the photo.
  - Atlas gets all of this too, because both companies share `register_chat`.
- **Frontend** (`webui/frontend/src/screens/Chat.jsx`, `components/Icon.jsx` new `image` icon, `styles/themes.css`
  `.photo-preview` / `.photo-error` with the existing tokens):
  - A hidden file input (`accept="image/jpeg,image/png,image/webp"`) and a **Photo** / **Change photo** button.
  - A preview (56 px thumbnail, file name, × "Remove the photo").
  - A check on the screen first: the type and 5 MB. If it fails, a plain error text is shown and nothing is sent.
  - The photo is sent as `image_b64` with the message. While a send runs, the button and × are disabled. The photo is
    cleared once the server accepts the send. It is kept with the pending send, so "Resend the same message" resends
    the same photo with the same id. "New chat" clears it.
- **Tests**:
  - `webui/api/tests/test_chat.py`: 7 tests. The photo reaches the channel and is dropped from the job. A finished or
    failed job holds no bytes. With no photo, the call is the same as before. A photo-only message works, but empty
    text with no photo is refused. Too large, wrong type and not-base64 are refused, and no job starts. The limit is
    the same as the vision model's. Same id + same photo = one run; another photo = 409.
  - `webui/api/tests/test_atlas.py`: 1 test (the Atlas route passes the photo and refuses a GIF).
  - `webui/frontend/src/test/ChatPhoto.test.jsx`: 5 tests. Choose → preview → `image_b64` in the body, then cleared.
    Photo only. Too large or GIF → error and nothing sent. Remove → not sent. Atlas route.
- **Docs**: README (T35 line), `docs/DEMO_RUNBOOK.md` (the photo step is now in the web UI, with the live numbers).

## 3. Evidence
- Python: `python -m pytest -q --ignore=tests/data` → **2011 passed, 5 skipped** (main: 2003; +8 new). webui API alone 132 passed.
- Frontend: `npm test` → **82 passed / 14 files**. `npm run build` OK (318.7 kB JS).
- **Live check** (2 Nov, 23:27): the real API (`python -m webui.api.run`, port 8611, a temporary accounts file and
  tickets DB in the scratchpad; the demo tickets were not touched). Local models: `callverse-m2-v3`, `qwen2.5:1.5b`,
  and vision qlora nf4. The script sent **the same JSON the React screen sends** (login, then `POST .../chat/send`
  with `image_b64` as a data URL, then the SSE stream read to the end). The photos are T34's real dataset photos
  (`out/t34_photos/`, checked by sha256 in T34).

  | # | Account | Message | Photo check (saved `photo_check` step) | Result | Time |
  |---|---|---|---|---|---|
  | L1 | sara (ShopNova) | `My order 4509 arrived damaged, see the photo. I want a refund.` + cv001 cracked phone | smartphone, cracked_screen, damage yes | **escalate** ("…passed on for review"), ticket Escalated, nothing written. Same as T34 P1 | 69.8 s (model load included) |
  | L2 | nizar (Atlas) | `My suitcase arrived broken after my flight, booking 7004. See the photo.` + cv057 | "washing_machine", damaged_room_fixture, damage yes (wrong object, as in T34) | **decline** (refund rule for 7004: 3 h 15 late < 5 h), nothing written. Same as T34 P3 | 20.9 s |
  | L3 | amira (ShopNova) | `Hi, where is my order 4511?` (no photo) | — | info "Hello, your order 4511 is being prepared." 3 live steps, 13 steps saved. **Same as before** | 9.8 s |

  - Saved user messages: `…\n[Photo attached]`. `job.has_photo` = true / true / false.
  - **The photo is not stored anywhere I checked.** I searched for a piece of each photo's base64 and for the word
    `image_b64` in the tickets DB, the API log and both trace files of the run. None was found.
  - Memory (sampled every 3 s, 28 samples): **VRAM peak 5887 MiB** (of 6 GB). **Free RAM low point 0.11 GB**.
    Ollama, the API and the vision model were running; no Streamlit, no Vite.
  - Not done live: a click in a real browser on 5173. With only 0.11 GB of RAM free, a browser would have pushed the
    PC over its limit. The click path is covered by the Vitest tests. The live check covers the API and the channel.

## 4. Problems
1. **No live steps, and no saved pipeline steps, for a photo message** (bug from T34, in
   `callverse/channels/web_chat.py`, outside this task's scope, **not fixed**). `channel_step("photo_check", …)` calls
   `flush()`. `flush()` removes the trace listener (`trace.remove_listener(listen)`) **before** the pipeline runs. So
   for every message with a photo:
   - the chat shows only "Sending…" for 20–70 s (L1, L2: 0 live steps);
   - the ticket keeps only the `photo_check` step. Intake, route, agents, Coordinator and SLM are not saved, so the
     Console's "What was done" is almost empty. The trace file still has all of them.

   The same happens in the Streamlit chat. Fix idea (2 lines): in `channel_step`, add the listener back after the
   step is saved, or save the photo step without calling `flush()`.
2. Memory is very tight with a photo: 5.9 GB of 6 GB VRAM and 0.1 GB free RAM. T34 saw the same. For the demo, close
   everything else.
3. The base64 request is about 33% bigger than the file (a 5 MB photo is about 6.7 MB of JSON). This is fine on
   localhost.
4. The Atlas suitcase photo is still labelled "washing_machine / damaged_room_fixture" (a model limit, as in T34).
   The decision comes from the refund rules, so the result is not changed by it.

## 5. Questions for the Brain
1. Problem 1: may I fix `web_chat.channel_step` in a small follow-up task (T35b)? It is a 2-line change plus a test
   that checks a photo message shows live steps and saves its pipeline steps. It is outside T35's allowed files, so I
   did not touch it.
2. **Dali's OK is needed before the merge** (`webui/` is his area): the API field, `Chat.jsx`, the icon and the CSS.

## 6. Next step
After the Brain's review and Dali's OK, Yassine merges:
```
git checkout main && git pull && git merge --no-ff origin/feat/t35-react-photo && git push
```
Then run the tests on main (Python + `npm test`), and set NEXT.md to DONE. Then I suggest T35b (Problem 1) before the demo.
