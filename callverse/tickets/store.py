"""The tickets store: CallVerse's OWN database (callverse/data/callverse.db), separate from the company's data.

Why a second database? Like a real outsourced customer center: the company (ShopNova) owns its orders,
refunds, users... in shopnova.db; the center owns its tickets, the conversation and how the agents worked on
it. The Console (T19) reads this file; it never writes company data. Git-ignored, created on first use.

Tables (docs/ui_design.md section 3):
- tickets   : one conversation with one client: id "T-0001", company, user_id, status, main_reason, priority,
              lead_agent, created_at, updated_at, closed_at.
- messages  : what was said: sender user / assistant / system, the text, when.
- steps     : how CallVerse worked on ONE message (intake, route, tool calls, proposal, Coordinator, SLM...),
              copied from the trace, so the Console can replay it without reading trace files.
- approvals : refunds waiting for finance (T18: created by the channel on "layer3_pending", decided by the
              ShopNova admin through callverse/channels/approvals.py).
- system_tokens : tokens CallVerse spent for itself, not for a ticket (T17 follow-up Q5: the quota check's
              "Say OK." pings), so the Console can show them apart from the tokens per ticket.

T19 (the Console): two clocks. The simulation clock does not move, so every ticket would have the same time.
- created_at / updated_at / at = SIMULATION time: the company rules use it (the 3-day reopen window).
- created_real / updated_real / at_real = the COMPUTER's time (local, ISO): the Console uses it for ages, tickets
  per day, reply speed and "Groq tokens used today". messages.seconds = how long an assistant reply took.
  Old rows (before T19) have NULL there; the Console shows "—" for them.
- New status "Escalated": the Coordinator (or an error) passed the ticket to a human colleague.

The ticket rule (T17 item 11), in ticket_for_message():
- one chat = one ticket. "Solved" when the decision is final; "Waiting for user" when we asked something;
- a new message on a Solved ticket within 3 days (simulation clock) reopens it ("Open"); a new message on an
  Escalated ticket continues it (like Open);
- after 3 days, on a Closed ticket, or after "New chat" (no ticket id): a new ticket.

The rule times come from the simulation clock (callverse/data/clock.py); the *_real columns are only for the Console.
The tests call use_db(<temporary file>) first, like callverse/data/db.py.
"""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from callverse.data import clock

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "callverse.db"
_db_path = DEFAULT_DB_PATH

STATUSES = ("New", "Open", "Waiting for user", "Waiting for finance", "Escalated", "Solved", "Closed")   # T19: Escalated
SENDERS = ("user", "assistant", "system")
APPROVAL_STATUSES = ("pending", "approved", "refused")
REOPEN_DAYS = 3   # a Solved ticket can be reopened for 3 days (simulation clock), then a new ticket starts
# Ticket columns that update_ticket() may change (id, company, user_id, created_at never change).
UPDATABLE = ("status", "main_reason", "priority", "lead_agent")


def _in(values) -> str:
    """SQL text "('a', 'b')" for a CHECK (... IN ...) constraint."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


# The tickets table alone ({name} = the table name): connect() also uses it to rebuild an old tickets table
# whose status check does not know "Escalated" yet (SQLite cannot change a CHECK in place).
TICKETS_TABLE = f"""
CREATE TABLE IF NOT EXISTS {{name}} (
    id          TEXT PRIMARY KEY,            -- "T-0001", "T-0002", ...
    company     TEXT NOT NULL,               -- e.g. "shopnova"
    user_id     INTEGER NOT NULL,            -- the company's user id (users.id in shopnova.db)
    status      TEXT NOT NULL CHECK (status IN {_in(STATUSES)}),
    main_reason TEXT,                        -- from Intake (last message)
    priority    TEXT,                        -- high / medium / low, from Intake (last message)
    lead_agent  TEXT,                        -- "A" or "B": the agent that answered the last message
    created_at  TEXT NOT NULL,               -- simulation time, ISO
    updated_at  TEXT NOT NULL,
    closed_at   TEXT,
    user_unread INTEGER NOT NULL DEFAULT 0,      -- T18: 1 = a reply the user has not opened yet (e.g. finance's)
    created_real TEXT,                       -- T19: the computer's time (local ISO), for the Console
    updated_real TEXT
);
"""

SCHEMA = TICKETS_TABLE.format(name="tickets") + f"""
CREATE TABLE IF NOT EXISTS messages (
    id        INTEGER PRIMARY KEY,
    ticket_id TEXT NOT NULL REFERENCES tickets(id),
    sender    TEXT NOT NULL CHECK (sender IN {_in(SENDERS)}),
    text      TEXT NOT NULL,
    at        TEXT NOT NULL,
    at_real   TEXT,                                -- T19: the computer's time
    seconds   REAL                                 -- T19: assistant messages: how long the reply took
);
CREATE TABLE IF NOT EXISTS steps (
    id         INTEGER PRIMARY KEY,
    ticket_id  TEXT NOT NULL REFERENCES tickets(id),
    message_id INTEGER REFERENCES messages(id),   -- the user message this step worked on
    step       TEXT NOT NULL,                     -- intake / route / tool_call / ... (web_chat.STEP_KINDS)
    agent      TEXT,                              -- who did it: intake, A, B, coordinator, slm, ...
    data       TEXT NOT NULL,                     -- JSON: the trace data of that step
    at         TEXT NOT NULL,
    at_real    TEXT                               -- T19: the computer's time (Groq tokens used today)
);
CREATE TABLE IF NOT EXISTS approvals (
    id          INTEGER PRIMARY KEY,
    ticket_id   TEXT NOT NULL REFERENCES tickets(id),
    order_id    INTEGER NOT NULL,
    amount      REAL NOT NULL,
    proposal_id TEXT,
    status      TEXT NOT NULL CHECK (status IN {_in(APPROVAL_STATUSES)}),
    decided_by  TEXT,
    decided_at  TEXT,
    reason      TEXT
);
CREATE TABLE IF NOT EXISTS system_tokens (
    id       INTEGER PRIMARY KEY,
    purpose  TEXT NOT NULL,              -- e.g. "quota_check"
    provider TEXT,
    model    TEXT,
    tokens   INTEGER NOT NULL,
    at       TEXT NOT NULL,
    at_real  TEXT                        -- T19: the computer's time (Groq tokens used today)
);
"""


def use_db(path: str | Path) -> None:
    """Point the store at another file (used by the tests)."""
    global _db_path
    _db_path = Path(path)


def db_path() -> Path:
    return _db_path


def connect() -> sqlite3.Connection:
    """Open the tickets database, creating the file and the tables if needed."""
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(_db_path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    # T18: a callverse.db made before T18 has no user_unread column: add it, so the old file keeps working.
    if "user_unread" not in _columns(con, "tickets"):
        con.execute("ALTER TABLE tickets ADD COLUMN user_unread INTEGER NOT NULL DEFAULT 0")
        con.commit()
    # T19: the same for the computer-time columns and the reply seconds (old rows keep NULL there).
    for table, column, kind in NEW_COLUMNS:
        if column not in _columns(con, table):
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")   # names from NEW_COLUMNS only
            con.commit()
    _allow_escalated(con)
    return con


# T19: columns added to a callverse.db made before T19: (table, column, type).
NEW_COLUMNS = [("tickets", "created_real", "TEXT"), ("tickets", "updated_real", "TEXT"),
               ("messages", "at_real", "TEXT"), ("messages", "seconds", "REAL"),
               ("steps", "at_real", "TEXT"), ("system_tokens", "at_real", "TEXT")]


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}


def _allow_escalated(con: sqlite3.Connection) -> None:
    """T19: an old tickets table's status check does not know "Escalated". SQLite cannot change a CHECK, so the
    table is rebuilt the way SQLite's documentation says: new table, copy all rows, drop the old one, rename.
    The other tables keep pointing at "tickets" (same name, same ids). Done once; nothing is lost."""
    sql = con.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'tickets'").fetchone()[0]
    if "'Escalated'" in sql:
        return
    columns = ", ".join(sorted(_columns(con, "tickets")))   # all old columns exist in the new table too
    con.execute("PRAGMA foreign_keys = OFF")
    con.executescript("BEGIN;" + TICKETS_TABLE.format(name="tickets_new") + ";"
                      f"INSERT INTO tickets_new ({columns}) SELECT {columns} FROM tickets;"
                      "DROP TABLE tickets; ALTER TABLE tickets_new RENAME TO tickets; COMMIT;")


def real_now() -> str:
    """T19: the COMPUTER's time (local, ISO, seconds), for the Console only. The rules use now() below."""
    return datetime.now().isoformat(timespec="seconds")


def now() -> str:
    """The simulation time as ISO text (the same clock as ShopNova's data)."""
    return clock.now().isoformat(timespec="seconds")


def create_ticket(company: str, user_id: int) -> dict:
    """A new ticket with status "New". Ids follow each other: T-0001, T-0002, ... (rows are never deleted)."""
    at = now()
    with closing(connect()) as con:
        con.execute("BEGIN IMMEDIATE")   # two chats at the same moment cannot take the same number
        count = con.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        ticket_id = f"T-{count + 1:04d}"
        real = real_now()
        con.execute("INSERT INTO tickets (id, company, user_id, status, created_at, updated_at, created_real,"
                    " updated_real) VALUES (?, ?, ?, 'New', ?, ?, ?, ?)",
                    (ticket_id, company, int(user_id), at, at, real, real))
        con.commit()
    return get_ticket(ticket_id)


def get_ticket(ticket_id: str) -> dict | None:
    with closing(connect()) as con:
        row = con.execute("SELECT * FROM tickets WHERE id = ?", (str(ticket_id),)).fetchone()
    return dict(row) if row else None


def update_ticket(ticket_id: str, **fields) -> dict:
    """Change status / main_reason / priority / lead_agent; updated_at (and updated_real) are set; closed_at when
    it becomes Closed."""
    unknown = set(fields) - set(UPDATABLE)
    if unknown:
        raise ValueError(f"cannot update {sorted(unknown)} (allowed: {', '.join(UPDATABLE)})")
    if "status" in fields and fields["status"] not in STATUSES:
        raise ValueError(f"unknown status '{fields['status']}' (allowed: {', '.join(STATUSES)})")
    fields["updated_at"] = now()
    fields["updated_real"] = real_now()
    if fields.get("status") == "Closed":
        fields["closed_at"] = fields["updated_at"]
    sets = ", ".join(f"{name} = ?" for name in fields)   # names come from UPDATABLE above, never from a client
    with closing(connect()) as con:
        con.execute(f"UPDATE tickets SET {sets} WHERE id = ?", (*fields.values(), str(ticket_id)))
        con.commit()
    return get_ticket(ticket_id)


def add_message(ticket_id: str, sender: str, text: str, seconds: float | None = None) -> int:
    """Save one message of the conversation and return its id.
    seconds (T19): for an assistant message, how long the reply took (None = not measured)."""
    if sender not in SENDERS:
        raise ValueError(f"unknown sender '{sender}' (allowed: {', '.join(SENDERS)})")
    with closing(connect()) as con:
        cur = con.execute("INSERT INTO messages (ticket_id, sender, text, at, at_real, seconds) VALUES (?, ?, ?, ?, ?, ?)",
                          (str(ticket_id), sender, text, now(), real_now(), seconds))
        con.commit()
    return cur.lastrowid


def add_step(ticket_id: str, message_id: int | None, step: str, agent: str | None, data: dict) -> int:
    """Save one step of how CallVerse handled a message (data = the trace data, as JSON)."""
    with closing(connect()) as con:
        cur = con.execute("INSERT INTO steps (ticket_id, message_id, step, agent, data, at, at_real)"
                          " VALUES (?, ?, ?, ?, ?, ?, ?)",
                          (str(ticket_id), message_id, step, agent,
                           json.dumps(data, ensure_ascii=False, default=str), now(), real_now()))
        con.commit()
    return cur.lastrowid


def add_system_tokens(purpose: str, provider: str | None, model: str | None, tokens: int) -> int:
    """Save tokens spent outside any ticket (e.g. the quota check) and return the row id."""
    with closing(connect()) as con:
        cur = con.execute("INSERT INTO system_tokens (purpose, provider, model, tokens, at, at_real)"
                          " VALUES (?, ?, ?, ?, ?, ?)", (purpose, provider, model, int(tokens), now(), real_now()))
        con.commit()
    return cur.lastrowid


def system_tokens() -> list[dict]:
    with closing(connect()) as con:
        return [dict(r) for r in con.execute("SELECT * FROM system_tokens ORDER BY id").fetchall()]


def messages(ticket_id: str) -> list[dict]:
    with closing(connect()) as con:
        rows = con.execute("SELECT * FROM messages WHERE ticket_id = ? ORDER BY id", (str(ticket_id),)).fetchall()
    return [dict(r) for r in rows]


def steps(ticket_id: str) -> list[dict]:
    with closing(connect()) as con:
        rows = con.execute("SELECT * FROM steps WHERE ticket_id = ? ORDER BY id", (str(ticket_id),)).fetchall()
    return [{**dict(r), "data": json.loads(r["data"])} for r in rows]


def can_continue(ticket: dict) -> bool:
    """True if a new message may go on this ticket (the ticket rule): not Closed, and a Solved ticket only for
    REOPEN_DAYS days after it was solved (updated_at = when it became Solved)."""
    if ticket["status"] == "Closed":
        return False
    if ticket["status"] == "Solved":
        return clock.now() - datetime.fromisoformat(ticket["updated_at"]) <= timedelta(days=REOPEN_DAYS)
    return True


def ticket_for_message(company: str, user_id: int, ticket_id: str | None = None) -> dict:
    """The ticket a new user message goes on (the ticket rule above).

    ticket_id = the chat's current ticket (None after "New chat"). A ticket of another user or company is
    never used (a new one is made). A Solved ticket within 3 days is reopened ("Open").
    """
    ticket = get_ticket(ticket_id) if ticket_id else None
    if ticket is None or ticket["company"] != company or ticket["user_id"] != int(user_id) or not can_continue(ticket):
        return create_ticket(company, user_id)
    if ticket["status"] == "Solved":
        ticket = update_ticket(ticket["id"], status="Open")
    return ticket


def set_unread(ticket_id: str, unread: bool) -> None:
    """T18: mark a ticket as having a reply the user has not opened (1) or as opened (0).
    updated_at is NOT changed: opening a reply must not move the 3-day reopen window."""
    with closing(connect()) as con:
        con.execute("UPDATE tickets SET user_unread = ? WHERE id = ?", (1 if unread else 0, str(ticket_id)))
        con.commit()


def unread_tickets(company: str, user_id: int) -> list[dict]:
    """The user's tickets with a reply not opened yet (the "💬 New reply on T-00NN" notice), oldest first."""
    with closing(connect()) as con:
        rows = con.execute("SELECT * FROM tickets WHERE company = ? AND user_id = ? AND user_unread = 1 ORDER BY id",
                           (company, int(user_id))).fetchall()
    return [dict(r) for r in rows]


# ---------- approvals (T18: the real Layer 3 queue) ----------

def create_approval(ticket_id: str, order_id: int, amount: float, proposal_id: str | None) -> dict:
    """A refund waiting for the ShopNova admin (status "pending")."""
    with closing(connect()) as con:
        cur = con.execute("INSERT INTO approvals (ticket_id, order_id, amount, proposal_id, status)"
                          " VALUES (?, ?, ?, ?, 'pending')", (str(ticket_id), int(order_id), float(amount), proposal_id))
        con.commit()
    return get_approval(cur.lastrowid)


def get_approval(approval_id: int) -> dict | None:
    with closing(connect()) as con:
        row = con.execute("SELECT * FROM approvals WHERE id = ?", (int(approval_id),)).fetchone()
    return dict(row) if row else None


def approvals(status: str | None = None) -> list[dict]:
    """All approvals (or those with one status): pending ones oldest first, the others newest first."""
    with closing(connect()) as con:
        if status is None:
            rows = con.execute("SELECT * FROM approvals ORDER BY status != 'pending', "
                               "CASE WHEN status = 'pending' THEN id ELSE -id END").fetchall()
        else:
            rows = con.execute("SELECT * FROM approvals WHERE status = ? ORDER BY id", (status,)).fetchall()
    return [dict(r) for r in rows]


def pending_approval_for_order(order_id) -> dict | None:
    """The pending approval of this order, if there is one (the channel's duplicate guard)."""
    if order_id is None:
        return None
    with closing(connect()) as con:
        row = con.execute("SELECT * FROM approvals WHERE order_id = ? AND status = 'pending' ORDER BY id LIMIT 1",
                          (int(order_id),)).fetchone()
    return dict(row) if row else None


def close_approval(approval_id: int, status: str, decided_by: str, reason: str | None) -> bool:
    """Set a PENDING approval to approved / refused. False if it was not pending any more (decided once):
    the "WHERE status = 'pending'" makes the check and the change one step, so two clicks cannot both close it."""
    if status not in ("approved", "refused"):
        raise ValueError(f"an approval is closed as approved or refused, not '{status}'")
    with closing(connect()) as con:
        cur = con.execute("UPDATE approvals SET status = ?, decided_by = ?, decided_at = ?, reason = ?"
                          " WHERE id = ? AND status = 'pending'",
                          (status, decided_by, now(), reason, int(approval_id)))
        con.commit()
    return cur.rowcount == 1


def current_ticket(company: str, user_id: int) -> dict | None:
    """The user's latest ticket if a new message may still go on it (to show the chat again after a reload)."""
    with closing(connect()) as con:
        row = con.execute("SELECT * FROM tickets WHERE company = ? AND user_id = ? ORDER BY id DESC LIMIT 1",
                          (company, int(user_id))).fetchone()
    if row is None or not can_continue(dict(row)):
        return None
    return dict(row)
