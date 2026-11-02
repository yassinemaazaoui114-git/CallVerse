"""Start the web API on 127.0.0.1 (default port 8610): python -m webui.api.run

Reads only: it opens callverse.db and the company data in SQLite read-only mode and loads no model.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # make `import callverse` and `import webui` work

import uvicorn  # noqa: E402

from webui.api import settings  # noqa: E402
from webui.api.app import apply_env_overrides, create_app  # noqa: E402


def main() -> None:
    apply_env_overrides()
    print(f"CallVerse web API: http://{settings.HOST}:{settings.PORT}/api/docs  (Ctrl+C stops it)")
    uvicorn.run(create_app(), host=settings.HOST, port=settings.PORT, log_level="warning")


if __name__ == "__main__":
    main()
