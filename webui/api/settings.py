"""Settings of the web API, read from environment variables (never from .env: the API needs no key).

Every value has a safe default for this PC. The tests and the demo point the API at TEMPORARY files with the
two CALLVERSE_WEBUI_* paths, so the real accounts file and the real tickets database are never touched.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

HOST = "127.0.0.1"   # localhost only, like every other CallVerse server: never bind to all interfaces
PORT = int(os.getenv("CALLVERSE_WEBUI_API_PORT", "8610"))

# The session cookie (HttpOnly, SameSite=Strict). Secure is off: the API runs on http://127.0.0.1 only.
COOKIE_NAME = "cv_webui_session"
SESSION_HOURS = float(os.getenv("CALLVERSE_WEBUI_SESSION_HOURS", "8"))

# Every state-changing request (POST) must carry this header. A browser lets another site send a plain form or
# a simple fetch with our cookie, but it never lets it add a custom header without a CORS preflight, and this
# API answers no preflight (no CORS). Together with SameSite=Strict this blocks cross-site request forgery.
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "CallVerse"

# Optional overrides (used by the tests and by the demo script, see webui/README.md):
# - CALLVERSE_WEBUI_ACCOUNTS: another accounts file (same YAML format, bcrypt hashes) than config/accounts.yaml
# - CALLVERSE_WEBUI_TICKETS_DB: another callverse.db (the tickets database the Console reads)
# - CALLVERSE_WEBUI_SHOPNOVA_DB: another shopnova.db (only read, for the users' names)
ACCOUNTS_FILE = os.getenv("CALLVERSE_WEBUI_ACCOUNTS")
TICKETS_DB = os.getenv("CALLVERSE_WEBUI_TICKETS_DB")
SHOPNOVA_DB = os.getenv("CALLVERSE_WEBUI_SHOPNOVA_DB")
ATLAS_DB = os.getenv("CALLVERSE_WEBUI_ATLAS_DB")   # another atlas.db (only read, step 5)
# - CALLVERSE_WEBUI_FAKE_CHAT=1: the chat uses the fake channel of dev_fixture.py (no model, replies marked as
#   test data). For looking at the chat screen only; never set it for a real demo.
FAKE_CHAT = os.getenv("CALLVERSE_WEBUI_FAKE_CHAT", "") == "1"
