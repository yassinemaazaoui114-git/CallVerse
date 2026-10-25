"""M7 v4: closed conversations from the prototype's traces, plus what v4's checks need from the raw lines.

V3 (`v3/m7/conversations.py`) is used unchanged to build each record. v4 adds, per conversation:
  span          (first line, last line) of the conversation in its trace file (a file can hold several tickets)
  agent_runs    every agent run: {"agent": "A"/"B", "start_line", "ref"} from the `agent_start` lines.
                Needed to decide what a given agent had been TOLD by its tools when it made a claim
                (claim_unsupported): an agent run starts with no memory; a send-back starts a new run.
  lines         {line number: (step, data)} of the span, so evidence refs can be checked (verify_refs).
Why not edit V3: V3 is frozen (its tests and results must stay reproducible); v4 only adds fields.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))          # experiments/agents_ef
from v3.m7.conversations import dialogue_text, parse_trace  # noqa: E402,F401  (re-exported)


def line_no(ref: str) -> int:
    """'dev-0001.jsonl:27' -> 27."""
    return int(str(ref).rsplit(":", 1)[1])


def read_lines(path: Path) -> dict:
    out = {}
    with open(path, encoding="utf-8") as f:
        for n, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
                out[n] = (rec.get("step"), rec.get("data") or {}, rec.get("actor"))
            except ValueError:
                out[n] = ("unreadable_line", {}, None)
    return out


def parse_trace_v4(path: Path) -> list[dict]:
    path = Path(path)
    convs = parse_trace(path)
    raw = read_lines(path)
    done_lines = sorted(n for n, (step, _, _) in raw.items() if step == "pipeline_done")
    # V3 cuts conversations at intake_start (or the first line) and closes them at pipeline_done.
    starts = sorted(n for n, (step, _, _) in raw.items() if step == "intake_start")
    for i, c in enumerate(convs):
        end = line_no(c["done_ref"])
        prev_end = done_lines[done_lines.index(end) - 1] if done_lines.index(end) > 0 else 0
        # same rule as V3: the LAST intake_start after the previous ticket resets the record; without one,
        # the conversation starts at the first line after the previous ticket.
        begin = max([s for s in starts if prev_end < s <= end],
                    default=min([n for n in raw if n > prev_end], default=end))
        c["span"] = (begin, end)
        c["lines"] = {n: v for n, v in raw.items() if begin <= n <= end}
        c["agent_runs"] = [{"agent": (actor or "").replace("agent_", ""), "start_line": n, "ref": f"{path.name}:{n}"}
                           for n, (step, _, actor) in sorted(c["lines"].items()) if step == "agent_start"]
    return convs


def load_conversations_v4(folder) -> list[dict]:
    out = []
    for p in sorted(Path(folder).glob("*.jsonl")):
        out += parse_trace_v4(p)
    return out


def public_record(conv: dict) -> dict:
    """The record without the raw lines (for JSON output)."""
    return {k: v for k, v in conv.items() if k != "lines"}
