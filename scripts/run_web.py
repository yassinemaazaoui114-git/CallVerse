"""Start the CallVerse customer website (text + voice chat).

Usage (from the repo root):
    python -m scripts.run_web            -> http://127.0.0.1:8080/  (this computer only)

HOST / PORT come from the environment. The default 127.0.0.1 keeps it on this computer; the Docker image
sets HOST=0.0.0.0 and PORT=7860 because a cloud host must reach it. This app has no admin or write
routes, so it is the only CallVerse app meant to be public (the platform server stays on localhost).
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn  # noqa: E402

from callverse import trace  # noqa: E402
from callverse.data.seed import seed  # noqa: E402


def main() -> None:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8080"))
    seed()                            # fresh placeholder ShopNova data on every start (demo data, AI-generated)
    trace_path = trace.start_run()    # one trace file per server run
    from callverse.web.app import app
    from callverse.web.pipeline import resolve_mode

    # Load the Intake models (M3 + M4) in the background, so the first customer does not wait for them.
    import threading
    from callverse.intake import intake
    threading.Thread(target=intake.load_models, daemon=True).start()
    print(f"CallVerse customer channel: http://{host}:{port}/   mode: {resolve_mode().upper()}")
    print(f"Trace file: {trace_path}")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
