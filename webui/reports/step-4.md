# UI replacement — step 4 report (for Yassine)

Branch `feat/ui-react` · after the step-3 correction `e77ba72` (verified: API 42, vitest 32 before starting) ·
folder `webui/` · 2026-11-01 · Dali's lane. `callverse/` unchanged, Streamlit apps unchanged, no merge into
`main`. No Atlas screens, no dashboard.

## 1. In plain words

The ShopNova admin can now handle the refund queue in the new UI: see the refunds waiting for finance with the
order's facts (client, amount, rule, paid, already refunded, days late, the agent's facts), approve or refuse
with a reason after a confirmation that repeats exactly what will be decided, and see the decided ones with
who decided, when and why. The decision itself is still made by the core function the Streamlit page uses
(`approvals.decide`): the pending check, the "reason required to refuse" rule, the Coordinator's re-check on
fresh data, the single write transaction, the new reply to the customer and the "New reply" notice are all its
own; the API only passes the three things the admin chose (which approval, approve or refuse, the reason) and
adds the admin's name from the account file. A double click, a lost answer or two admins at once cannot pay
twice: the core refuses a second decision inside its transaction, and the API reads the recorded state back
instead of sending again. Checked in the browser with a fake reply writer (no model, replies marked test data).

## 2. Done

- **API** `webui/api/admin.py` + routes: `GET /api/admin/approvals?status=pending|decided` (ShopNova rows from
  `store.approvals(..., company="shopnova")` + `admin_reads.approval_facts` + the proposal row, like the
  Streamlit page), `GET /api/admin/approvals/{id}` (the recorded state; an Atlas or missing id → 404),
  `POST /api/admin/approvals/{id}/decide` `{approve, reason, client_id?}`. Guard `shopnova_admin` =
  `accounts.check_permission(session, "approve_refunds", "shopnova")` (customers, Atlas admin, supervisor,
  no login → 403 / 401); CSRF header required on the POST. Before deciding: the approval is re-read (404 /
  409 `already_decided` with who and when), the reason rule is applied, a per-approval in-flight guard refuses a
  concurrent request (409 `decision_in_progress`), then `decide(approval_id, username, approve, reason,
  slm_chat_fn, company="shopnova")` runs in FastAPI's worker thread (plain `def` route: the event loop stays
  free). The result is recorded under `client_id` for 15 min, so the same request asked again returns the
  recorded result instead of running. `decide()`'s error dict is mapped: re-check refused → 409
  `recheck_refused` (the approval stays pending, the Coordinator's words shown), not found → 404, already →
  409, reason → 400, anything else → 409 `write_refused`. The channel is imported lazily (the Console process
  never loads it: checked in a fresh subprocess by the step-1 test).
- **Frontend**: `screens/AdminApprovals.jsx` (Waiting / Decided tabs, cards with facts and the `proof_received`
  field when the proposal carries it, reason input, Approve / Refuse → confirmation dialog with approval id,
  order, ticket, amount, choice, reason → one submission at a time, result box with outcome / ticket status /
  refund written or nothing paid, queue refreshed; refused re-check, already decided, API failure, uncertain
  result with "Confirm again" using the same request id, denied access, empty, loading). ShopNova admin area in
  the shell ("ShopNova admin", Refund approvals), login home `/admin/approvals` for the ShopNova admin
  (Atlas accounts still go to the workspace page). `dev_fixture.fake_slm` for the demo without Ollama.
- **Tests**: `webui/api/tests/test_admin.py` (9, real `decide()` with a fake reply writer on a seeded temp
  shop database in queue mode, pending approvals built the way the core's own tests build them) and
  `src/test/AdminApprovals.test.jsx` (6). Step-1 test `test_reads_write_nothing_and_load_no_model` now checks
  the API's imports in a fresh subprocess (the chat and admin tests load the pipeline on purpose in the shared
  test process).

## 3. Numbers / evidence

| Check | Result |
|---|---|
| `python -m pytest webui/api/tests -q` (steps 1–4) | **51 passed** |
| `npm --prefix webui/frontend test` (steps 1–4) | **38 passed** (8 files) |
| `npm --prefix webui/frontend run build` | OK, JS 230.3 kB (71.7 kB gzip) |
| sara, hedi, supervisor, atlas_admin, no login on the 3 routes and the POST; POST without CSRF header | 403 / 401 / 403 |
| lists: one ShopNova pending + one Atlas approval row → list has the ShopNova one only, with facts (rule, paid, user, facts_used); Atlas id → 404 on GET and POST; `status=weird` → 400 | passed |
| approve: `decide()` called with `admin="admin"`, `company="shopnova"` from the account; refund 378 TND written, order 4515 refunded, ticket Solved; youssef's chat shows the unread notice and the new assistant reply; decided list shows the reason | passed |
| refuse: blank reason → 400 and still pending; with reason → `layer3_refused`, no refund, reason stored; reason > 1000 chars → 400 | passed |
| already decided → 409 with "by admin"; concurrent: two POSTs on one pending approval while `decide()` is held → one 200, one 409 `decision_in_progress`, `decide()` called once | passed |
| re-check refused (patched `recheck`) → 409 `recheck_refused`, still pending, no refund; same request id again re-runs the check (an error is not a recorded decision); refusing still possible | passed |
| lost response: same `client_id` again → the recorded result (`recorded: true`), `decide()` ran once; without the id → 409 already decided; GET state says approved by admin | passed |
| worker exception → 409 `write_refused` with the exception name, guard released, a later decision works; unknown outcome `approve_with_proof_pending` passed through | passed |
| Browser (fake reply writer, desktop): login as admin → Refund approvals (2 pending with facts, screenshot 40); approve approval 2 with a reason → confirmation (41) → "Approval 2: approved · ticket T-0008 is now Solved · refund 378.00 TND written" and Waiting (1) (42); Decided tab shows admin, simulation time, reason, proposal decision (43); approval 1 (a fixture row whose proposal was decided by the other case) → the core's "proposal P-0001 is already decided: approve", nothing written, still pending (44) | ✔ |
| Browser, phone 375×812: queue and confirmation dialog, `scrollWidth` 375 = `clientWidth` (45, 46) | ✔ |
| Real money / Groq | none: temp databases, fake SLM, `llm.chat` patched to fail |

## 4. Problems

- **Cross-process safety is the core's, not the UI's.** Two processes (this API and the Streamlit app) can both
  pass `decide()`'s pending check (its lock is per process), but `writes.admin_decide_refund` decides the
  proposal inside one `BEGIN IMMEDIATE` transaction and refuses an already decided proposal, and
  `close_approval` only closes a pending row: the loser gets "already decided", nothing is paid twice. The
  API's in-flight guard and recorded results only cover this process. No core change needed for money; the
  loser's customer reply is simply not written twice either (the write failed before the reply step).
- **The demo fixture's approval 1** (from step 1) points at a proposal id that the real seed does not own; it
  now serves as the "core refuses, nothing written" example. Not a product case.
- **Recorded results are in memory** (15 min, this process): after an API restart a retry with the old
  `client_id` gets 409 `already_decided` with who / when, which is still a correct, non-repeating answer.
- `decided_at` is the simulation clock (the core's choice); the screen labels it so.
- Not verified in the browser: a lost answer (covered by the screen test: the recorded state is read, the same
  request id reused), concurrent clicks from two tabs (API test).

## 5. Questions for the Brain

1. The decided list reads `approval_facts` for every row (tracking + refunds reads per row). Fine for a demo;
   should the API cap the decided list (e.g. last 50) for later?
2. Should the admin see the customer reply text after a decision? `decide()` returns it; the screen shows
   only the outcome and the ticket status today (the reply belongs to the customer's chat).
3. Step 5 (Atlas): the same queue serves Atlas (`company="atlas"`, compensations). Plan: reuse these routes under
   an `atlas_admin` guard with `company="atlas"` and `atlas_app_reads` for the facts. OK?

## 6. Next step

Step 5 of the brief: Atlas Travel customer and admin pages. After your review of this step.
