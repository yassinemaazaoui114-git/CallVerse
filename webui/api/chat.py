"""ShopNova customer chat for the API (step 3): one message through the existing channel, with live progress.

The channel is `callverse.channels.web_chat.send(user_id, company, text, ticket_id, on_step, about_order)`. It
takes 5–60 s (local models + Groq) and holds its own lock (one message at a time for the whole center). This
module adds only transport around it; no pipeline logic is copied:

- a JOB per message, run in a worker THREAD so the API's event loop stays free (the Console keeps answering);
- the `on_step` texts of the channel are recorded on the job as events and streamed to the browser as
  Server-Sent Events (SSE). Design: `POST /api/shop/chat/send` returns the SSE stream itself (the browser
  reads it with `fetch`; a native EventSource cannot POST). Events: `job` (the job id), `step` (one live
  text), `done` (the channel's saved result), `error` (the worker failed), and `: ping` comments every
  PING_SECONDS so an idle connection stays open;
- jobs are kept in memory for KEEP_SECONDS after they finish (see Registry), so a browser that lost the
  connection can ask `GET /api/shop/chat/job` what happened, or re-attach to the live stream
  (`GET /api/shop/chat/job/stream`, which replays the steps so far) WITHOUT sending the message again. A browser
  disconnect never stops the worker: the channel keeps running and saves its reply in the tickets store, which
  the browser then reloads. Stopping the API process is different: the worker is a daemon thread and dies
  with the process, so only what the channel had already written to the store survives a restart;
- duplicates: every send may carry a `client_id`. A `client_id` is bound to its message, ticket and order for
  the whole retention window: the same id with the same payload returns the same job (a double click, a retry
  after a disconnect, even a replay of A after B ran), never a second channel run; the same id with another
  payload is refused (409 `client_id_reused`). A send while the customer's job is still running is refused
  (409 `busy_user`);
- the channel is imported lazily (`send_fn()`), so a Console-only API process never loads the pipeline, the
  models or the channel. Tests set `send_fn` to a fake.

Transport state (`job.status`: running / done / failed) is separate from the business outcome (`result.outcome`:
approve, busy, not_your_order, …): a `done` job may carry the channel's "busy" reply, which is a normal result.
"""

import json
import threading
import time
import uuid
from datetime import datetime

PING_SECONDS = 15        # keep-alive comment on an idle stream
KEEP_SECONDS = 15 * 60   # a finished job stays in memory this long (recovery and duplicate protection window)
MAX_TEXT = 2000

_send_fn = None


def send_fn():
    """The channel's send function, imported on first use only (the Console must stay light)."""
    global _send_fn
    if _send_fn is None:
        from callverse.channels import web_chat   # noqa: WPS433 (lazy on purpose)
        _send_fn = web_chat.send
    return _send_fn


def use_send_fn(fn) -> None:
    """Tests: replace the channel by a fake (None = back to the real one)."""
    global _send_fn
    _send_fn = fn


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Job:
    """One message being handled by the channel, and everything the browser may ask about it."""

    def __init__(self, user_id: int, company: str, text: str, ticket_id: str | None, about_order: int | None,
                 client_id: str | None):
        self.id = uuid.uuid4().hex
        self.user_id, self.company = int(user_id), company
        self.text, self.ticket_id, self.about_order, self.client_id = text, ticket_id, about_order, client_id
        self.status = "running"           # running | done | failed   (transport state)
        self.result: dict | None = None   # the channel's result (business outcome inside)
        self.error: dict | None = None
        self.events: list[dict] = []      # [{event, data}] in order: job, step..., done | error
        self.started, self.finished = time.monotonic(), None
        self.started_at = _now()
        self._cond = threading.Condition()
        self._push("job", {"job_id": self.id, "ticket_id": ticket_id, "started_at": self.started_at})

    def _push(self, event: str, data: dict) -> None:
        with self._cond:
            self.events.append({"event": event, "data": data})
            self._cond.notify_all()

    def on_step(self, text: str) -> None:
        self._push("step", {"text": str(text), "at": _now()})

    def finish(self, result: dict) -> None:
        self.result, self.status, self.finished = result, "done", time.monotonic()
        self._push("done", result)

    def fail(self, exc: BaseException) -> None:
        self.error = {"error": "worker_error", "message": f"{type(exc).__name__}: {exc}"[:300]}
        self.status, self.finished = "failed", time.monotonic()
        self._push("error", self.error)

    @property
    def payload(self) -> tuple:
        """What a client_id is bound to: the same id may only ever mean this message on this ticket / order."""
        return (self.text, self.ticket_id, self.about_order)

    @property
    def steps(self) -> list[dict]:
        return [e["data"] for e in self.events if e["event"] == "step"]

    def view(self) -> dict:
        """What GET /api/shop/chat/job returns: enough to recover a conversation without re-sending."""
        return {"job_id": self.id, "status": self.status, "client_id": self.client_id, "ticket_id": self.ticket_id,
                "text": self.text, "about_order": self.about_order, "started_at": self.started_at,
                "steps": self.steps, "result": self.result, "error": self.error}

    def wait_events(self, index: int, timeout: float) -> list[dict]:
        """The events from `index` on; waits up to `timeout` s for a new one (empty list = nothing yet)."""
        with self._cond:
            if len(self.events) <= index and self.status == "running":
                self._cond.wait(timeout)
            return self.events[index:]

    def expired(self) -> bool:
        return self.finished is not None and time.monotonic() - self.finished > KEEP_SECONDS


class Registry:
    """The jobs of the customers, with the duplicate rules. One lock: FastAPI handlers run in threads.

    Two indexes, kept apart on purpose:
    - `_by_client[(company, user id, client_id)]` = the job that `client_id` started, for the whole retention
      window (KEEP_SECONDS after it finished). A replay of A after B still finds A and never runs the channel
      again; a `client_id` reused with a DIFFERENT text / ticket / order is refused (it is not the same request);
    - `_current[(company, user id)]` = the customer's latest job (the "is something running?" pointer and what
      GET /api/shop/chat/job reports).
    Storage is bounded: finished jobs older than KEEP_SECONDS are dropped on every access, and when more than
    MAX_JOBS are kept the oldest FINISHED ones go first (a running job is never dropped).
    """

    MAX_JOBS = 500

    def __init__(self):
        self._by_client: dict[tuple[str, int, str], Job] = {}
        self._current: dict[tuple[str, int], Job] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(company: str, user_id: int) -> tuple[str, int]:
        return company, int(user_id)

    def _prune(self) -> None:
        """Drop expired finished jobs; then, if still too many, the oldest finished ones. Lock held by caller."""
        for key, job in list(self._by_client.items()):
            if job.expired():
                del self._by_client[key]
        for key, job in list(self._current.items()):
            if job.expired():
                del self._current[key]
        if len(self._by_client) > self.MAX_JOBS:
            finished = sorted((j for j in self._by_client.values() if j.finished is not None), key=lambda j: j.finished)
            for job in finished[: len(self._by_client) - self.MAX_JOBS]:
                self._by_client.pop((job.company, job.user_id, job.client_id), None)

    def current(self, company: str, user_id: int) -> Job | None:
        with self._lock:
            self._prune()
            return self._current.get(self._key(company, user_id))

    def start(self, user_id: int, company: str, text: str, ticket_id: str | None, about_order: int | None,
              client_id: str | None, run) -> tuple[Job, bool]:
        """(job, created).
        - a known client_id with the SAME payload: that job again, whatever came after it (no second run);
        - a known client_id with ANOTHER payload: ValueError("client_id_reused");
        - another job of this customer still running: ValueError("busy_user");
        - otherwise a new job, run by `run(job)` in a thread."""
        with self._lock:
            self._prune()
            key = self._key(company, user_id)
            if client_id:
                known = self._by_client.get((company, int(user_id), client_id))
                if known is not None:
                    if known.payload != (text, ticket_id, about_order):
                        raise ValueError("client_id_reused")
                    return known, False
            running = self._current.get(key)
            if running is not None and running.status == "running":
                raise ValueError("busy_user")
            job = Job(user_id, company, text, ticket_id, about_order, client_id)
            self._current[key] = job
            if client_id:
                self._by_client[(company, int(user_id), client_id)] = job
            self._prune()   # keep the bound after the insert too (the new job is running: never dropped)
        threading.Thread(target=run, args=(job,), daemon=True, name=f"chat-{job.id[:8]}").start()
        return job, True

    def clear(self) -> None:
        with self._lock:
            self._by_client.clear()
            self._current.clear()


def run_job(job: Job) -> None:
    """The worker: the channel, with its lock and rules exactly as the Streamlit page calls it."""
    try:
        result = send_fn()(job.user_id, job.company, job.text, ticket_id=job.ticket_id, on_step=job.on_step,
                           about_order=job.about_order)
        job.finish(result)
    except BaseException as e:   # noqa: BLE001 — a worker must report, never die silently
        job.fail(e)


def sse(event: str, data: dict) -> str:
    """One SSE frame. The JSON is one line, so a `data:` line never splits a frame."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def stream(job: Job, from_index: int = 0):
    """Yield the job's events as SSE from `from_index`, then stop after `done` / `error`. While the worker is
    still running and nothing new arrived, a `: ping` comment keeps the connection alive."""
    index = from_index
    yield ": connected\n\n"
    while True:
        events = job.wait_events(index, PING_SECONDS)
        if not events:
            if job.status != "running":
                return
            yield ": ping\n\n"
            continue
        for e in events:
            yield sse(e["event"], e["data"])
            index += 1
            if e["event"] in ("done", "error"):
                return
