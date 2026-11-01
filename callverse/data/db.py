"""Where the ShopNova database file is, and how to open it.

Everything that reads or writes ShopNova data (read tools, write functions, seed) opens the
database through connect() below, so there is ONE place that decides which file is used.

Normally that is callverse/data/shopnova.db. The tests call use_db(<temporary file>) first,
so they never touch the real database.
"""

import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "shopnova.db"

_db_path = DEFAULT_DB_PATH


def use_db(path: str | Path) -> None:
    """Point all ShopNova code at another database file (used by the tests)."""
    global _db_path
    _db_path = Path(path)


def db_path() -> Path:
    """The database file currently in use."""
    return _db_path


def connect() -> sqlite3.Connection:
    """Open the current database (create and seed it first if the file does not exist)."""
    if not _db_path.exists():
        from callverse.data.seed import seed  # imported here to avoid a circular import
        seed()
    con = sqlite3.connect(_db_path)
    con.row_factory = sqlite3.Row  # rows behave like dicts: row["name"]
    # T14c: a shopnova.db made before T14c has no proposals.proof_received: add it with the safe default 0 (= no photo),
    # so an old file keeps working and its old proposals read as "no proof".
    columns = {r["name"] for r in con.execute("PRAGMA table_info(proposals)")}   # empty: no table yet
    if columns and "proof_received" not in columns:
        con.execute("ALTER TABLE proposals ADD COLUMN proof_received INTEGER NOT NULL DEFAULT 0")
        con.commit()
    return con
