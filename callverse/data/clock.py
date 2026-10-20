"""The simulation clock: ShopNova's "now", which can move forward (for story S3, delivery notifications).

- The clock starts at sim_today from config.yaml (2026-10-09) at 09:00 and only moves when advance() is called.
  If it never moves, everything behaves exactly as with the old fixed date.
- It is stored in the database (one-row table sim_clock), so every part of the platform sees the same time.
  config.sim_today() returns now().date(), so days_late and days_since_delivery follow the clock.
- advance(hours) also plays the scripted delivery timeline (scenario_timeline.json): every event that is due
  is applied once, in time order, through set_order_status (so the transition table applies).
- reset() puts the clock back to the start and undoes the timeline (see reset() for the one exception).

Sending notifications is NOT done here: after advance(), reports.get_pending_notifications() simply sees the
new events; the notifier (core work) sends them.
"""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, time, timedelta
from pathlib import Path

from callverse import trace
from callverse.config import sim_start
from callverse.data.db import connect

TIMELINE_PATH = Path(__file__).resolve().parent / "scenario_timeline.json"
START_HOUR = 9   # the simulated day starts at 09:00

CLOCK_SCHEMA = """
CREATE TABLE IF NOT EXISTS sim_clock (
    id  INTEGER PRIMARY KEY CHECK (id = 1),   -- one row only
    now TEXT NOT NULL                          -- ISO datetime, e.g. 2026-10-10T15:00:00
);
CREATE TABLE IF NOT EXISTS sim_timeline_applied (
    event_id   TEXT PRIMARY KEY,               -- id from scenario_timeline.json
    applied_at TEXT NOT NULL,                  -- simulated time when it was applied
    result     TEXT NOT NULL                   -- JSON: what happened (or why it was refused)
);
"""


def start() -> datetime:
    """Where the clock starts: sim_today from config.yaml at 09:00."""
    return datetime.combine(sim_start(), time(START_HOUR))


def now() -> datetime:
    """The current simulated time (the start if the clock was never moved)."""
    try:
        with closing(connect()) as con:
            row = con.execute("SELECT now FROM sim_clock WHERE id = 1").fetchone()
    except sqlite3.OperationalError:   # an older database without the clock table: the clock never moved
        return start()
    return datetime.fromisoformat(row["now"]) if row else start()


def load_timeline(path: str | Path | None = None) -> list[dict]:
    """Timeline events sorted by time: [{"id", "order_id", "after_hours", "status"}]."""
    data = json.loads(Path(path or TIMELINE_PATH).read_text(encoding="utf-8"))
    return sorted(data["events"], key=lambda e: (e["after_hours"], e["id"]))


def _apply(event: dict, when: datetime) -> dict:
    """Apply one timeline event through set_order_status; never raises."""
    from callverse.data.writes import set_order_status   # imported here: writes -> config -> clock at import time
    result = set_order_status(event["order_id"], event["status"])
    if "error" in result:
        return {"event_id": event["id"], "order_id": event["order_id"], "status": event["status"],
                "at": when.isoformat(), "applied": False, "reason": result["error"]}
    if result.get("event"):   # set_order_status wrote the events row: label it as scripted (timeline)
        with closing(connect()) as con:
            con.execute("UPDATE events SET scripted = 1 WHERE id = ?", (result["event"]["id"],))
            con.commit()
    return {"event_id": event["id"], "order_id": event["order_id"], "status": event["status"],
            "at": when.isoformat(), "applied": True, "old_status": result["old_status"],
            "event_row": result["event"]["id"] if result.get("event") else None}


def advance(hours: float) -> dict:
    """Move the clock forward and apply the timeline events that became due. Returns {from, to, applied}.

    hours must be a number > 0 (else {"error": ...}). Each timeline event is handled once: a refused event
    (illegal status move) is reported in `applied` with its reason and is not tried again.
    """
    if isinstance(hours, bool) or not isinstance(hours, (int, float)) or not hours > 0 or hours != hours:
        trace.log("clock_refused", "clock", {"hours": hours, "reason": "hours must be a number > 0"})
        return {"error": "hours must be a number > 0"}

    old = now()
    new = old + timedelta(hours=hours)
    with closing(connect()) as con:
        con.executescript(CLOCK_SCHEMA)
        con.execute("INSERT OR REPLACE INTO sim_clock (id, now) VALUES (1, ?)", (new.isoformat(),))
        con.commit()
        done = {r["event_id"] for r in con.execute("SELECT event_id FROM sim_timeline_applied")}

    applied = []
    for event in load_timeline():
        due = start() + timedelta(hours=event["after_hours"])
        if event["id"] in done or due > new:
            continue
        outcome = _apply(event, due)
        applied.append(outcome)
        with closing(connect()) as con:
            con.execute("INSERT INTO sim_timeline_applied (event_id, applied_at, result) VALUES (?, ?, ?)",
                        (event["id"], new.isoformat(), json.dumps(outcome)))
            con.commit()

    result = {"from": old.isoformat(), "to": new.isoformat(), "applied": applied}
    trace.log("clock_advance", "clock", result)
    return result


def reset() -> dict:
    """Clock back to the start; the timeline orders back to their seeded rows; timeline events removed.

    The one exception to "status changes only through set_order_status": going back (e.g. delivered ->
    shipped) is refused by the transition table, so reset() restores the seeded status and dates directly.
    """
    from callverse.data.seed import ORDERS
    seeded = {o[0]: o for o in ORDERS}
    order_ids = sorted({e["order_id"] for e in load_timeline()})
    with closing(connect()) as con:
        con.executescript(CLOCK_SCHEMA)
        con.execute("DELETE FROM sim_clock")
        con.execute("DELETE FROM sim_timeline_applied")
        for oid in order_ids:
            o = seeded[oid]   # (id, user_id, items, total, paid, status, order_date, promised_date, delivered_date, ...)
            con.execute("UPDATE orders SET status = ?, delivered_date = ? WHERE id = ?", (o[5], o[8], oid))
            con.execute("DELETE FROM events WHERE order_id = ? AND scripted = 1", (oid,))
        con.commit()
    result = {"now": start().isoformat(), "orders_restored": order_ids}
    trace.log("clock_reset", "clock", result)
    return result
