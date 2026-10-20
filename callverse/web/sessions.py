"""Conversation sessions and abuse protection for the web channel, kept in server memory.

- A session = one conversation in one browser tab: its history (so the agent keeps the context),
  the identity the customer proved, and a question waiting for that proof.
  The session id is a long random secret; the browser keeps it in sessionStorage.
- Sessions expire after `session_ttl_minutes` without activity. Nothing is written to disk.
- RateLimiter: a sliding window per session and per IP, so one visitor cannot burn the API quota.

shortcut: memory only (lost on restart, one server process). Move to Redis/SQLite before running
several server processes.
"""

import secrets
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field

MAX_SESSIONS = 1000


@dataclass
class Session:
    id: str
    created: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    history: list[dict] = field(default_factory=list)     # [{"role": "user"|"assistant", "content": str}]
    verified_user_id: int | None = None                    # set after an identity check (pipeline.py)
    verified_orders: set[int] = field(default_factory=set)
    pending_text: str | None = None                         # question waiting for the identity check
    pending_orders: list[int] = field(default_factory=list)
    turns: int = 0


class SessionStore:
    def __init__(self, ttl_minutes: float):
        self.ttl = ttl_minutes * 60
        self._sessions: OrderedDict[str, Session] = OrderedDict()
        self._lock = threading.Lock()

    def create(self) -> Session:
        with self._lock:
            self._purge()
            while len(self._sessions) >= MAX_SESSIONS:
                self._sessions.popitem(last=False)          # drop the oldest
            session = Session(id=secrets.token_urlsafe(24))
            self._sessions[session.id] = session
            return session

    def get(self, session_id: str | None) -> Session | None:
        with self._lock:
            self._purge()
            session = self._sessions.get(session_id or "")
            if session:
                session.last_seen = time.time()
                self._sessions.move_to_end(session.id)
            return session

    def _purge(self) -> None:
        cutoff = time.time() - self.ttl
        for sid in [s.id for s in self._sessions.values() if s.last_seen < cutoff]:
            del self._sessions[sid]


class RateLimiter:
    """At most `limit` events per `window` seconds for each key."""

    def __init__(self, limit: int, window: float):
        self.limit, self.window = limit, window
        self._events: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and events[0] <= now - self.window:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(now)
            if len(self._events) > 10 * MAX_SESSIONS:       # forget idle keys so memory stays bounded
                for k in [k for k, v in self._events.items() if not v]:
                    del self._events[k]
            return True


class AudioStore:
    """Reply audio kept for replay, addressed by an unguessable id, removed after `ttl` seconds.

    Bounded in size: the oldest clips are dropped first.
    """

    def __init__(self, ttl: float = 900, max_bytes: int = 50_000_000):
        self.ttl, self.max_bytes = ttl, max_bytes
        self._clips: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, data: bytes) -> str:
        clip_id = secrets.token_urlsafe(16)
        with self._lock:
            self._clips[clip_id] = (time.time(), data)
            self._trim()
        return clip_id

    def get(self, clip_id: str) -> bytes | None:
        with self._lock:
            self._trim()
            item = self._clips.get(clip_id)
            return item[1] if item else None

    def _trim(self) -> None:
        cutoff = time.time() - self.ttl
        while self._clips and next(iter(self._clips.values()))[0] < cutoff:
            self._clips.popitem(last=False)
        while self._clips and sum(len(d) for _, d in self._clips.values()) > self.max_bytes:
            self._clips.popitem(last=False)
