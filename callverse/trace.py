"""Trace logger: every step of a run is written as one JSON line in traces/<run_id>.jsonl.

A "run" is one conversation (for example one execution of scripts/run_demo.py).
Each line says WHO did the step (actor), WHAT kind of step it was, the data (input, output,
tool calls...) and WHEN it happened. This is what lets us show the teacher exactly what happened.
"""

import json
from datetime import datetime
from pathlib import Path

from callverse.config import PROJECT_ROOT

_trace_dir = PROJECT_ROOT / "traces"
_run_id = None


def start_run(run_id: str | None = None, trace_dir: str | Path | None = None) -> Path:
    """Start a new trace file and return its path. Without a run_id, the current time is used."""
    global _run_id, _trace_dir
    if trace_dir is not None:
        _trace_dir = Path(trace_dir)
    _run_id = run_id or datetime.now().strftime("run_%Y%m%d_%H%M%S_%f")
    return current_path()


def current_path() -> Path:
    """Path of the trace file of the current run (starts a run automatically if needed)."""
    if _run_id is None:
        start_run()
    return _trace_dir / f"{_run_id}.jsonl"


def log(step: str, actor: str, data: dict) -> None:
    """Append one JSON line: {time, run_id, step, actor, data}."""
    path = current_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "time": datetime.now().isoformat(timespec="milliseconds"),
        "run_id": _run_id,
        "step": step,      # e.g. "llm_call", "tool_call", "tool_refused", "final_answer"
        "actor": actor,    # e.g. "llm", "agent_A", "registry"
        "data": data,
    }
    with open(path, "a", encoding="utf-8") as f:
        # default=str turns anything not JSON-friendly (dates...) into text instead of crashing.
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    for listener in list(_listeners):
        try:
            listener(record)
        except Exception:   # a listener (e.g. the web page showing live steps) must never break a run
            pass


# T17: listeners = functions called with each record just after it is written (live steps in the chat).
# The trace file stays the reference; a listener only gets a copy of what was written.
_listeners: list = []


def add_listener(fn) -> None:
    """Call fn(record) for every new trace line, until remove_listener(fn)."""
    _listeners.append(fn)


def remove_listener(fn) -> None:
    """Stop calling fn (no error if it was not registered)."""
    if fn in _listeners:
        _listeners.remove(fn)
