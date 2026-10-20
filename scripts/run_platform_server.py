"""Start the ShopNova platform server on THIS PC only (http://127.0.0.1:8000).

Usage (from the repo root):
    python scripts/run_platform_server.py        (or: python -m scripts.run_platform_server)
Stop it with Ctrl+C.

HOST is 127.0.0.1 on purpose: the server is reachable only from this computer, never from the
network. Writes need PLATFORM_COORDINATOR_TOKEN in .env (see README); without it, they are refused.
"""

import sys
from pathlib import Path

# Allow "python scripts/run_platform_server.py" as well as "python -m scripts.run_platform_server".
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn  # noqa: E402

from callverse import trace  # noqa: E402
from callverse.data.db import db_path  # noqa: E402
from callverse.server.app import app  # noqa: E402

HOST = "127.0.0.1"   # localhost only: never bind to all network interfaces
PORT = 8000


def main() -> None:
    trace_path = trace.start_run()   # one trace file per server run
    print(f"ShopNova platform server: http://{HOST}:{PORT}/")
    print(f"API pages (all endpoints): http://{HOST}:{PORT}/docs")
    print(f"Database  : {db_path()}")
    print(f"Trace file: {trace_path}")
    print("Stop with Ctrl+C.")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
