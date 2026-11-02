"""Login, sessions and role checks for the web API, on top of callverse.auth.accounts (the ONE account store).

- The accounts file (config/accounts.yaml, bcrypt hashes) is the same one the Streamlit apps use. There is no
  second user database. `verify_password` compares the typed password with the stored bcrypt hash exactly as
  streamlit-authenticator does (bcrypt.checkpw). The hash never leaves this module and is never logged.
- A session is a random token kept in memory on the server; the browser only gets the token in an HttpOnly
  cookie (JavaScript cannot read it). Restarting the API logs everyone out, which is fine for a demo on one PC.
- Role checks reuse accounts.check_role: the role always comes from the accounts FILE (looked up by the username
  of the session), never from anything the browser sends.
"""

import secrets
import threading
from datetime import datetime, timedelta

import bcrypt

from callverse.auth import accounts

from webui.api import settings


def password_hash_of(username: str) -> str | None:
    """The stored bcrypt hash of one account, or None if the account does not exist. Internal to this module."""
    data = accounts.load_accounts()
    entry = (data or {}).get("credentials", {}).get("usernames", {}).get(username) if username else None
    if not entry:
        return None
    value = entry.get("password")
    return value if isinstance(value, str) and value else None


def verify_password(username: str, password: str) -> bool:
    """True if `password` matches the account's bcrypt hash (the same check streamlit-authenticator makes)."""
    stored = password_hash_of(username)
    if stored is None or not password:
        # Still run a bcrypt check so a wrong username takes as long as a wrong password (no username probing).
        bcrypt.checkpw(b"x", _DUMMY_HASH)
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
    except ValueError:   # a stored value that is not a bcrypt hash
        return False


_DUMMY_HASH = bcrypt.hashpw(b"dummy", bcrypt.gensalt(rounds=4))


class SessionStore:
    """Sessions in memory: token -> {username, created, expires}. One lock: FastAPI may run handlers in threads."""

    def __init__(self, hours: float = settings.SESSION_HOURS):
        self._sessions: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._hours = hours

    def create(self, username: str) -> str:
        token = secrets.token_urlsafe(32)
        now = datetime.now()
        with self._lock:
            self._sessions[token] = {"username": username, "created": now,
                                     "expires": now + timedelta(hours=self._hours)}
        return token

    def username(self, token: str | None) -> str | None:
        """The username of a live session, or None (no token, unknown token, expired token)."""
        if not token:
            return None
        with self._lock:
            found = self._sessions.get(token)
            if found is None:
                return None
            if found["expires"] <= datetime.now():
                del self._sessions[token]
                return None
            return found["username"]

    def delete(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()


def session_info(username: str) -> dict | None:
    """What the browser may know about the logged-in account: username, name, role, company. Never the hash."""
    found = accounts.account(username)
    if found is None:
        return None
    return {"username": found["username"], "name": found["name"], "role": found["role"],
            "company": accounts.company_of(found)}


def has_role(username: str | None, role: str) -> dict | None:
    """The account if it has `role` (through accounts.check_role, the same check as the Streamlit pages)."""
    if not username:
        return None
    return accounts.check_role({"authentication_status": True, "username": username}, role)
