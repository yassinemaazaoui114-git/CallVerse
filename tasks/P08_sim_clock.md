# P08 — Simulation clock + scripted delivery events (for story S3)  ·  Dali's lane

## Why
Story S3 (delivery notification): the user asks to be told when the order arrives, Agent A proposes
`subscribe`, the Coordinator approves, **time passes**, the order is delivered, and the user gets a message.
Today time is frozen (`sim_today` = 2026-10-09 in `config.yaml`) and nothing moves an order forward.
P08 gives the platform a clock that can move and a small script of delivery events. Sending the message
is core work (T09), not this task.

## Hard limits
- Branch `feature/sim-clock` from the latest `main` (pull first). Do not merge.
- Platform files only: `callverse/data/*`, platform scripts, `callverse/server/*` (read-only display), their tests.
  The **one** allowed core edit: `callverse/config.py → sim_today()` reads the clock (see step 1).
- Do not touch agents, Coordinator, pipeline, SLM, Intake, policies, or `tests/data/*`.
- **Default behaviour unchanged:** if the clock is never moved, `sim_today()` is 2026-10-09 and every existing test
  passes without changes.
- Status changes only through `set_order_status` (the transition table applies). No secrets in files.

## What to do
1. **Clock** — new `callverse/data/clock.py`, stored in the DB (one-row table `sim_clock`):
   - `now() -> datetime` (start: `sim_today` from config at 09:00);
   - `advance(hours: float) -> {from, to, applied: [events]}`; hours > 0 only;
   - `reset()` → back to the config start.
   - `config.sim_today()` returns `clock.now().date()`, so `days_late` and `days_since_delivery` follow the clock.
2. **Scripted timeline** — new `callverse/data/scenario_timeline.json` (`scripted: true`, AI-generated, marked as such):
   one **scripted order that is `shipped` and on time**, not used by S1/S2/S4 or the damaged case (pick it; say which in
   the report). Events: `+24 h → out_for_delivery`, `+30 h → delivered`.
3. **Apply events** — `advance()` applies every timeline event that is due, in time order: `set_order_status`, then an
   `events` row (`scripted = 1`). Each event is applied **once** (advancing again never repeats it). An illegal transition
   is refused, reported in `applied` with the reason, and does not crash.
4. **Notifications stay read-only here:** after `advance()`, `get_pending_notifications()` must return the subscriptions whose
   event has now happened (not yet sent). `mark_subscription_sent` is unchanged.
5. **Script** `scripts/advance_clock.py --hours N` and `--reset` (prints from/to and applied events).
   Dashboard (P05): show the simulation time (read-only). No new write route on the server.
6. `docs/platform_contract.md`: add the clock functions and the timeline file.

## Checks (with numbers)
- Existing tests: all pass **unchanged** (report x/y).
- New tests:
  - advance 24 h → the order is `out_for_delivery`, exactly 1 new event row;
  - advance 6 h more → `delivered`, 1 more event row;
  - advance 10 h more → 0 new events (no repeat);
  - with a subscription (order, `delivered`) created before: `get_pending_notifications()` returns it **0** times before
    delivery and **1** time after;
  - 4512 (stuck at depot): `days_late` goes from 6 to 8 after advancing 48 h;
  - `reset()` → clock back to 2026-10-09 09:00 and the timeline order back to `shipped`;
  - a wrong timeline event (e.g. `delivered → shipped`) → refused, reported, no crash.
- `scripts/advance_clock.py --hours 30` output pasted in the report.

## Time box and stop rule
90 minutes. Stop and report if changing `sim_today()` breaks existing tests in a way you can't fix without touching core files.

## Git (approved by Yassine, 2026-10-21)
Commit and push `feature/sim-clock`. No merge. Write `tasks/P08_report.md`, set `tasks/NEXT_PLATFORM.md` to WAITING FOR REVIEW.

## Notes from review (Dali, 2026-10-21)
- **Avoid a loop at start-up**: `db.connect()` seeds the DB when the file is missing, and `seed.py` calls `sim_today()`.
  If `sim_today()` reads the clock from the DB, a missing DB file → `connect()` → `seed()` → `sim_today()` →
  `connect()` → ... loops. `seed.py` must use the **config start date** directly (e.g. a `config.sim_start()` or the
  raw `sim_today` value), never the moving clock. This also keeps a rebuilt DB byte-identical after the clock moved.
- **`reset()` vs the transition table**: `delivered → shipped` is refused by `set_order_status`, so `reset()` cannot use
  it. `reset()` restores the timeline order's seeded row (status, dates) and removes the timeline's `events` rows
  directly. This is the one allowed exception; say so in the contract.
- **Date format**: `events.at`, `created_at` and `decided_at` are dates (`YYYY-MM-DD`) today, and `get_pending_notifications`
  returns `event_at`. Keep the existing shapes: store the date (or document an ISO datetime if you need hours, and
  update every reader and the contract).
- **Which order**: 4510 is tagged `on_time` in `list_scenario_cases()` and 4513 appears in the SLM test decisions. Either
  can be used because nothing moves unless the clock is advanced, but say which one and why in the report.
