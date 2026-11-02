# UI replacement — step 3 report (for Yassine)

Branch `feat/ui-react` · after the step-2 correction commit `1cab8c9` · folder `webui/` · 2026-11-01 · Dali's lane.
`callverse/` unchanged, Streamlit apps unchanged, no merge into `main`. No admin approvals, Atlas or dashboard.

## 0. Step-2 correction (its own commit, `1cab8c9`)

Both order routes now answer 503 `setup_required` when the configured `shopnova.db` is missing, checked after
the role check and before any read function runs (so `db.connect()` can no longer seed a file during a
request). The screens show "ShopNova's data is not set up on this PC" with Retry. Tests: 503 on both routes
and the file still absent; a non-customer still gets 403; the Console routes answer 200 / 404 without the
shop file and never create it. Step-2 report updated.

## 1. In plain words

A ShopNova customer can now really chat with CallVerse from the new UI. Each message goes through the
existing web chat channel (the same door the Streamlit app uses: ticket rule, quota check, identity check,
the pipeline, the saved reply), running in a worker thread so the rest of the API stays responsive. While it
works, the browser shows the channel's own live texts ("Reading your message…", "Checking your order…", …)
over a Server-Sent Events stream; when it is done the screen reloads the conversation as it was saved.
"Ask about this order" now opens the chat with that order as context. If the connection drops, nothing is
sent again: the screen says the request may still be running and lets the customer check and re-attach.
A second click or a retry never runs the channel twice. "New chat", the ticket status, the "New reply on
T-00NN" notices and the busy / quota message work like in the Streamlit page. All screens were checked with a
clearly marked fake channel (every reply starts with `[TEST DATA]`); no Groq quota was spent.

## 2. Done

- **Backend** `webui/api/chat.py` + routes in `app.py`: `Job` / `Registry` (latest job per customer, kept
  15 min), `run_job` (the worker: `web_chat.send(user_id, company, text, ticket_id, on_step, about_order)`
  with user id and company from the account), `stream()` (SSE frames `job`, `step`, `done`, `error`, `: ping`
  every 15 s). Routes: `GET /api/shop/chat`, `POST /api/shop/chat/send` (returns the stream), `GET
  /api/shop/chat/job`, `GET /api/shop/chat/job/stream`, `POST /api/shop/chat/tickets/{id}/read`. Validation
  before any stream: login, ShopNova customer, shop data present, non-empty text ≤ 2000, the ticket must be
  this customer's **and** ShopNova's (`store.get_ticket`), the order must be this customer's
  (`shop_reads.user_orders`). Duplicate rules: 409 `busy_user` while a job runs; the same `client_id` = the same
  job (no second run), also after it finished. CSRF header kept on every POST. The channel is imported lazily
  on the first send (`send_fn()`), never at API import. Existing ticket-store functions only (`get_ticket`,
  `messages`, `current_ticket`, `unread_tickets`, `set_unread`); no SQL, no pipeline logic copied.
- **Frontend**: `src/sse.js` (fetch-based SSE reader with chunk buffering), `screens/Chat.jsx` (conversation
  read back from the store, order context chip, live steps, Send disabled while a job runs, outcome as text,
  busy note, "still working" on load with Follow progress, "Connection lost… NOT sent again" with Check
  status, failed request box, New chat, unread notices with server-side mark-read, Enter sends), "Ask about
  this order" → `/shop/chat?order=N`, "Help chat" in the ShopNova menu, chat styles on the ShopNova theme.
  `api.js`: `chatSend` / `chatJobStream` return the raw Response for the reader.
- **Demo fixture**: `dev_fixture.fake_send` + `CALLVERSE_WEBUI_FAKE_CHAT=1` (replies marked `[TEST DATA]`,
  "busy" / "slow" / "fail" words to try the states). Documented as never for a real demo.
- **Tests**: `webui/api/tests/test_chat.py` (14, fake channel; three of them on a real uvicorn server because
  Starlette's TestClient delivers a streaming body only when complete), `src/test/sse.test.js` (3),
  `src/test/Chat.test.jsx` (8). README: transport and recovery section.

## 3. Numbers / evidence

| Check | Result |
|---|---|
| `python -m pytest webui/api/tests -q` (steps 1–3) | **39 passed** (15 + 10 + 14) |
| `npm --prefix webui/frontend test` (steps 1–3) | **24 passed** (7 + 6 + 11) |
| `npm --prefix webui/frontend run build` | OK, JS 218.2 kB (68.5 kB gzip), CSS 19.2 kB |
| Successful send: events `job, step×3, done`; user + assistant messages and ticket status read back | passed |
| Order context (`about_order`) and ticket continuation (`ticket_id`) reach the channel | passed |
| youssef on sara's ticket / order, sara on an Atlas ticket of user id 1, hedi / admin / supervisor, no login, no CSRF header, empty / too long text | 404 / 404 / 404 / 403 / 401 / 403 / 400; the channel ran only for the owner |
| Same `client_id` twice while running and after: one channel run; another `client_id` while running: 409 | passed (live server) |
| Disconnect after the first step: job still `running`, conversation shows the user message only, re-attach replays `step×3` then `done`, reply saved; channel ran once | passed (live server) |
| Busy outcome: `done` with `outcome: busy` (no error event); worker exception: `error` event, job `failed`, next send allowed; unknown outcome `ask_proof_photo_v2` passed through; 401 after logout on job / chat | passed |
| Console `GET /api/console/tickets` answers in < 2 s while a chat job is held running | passed (live server) |
| SSE reader: frame split over two chunks, several frames in one chunk, CRLF, comments, final frame without blank line, dropped connection keeps earlier events | passed |
| Chat screen: live labels from the stream while sending, Send disabled, stream closed without `done` → "Connection lost" (no fake success); reply read back after `done`; unknown outcome as text; busy note; Check status → job → re-attach → reload with exactly one send; error event and 409 shown with their words; running job on load disables Send; unread notice opens the ticket and POSTs read; 401 while sending shows no reply | passed |
| Browser (fake channel, desktop): "Ask about this order" → chat with "About order 4512" chip and the current ticket; send → live steps (screenshot 30) → `[TEST DATA]` reply + "Outcome: approve · ticket Solved" (31); New chat → "busy please" → the busy note (32); "slow" message, page reloaded mid-run → "CallVerse is still working on your last message" (33) → Follow progress replays the steps (34) → reply read back, one send | ✔ |
| Browser, phone 375×812: chat idle and while sending, `scrollWidth` 375 = `clientWidth` (35, 36) | ✔ |
| Real model calls / Groq quota during tests and the browser check | none (fake channel everywhere; `llm.chat` patched to fail in the API tests) |

## 4. Problems

- **Jobs are in memory, and the worker is a daemon thread.** A browser disconnect leaves the worker running;
  stopping the API process does not: the thread dies with the process and the message being handled is
  interrupted. Only what the channel had already persisted in `callverse.db` is guaranteed to survive a
  restart (the user message and the steps saved so far; the reply only if the channel reached it). The job's
  progress record and its duplicate-protection record are lost too, so a resend after a restart is a new
  run. Fine for a one-PC demo; not a guarantee that every in-flight reply survives.
- **One stream consumer at a time per job is not enforced**: two tabs can both attach; each gets the events.
  Harmless, but the `busy_user` rule is per customer, not per tab.
- **The "disconnect" in the browser was a page reload** (the real-network drop was tested in the API tests and
  the screen tests with a cut stream); the screens' words were checked both ways.
- The channel's own lock means the whole center handles one message at a time: a second customer sending at the
  same moment waits inside the worker (no error, just a longer "Sending…"). Not changed (locked decision).
- Not verified in the browser: a worker exception (the "fail" word of the fake channel; covered by API + screen
  tests) and the 409 box (screen test).

## 5. Questions for the Brain

1. Should a message survive an API restart (persist the job and its `client_id` on the ticket and let a
   restarted API re-run or resume it)? Today an in-flight message is interrupted by a restart; only what was
   already written to the store survives.
2. The chat's `GET /api/shop/chat` uses `store.current_ticket` (the latest continuable ticket) when no ticket
   is named, like the Streamlit page after a reload. Keep, or always start a new conversation on load?
3. Step 4 (admin approvals) will call `approvals.decide(approval_id, admin, approve, reason)`: plan is
   `POST /api/admin/approvals/{id}/decide` behind `check_permission("approve_refunds", company)`. OK?

## 6. Next step

Step 4 of the brief: ShopNova admin approvals (approve / reject with a reason, the admin queue, Layer 3 kept).
After your review of this step.

## 7. Correction pass (second step-3 commit)

Asked by the Brain after review. Changes under `webui/` only; `callverse/` unchanged.

1. **Duplicate protection.** `chat.Registry` now keeps two indexes: `_by_client[(company, user id, client_id)]`
   for the whole 15 min retention window, and `_current[(company, user id)]` (the running / latest pointer).
   A `client_id` is bound to its payload (`text`, `ticket_id`, `about_order`): same id + same payload = the
   same job, whatever came after it (A → B → replay A finds A, no third run); same id + another payload =
   409 `client_id_reused`. Finished records expire after `KEEP_SECONDS`; the index is bounded to 500 records,
   oldest finished first, a running job never dropped.
2. **Request identity in the browser.** `Chat.jsx` keeps the uncertain submission as `pending`
   ({clientId, text, ticketId, aboutOrder}). A new message always gets a new id; "Resend the same message"
   re-posts exactly the pending payload with its id; while a submission is uncertain (stream cut, or
   409 `busy_user`) Send is paused and the screen offers Check status / Resend / Discard, so typed text is
   never a silent retry. A server-reported failure (error event, refusal) ends the submission: the next message
   is a new one.
3. **Stream lifecycle.** Every stream (send or recovery) has a sequence number and an `AbortController`;
   events and ends of an older stream are ignored (no state, no URL change). Streams are detached on unmount
   (navigation, logout, session expiry), on a conversation change (`?ticket=`), on New chat and before any
   new stream. Detaching aborts the reader only; the server's job goes on. `recovering` guards Check status:
   repeated clicks make one job request and one stream.
4. **SSE parsing.** `sse.js` normalises CRLF and lone CR, holding a trailing CR until the next chunk (CR and
   LF in different chunks), accepts an `AbortSignal` (cancels the reader, rejects with `AbortError`) and always
   releases the reader's lock. Progress and completion events stay separate.
5. **Restart claim corrected** in section 4, question 1 and the README: a browser disconnect leaves the worker
   running; terminating the API kills its daemon worker; only persisted data survives.

**Regression tests**: API — A → B → replay A runs the channel twice and replays A's events; same id with another
text / ticket / order → 409 and no run; registry expiry and bound (oldest finished dropped, running kept).
Frontend — new text after a failure gets a new id and shows its own result; uncertain submission pauses Send and
Resend reuses the exact id + payload; navigating away during sending drops the late `done` (no reload, no
redirect); navigating away during recovery drops the late `done`; repeated Check status = one job request and one
stream; SSE CRLF split at every one of the frame's chunk boundaries, three-chunk and lone-CR variants; abort
cancels the reader, releases the body, keeps the events already delivered.

**Results**

| Check | Result |
|---|---|
| `python -m pytest webui/api/tests -q` | **42 passed** |
| `npm --prefix webui/frontend test` | **32 passed** (6 files) |
| `npm --prefix webui/frontend run build` | OK, JS 220.3 kB (69.2 kB gzip) |

Not re-checked in the browser this pass (the fake-channel browser checks of section 3 were done before the
correction; the corrected paths are covered by the tests above).
