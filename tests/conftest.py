"""Shared test setup (pytest loads this file automatically)."""

import sys
from pathlib import Path

import pytest

# Make `import callverse` work when pytest is started from any folder.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from callverse import trace  # noqa: E402
from callverse.data import db  # noqa: E402
from callverse.data.seed import seed  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_env(tmp_path):
    """Before each test: build a fresh placeholder DB in a temp folder and write traces there too.

    The real database (callverse/data/shopnova.db) and the real traces/ folder are never touched.
    """
    db.use_db(tmp_path / "shopnova_test.db")
    seed()
    trace.start_run("test", trace_dir=tmp_path)
    yield
    db.use_db(db.DEFAULT_DB_PATH)  # put the default back after the test
