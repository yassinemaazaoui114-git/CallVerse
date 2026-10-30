"""Where the Atlas Travel database file is, and how to open it (same pattern as callverse/data/db.py).

Normally that is callverse/data/atlas.db. The tests call use_db(<temporary file>) first,
so they never touch the real database.

T22: an atlas.db made before T22 keeps working: connect() adds what is missing (the admin log, the two confirmation
columns of the proposals), and never changes a row.
"""

import sqlite3
from pathlib import Path

from callverse.data.atlas.schema import ADMIN_ACTIONS, CONFIRMATION_COLUMNS

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "atlas.db"

_db_path = DEFAULT_DB_PATH


def use_db(path: str | Path) -> None:
    """Point all Atlas code at another database file (used by the tests)."""
    global _db_path
    _db_path = Path(path)


def db_path() -> Path:
    """The database file currently in use."""
    return _db_path


def connect() -> sqlite3.Connection:
    """Open the current database (create and seed it first if the file does not exist)."""
    if not _db_path.exists():
        from callverse.data.atlas.seed import seed  # imported here to avoid a circular import
        seed()
    con = sqlite3.connect(_db_path)
    con.row_factory = sqlite3.Row  # rows behave like dicts: row["name"]
    con.executescript(ADMIN_ACTIONS)
    columns = {r["name"] for r in con.execute("PRAGMA table_info(proposals)")}
    for name, kind in CONFIRMATION_COLUMNS:
        if name not in columns:
            con.execute(f"ALTER TABLE proposals ADD COLUMN {name} {kind}")   # names from our own list only
            con.commit()
    return con
