"""Shared test setup (pytest loads this file automatically)."""

import sys
from pathlib import Path

import pytest

# Make `import callverse` work when pytest is started from any folder.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from callverse import trace  # noqa: E402
from callverse.data.seed import seed  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_env(tmp_path):
    """Before each test: rebuild the placeholder DB and write traces to a temp folder, not traces/."""
    seed()
    trace.start_run("test", trace_dir=tmp_path)
    yield
