"""Shared test setup (pytest loads this file automatically)."""

import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Make `import callverse` work when pytest is started from any folder.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from callverse import trace  # noqa: E402
from callverse.data import db  # noqa: E402
from callverse.data.seed import seed  # noqa: E402


@pytest.fixture(scope="session")
def seeded_template(tmp_path_factory):
    """Seed the database ONCE per test session into a template file (T15: 2,000 real orders take ~0.2 s to load).

    Each test then gets a fresh copy of this file, which is exactly what seed() would build (seeding is fixed).
    """
    template = tmp_path_factory.mktemp("template") / "shopnova_template.db"
    seed(template)
    return template


@pytest.fixture(autouse=True)
def fresh_env(tmp_path, seeded_template):
    """Before each test: a fresh copy of the seeded DB in a temp folder, and traces written there too.

    The real database (callverse/data/shopnova.db) and the real traces/ folder are never touched.
    """
    shutil.copyfile(seeded_template, tmp_path / "shopnova_test.db")
    db.use_db(tmp_path / "shopnova_test.db")
    trace.start_run("test", trace_dir=tmp_path)   # proposals live in this fresh DB: ids restart at P-0001
    yield
    db.use_db(db.DEFAULT_DB_PATH)  # put the default back after the test


@pytest.fixture(autouse=True)
def slm_offline(monkeypatch):
    """Tests never call the real SLM (Ollama): when a test gives no fake SLM, the call fails like a stopped
    Ollama and the writer uses its template. Tests that need SLM text pass their own slm_chat_fn / chat_fn."""
    from callverse.slm import writer

    def ollama_stopped(*args, **kwargs):
        raise ConnectionError("SLM is offline in tests")

    monkeypatch.setattr(writer, "llm", SimpleNamespace(chat=ollama_stopped))
