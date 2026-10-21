# P08 report — Simulation clock + scripted delivery events (for story S3)

## 1. In plain words
ShopNova's time no longer has to stand still. A simulation clock starts on 9 October 2026 at 09:00 and moves
forward only when someone runs `advance_clock.py`. As it moves, a small scripted timeline delivers order 4510:
out for delivery after 24 hours, delivered after 30 hours. "Days late" and the other dates follow the clock. When
the order is delivered, a client who subscribed to that event appears in the list of notifications to send; sending
it is the notifier's job in T09. If nobody moves the clock, everything works exactly as before.

## 2. Done
- **`callverse/data/clock.py`** (new): `start()`, `now()`, `advance(hours)`, `reset()`, `load_timeline()`. The clock is
  stored in the DB (one-row table `sim_clock`; applied timeline events in `sim_timeline_applied`). Both tables are
  created the first time the clock moves, so a freshly seeded DB is byte-identical to before.
- **`callverse/config.py`** (the one allowed core edit): new `sim_start()` (the fixed config date) and `sim_today()`, which
  now returns `clock.now().date()`.
- **No start-up loop** (review note): `seed.py` uses `sim_start()`, never the moving clock. A missing DB file →
  `connect()` → `seed()` works (tested by hand: `sim_today()` on a missing DB returns 2026-10-09).
- **`callverse/data/scenario_timeline.json`** (new, `scripted: true`, `ai_generated: true`): order **4510**,
  `+24 h → out_for_delivery`, `+30 h → delivered`.
- **Applying events**: every due event is applied once, in time order, through `set_order_status` (the transition table
  applies). `set_order_status` already writes the `events` row for notification events, so `advance()` marks that row
  `scripted = 1` instead of adding a duplicate. An illegal move is refused, reported in `applied` with its reason, never
  retried, and doesn't crash.
- **`reset()`**: clock back to 2026-10-09 09:00. 4510's seeded `status` and `delivered_date` are restored directly
  (the documented exception, since delivered → shipped is refused by the transition table), and its `scripted = 1`
  events rows and the applied list are removed.
- **Notifications**: unchanged and read-only. After `advance()`, `get_pending_notifications()` sees the new event.
- **`scripts/advance_clock.py`** (`--hours N` / `--reset`): prints from/to, the applied events and the pending
  notifications.
- **Server**: read-only `GET /clock` (`{now, start, today}`), and the dashboard shows the simulation time.
  No write route was added.
- **Contract** `docs/platform_contract.md`: new §9 (clock functions, timeline file, the `reset()` exception,
  date format), the `GET /clock` row in §8, and the dates note in §2.
- **Tests**: new `tests/test_clock.py` (10 tests).

## 3. Evidence
- **Existing tests unchanged**: 157 passed before (on `main`) and 157 after; none were edited.
  Full suite: **167 passed / 170** (157 + 10 new). The 3 failures are the known intake ones (`test_intake` ×2,
  `test_pipeline` ×1: `sentence_transformers` is not installed on this PC); they fail on `main` too.
- **New tests**:
  - advance 24 h → 4510 `out_for_delivery`, exactly **1** new events row (`2026-10-10`, `scripted = 1`);
  - +6 h → `delivered`, **1** more row; delivered_date 2026-10-10, days_late 0 (on time);
  - +10 h → **0** new events;
  - one 48 h step applies both events, in order;
  - with an approved `delivered` subscription created first: `get_pending_notifications()` → **0** before delivery
    (also 0 after out_for_delivery), **1** after;
  - 4512: `days_late` **6 → 8** after 48 h;
  - `reset()` → 2026-10-09 09:00, 4510 back to `shipped` with no delivered_date, events rows gone; the timeline can play again;
  - wrong event (4505 delivered → shipped) → refused, reported with "not allowed", no crash, not retried; a valid event
    in the same step still applies;
  - bad hours (0, -5, NaN, True, "24") → `{"error"}`, clock unchanged; `GET /clock` is read-only.
- **Seed unchanged**: the rebuilt DB MD5 is `e18ff80b…bb31`, the same as before P08. The real `shopnova.db` MD5 and mtime
  were unchanged by the test suite.
- **`python scripts/advance_clock.py --hours 30`** (real DB, then reset and re-seeded):
  ```
  Clock: 2026-10-09T09:00:00  ->  2026-10-10T15:00:00
    2026-10-10T09:00:00  order 4510: shipped -> out_for_delivery  (events row #1)
    2026-10-10T15:00:00  order 4510: out_for_delivery -> delivered  (events row #2)
  Pending notifications (not sent yet): 0
  ```
  Then `--hours 10` → "Timeline events applied: none". `--reset` → "Clock reset to 2026-10-09T09:00:00; orders restored: [4510]".
  (0 pending here because the real DB has no subscription; the test above covers the notification case.)

## 4. Problems
- **Which order: 4510**, because its simulator scenario (`list_scenario_cases()`) is "on time; a notification can be
  offered", which is exactly story S3, and it is not used by S1/S2/S4 or the damaged case. 4513 would also have worked,
  but it appears in the SLM test decisions. Nothing moves either order unless the clock is advanced.
- **`sim_today()` now reads the DB** (one small query per call). Reports that call `get_tracking` for every order do a
  few hundred tiny queries. That's fine at this size, but a cache would help if the data grows.
- **Moving the clock changes more than the timeline**: every non-delivered order gets later (`days_late` grows),
  and new rows (refunds, proposals, subscriptions) get the clock's date. That is the intended behaviour, but demos that
  expect "4512 = 6 days late" must reset the clock first (`--reset`), and so must anyone who re-seeds without resetting.
  Re-seeding also resets it, because the clock lives in the DB.
- **Events table dates stay dates**: an event at 09:00 and one at 15:00 on the same day both show `2026-10-10`. Only
  `sim_clock` stores hours. The applied results in the trace carry the full time.
- The timeline uses hours from the clock start (not from "now"). After a reset it plays again from the beginning.

## 5. Questions for the Brain
1. Should T09's notifier run automatically after each `advance()`, or stay a separate step (script / pipeline)?
   P08 keeps them separate, as the task says.
2. Should the timeline grow later (e.g. 4513 delivered at +48 h, a carrier delay for S4), or stay at one order for the demo?
3. Should the simulator (`read_own_case`) show the client the simulated time, e.g. "today is 10 October"?

## 6. Next step
T09 (core): after `advance()`, read `get_pending_notifications()`, write the message (SLM), and call
`mark_subscription_sent`. For the S3 demo, run `advance_clock.py --hours 30`, then the notifier.

Git: branch `feature/sim-clock` created from the latest `main` (a9e98ce), committed and pushed. Not merged.
