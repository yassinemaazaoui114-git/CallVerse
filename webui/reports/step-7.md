# UI replacement — step 7 report (for Yassine)

Branch `feat/ui-react` · after the step-6 review fixes `de28f86` · folder `webui/` · 2026-11-01 · Dali's lane.
`callverse/` unchanged, Streamlit apps unchanged, no merge into `main`, nothing pushed, nothing deployed.
**This report does not declare the replacement accepted: that is your review.**

## 1. In plain words

Step 7 is the review pass of the whole new UI. First I re-read the step-6 dashboards against the core's own
read functions and fixed what did not match (a satisfaction number labelled as if it were per period, a failed
period change that still presented the old numbers as the new period, the clocks). Then I went through every
account and every flow in the browser, on a desktop window and on a 375 px phone, with the keyboard only where
it matters (the approval dialog), and fixed the reproducible problems: the dialog let Tab escape and then Escape
stopped working; fact lists squeezed their values on a phone. I verified how the chat behaves when the assistant
is busy or the connection drops, with the fake channel: the message is kept, nothing is sent twice, and the busy
state is the channel's own answer, never a guess from the Groq counter. Finally I took the screenshot set,
updated the README and ran everything.

## 2. Flows checked (demo fixture, fake chat, temporary databases)

| Account | Desktop | Phone 375 × 812 | Keyboard / screen reader |
|---|---|---|---|
| `supervisor` | Live tickets, filters, Ticket detail, Dashboard (all / 7 / 30), Agents, Groq today | tickets, detail, dashboard + charts, agents: `scrollWidth` 375 = `clientWidth` on every page | chart `aria-label` lists the values; "Show as table" |
| ShopNova customer (`sara`) | My orders, Order detail, Ask about this order, Help chat (reply `[TEST DATA]`, busy, slow + reload, fail) | checked in steps 3 and 6; components unchanged since | Enter sends, Shift+Enter new line; status messages `role=status`, errors `role=alert` |
| ShopNova `admin` | Refund approvals (pending / decided), approve with reason, result, Dashboard 7 / 30 / 90 | dashboard, approvals, confirmation dialog | Tab / Shift+Tab stay in the dialog, Escape closes, focus back on "Approve" |
| Atlas customer (`hedi`) | My bookings, Booking detail (flight + hotel), Help chat with booking context | chat `?booking=7005`, hotel detail 7001: 375 wide | fact list stacks label / value under 480 px (fix below) |
| `atlas_admin` | Approvals (refund + compensation), Records (5 tables + log, search, paging), Dashboard all / 7 / 30 | dashboard (step 6), records tables scroll inside their panel | period buttons `aria-pressed` |

Screenshots: `webui/reports/screenshots/step-7/` (19 files): `01`–`09` from this pass (supervisor desktop
tickets and detail; supervisor, ShopNova admin and Atlas customer on the phone, the dialog with the keyboard,
the Atlas booking detail **before** the fact-list fix), `desktop_*` = the final desktop state of the chat,
approvals, bookings and the four dashboards (unchanged since steps 3–6, copied here for one index).

## 3. Bugs fixed in this step

Committed in `de28f86` (step-6 review against the core reads):

- **Old-period numbers after a failed refresh** were shown as if they were the selected period's. `useGuardedLoad`
  now reports `isCurrent`; the four dashboards dim the numbers and show `StalePeriodNote` ("Loading X… the
  numbers below are still those of Y" / "X could not be loaded … the numbers below are those of Y").
- **Satisfaction scope**: the Console's satisfaction is `review_avg` of ALL ShopNova reviews on file (any date),
  not of the period; the tile is now "Satisfaction (ShopNova reviews)" with that note, and "no review score on
  file" when there is none.
- **Real vs simulation time**: each dashboard names its clock from the API (`computer time` for the Console,
  `simulation clock` for the companies); none mixes them.
- **Groq units**: shown exactly as the core counts them (tokens today out of the configured daily limit); no
  remaining-quota maths in the browser; the meter value equals the number printed.
- ShopNova dashboard categories use the shop's own names (`CATEGORY_NAMES`); the dialog returns the focus.

In this step's commit (browser / accessibility pass):

- **Dialog keyboard**: Tab could leave the confirmation dialog, after which Escape no longer closed it. The key
  handler is now on the document while the dialog is open: Tab / Shift+Tab wrap inside, a focus that left is
  pulled back, Escape closes (not while a decision is in flight), the opener button gets the focus back. Test:
  "the confirmation dialog keeps Tab inside, closes on Escape and returns the focus to the opener".
- **Fact lists on a phone** (`dl.kv`: booking detail, order detail, approval dialog): a long label left the value
  a few characters wide. Under 480 px the label sits above the value.

## 4. Chat when the assistant is not available (verified with the fake channel)

| Situation | Signal | Screen | Test |
|---|---|---|---|
| Groq daily quota gone / Agent B has no model | the channel's `busy` outcome with `web_chat.BUSY_REPLY` (the ONLY signal; the Console's Groq counter is never read by a customer screen) | normal result, "Our assistant is busy right now … your message is saved", no alert | `test_busy_outcome_is_a_normal_result_not_a_transport_error`; screen test "busy outcome is shown as the assistant being busy" |
| another message of the same customer still running | 409 `busy_user` | draft kept, "A previous message is still being processed", Check status | `test_same_client_id_is_not_run_twice_and_another_send_is_refused_while_running` |
| connection lost mid-stream | stream ends without `done` | "Connection lost", Check status (re-attach, same job), Resend the same message (same `client_id`, answered from the record if finished) | `test_disconnect_then_recover_without_a_second_run`, `test_replay_of_a_after_b_returns_a_without_a_third_run`; screen test "lost connection: Check status re-attaches" |
| worker failure | `error` event | the error's words, no invented reply | `test_worker_exception_is_an_error_event_and_the_job_is_failed` |
| session expired during recovery | 401 | back to login | `test_session_expiry_during_recovery`; screen test "session expiry while sending" |

Supervisor-only numbers (Groq today, tokens per agent) are on supervisor routes only (403 for every other role,
`test_console_routes_need_the_supervisor`).

## 5. Test / build results

| Check | Result |
|---|---|
| `python -m pytest webui/api/tests -q` | **79 passed** |
| `npm --prefix webui/frontend test` | **50 passed** (10 files) |
| `npm --prefix webui/frontend run build` | OK, JS 272.3 kB (81.4 kB gzip), CSS 23.6 kB |
| `git diff main --stat -- . ':!webui'` | nothing outside `webui/` (`.agents/`, `.claude/` untracked, not committed) |
| Real model / real money / `.env` | none, never read |

## 6. Remaining gaps (not accepted yet)

1. **Partial decisions need core work.** When `approvals.decide` raises after the company write (money
   committed, approval row still pending or the customer reply not sent), the UI shows the evidence stage
   (`company_written_approval_pending`, `approval_closed_notification_unconfirmed`) and refuses to replay. Closing
   such a case needs `approvals.finish(approval_id)` in `callverse/` (open since step 4): mark the row decided
   and send the reply without writing the money again. Until then the admin finishes it in the Streamlit app or
   by hand.
2. **Serving `frontend/dist` from the API** is not done: a demo runs two processes (API + Vite, or any static
   server for `dist/`). A few lines in `app.py` if you want one process; not added without your OK.
3. **Screenshot location**: `webui/reports/screenshots/` (brief: `docs/screenshots/`). Copy or move after review.
4. **Satisfaction per ticket** waits for agent F (core). The Console shows the ShopNova review average with a note.
5. **Not checked**: the real chat (Ollama + Groq) through the new UI; a real Groq 429 end to end (only the fake
   `busy` outcome); the Streamlit apps side by side for every number (the dashboards call the same functions, the
   tests compare shapes, not every value); screen-reader software (only roles, names and `aria-*` in the DOM).
6. Minor: the "Tickets per day" chart draws the day totals (per-company split in the table); charts capped at
   560 px wide.

## 7. Acceptance checklist (for your review)

- [ ] Every number on the three dashboards matches the Streamlit page for the same period (spot-check 2–3).
- [ ] Login as each demo account lands on the right home and sees nothing of the other company.
- [ ] A real chat message (Ollama + Groq up) streams steps and ends in the saved reply.
- [ ] An approval decided in the new UI shows the same row and customer reply as in Streamlit.
- [ ] Phone check on a real device (only the emulated 375 px viewport was checked).
- [ ] Decisions on `approvals.finish`, on serving `dist/`, on the screenshot folder.
- [ ] Then: merge of `feat/ui-react` into `main` by you (`!`), tests run again on `main`.

## 8. Next step

Your review of steps 1–7. Nothing is merged, pushed or deployed.
