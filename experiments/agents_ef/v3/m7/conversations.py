"""Read closed conversations from the prototype's traces (traces/<run_id>.jsonl, one JSON line per step).

    load_conversations(folder) -> list of records, one per closed conversation (= one pipeline_done line)

A record keeps only what M7 needs, each item with the trace line it came from (file:line), so every flag M7
raises can be checked by a person in the original trace. Nothing is written back.
Format: callverse/trace.py ({time, run_id, step, actor, data}); steps from callverse/pipeline.py,
coordinator.py, slm/writer.py, tools/registry.py, intake/intake.py.
"""

import json
from datetime import datetime
from pathlib import Path


def _ref(path: Path, n: int) -> str:
    return f"{path.name}:{n}"


def parse_trace(path: Path) -> list[dict]:
    """All closed conversations in one trace file (a file can hold several tickets, e.g. a queue batch)."""
    lines = []
    with open(path, encoding="utf-8") as f:
        for n, raw in enumerate(f, start=1):
            raw = raw.strip()
            if raw:
                try:
                    lines.append((n, json.loads(raw)))
                except ValueError:
                    lines.append((n, {"step": "unreadable_line", "data": {}}))
    convs, cur = [], None
    for n, rec in lines:
        step, data = rec.get("step"), rec.get("data") or {}
        if step == "intake_start" or cur is None:
            cur = {"file": path.name, "run_id": rec.get("run_id"), "start": rec.get("time"), "ticket": None,
                   "client_text": data.get("text"), "steps": [], "tool_calls": [], "checks": [], "decisions": [],
                   "proposals": [], "proposal_refusals": [], "send_backs": [], "events": [], "slm_checks": [],
                   "intake_facts": None}
        cur["steps"].append(step)
        ref = _ref(path, n)
        if step == "intake_ticket":
            cur["ticket"] = {k: data.get(k) for k in ("ticket_id", "order_id", "main_reason", "priority_label",
                                                      "emotion", "sentiment", "style")}
        elif step == "intake_facts":
            cur["intake_facts"] = {**data, "ref": ref}
        elif step == "tool_call":
            cur["tool_calls"].append({"agent": data.get("agent"), "tool": data.get("tool"), "args": data.get("args"),
                                      "result": data.get("result"), "ref": ref})
        elif step == "coordinator_check":
            cur["checks"].append({**data, "ref": ref})
        elif step == "coordinator_decision":
            cur["decisions"].append({**data, "ref": ref})
        elif step == "proposal":
            cur["proposals"].append({**data, "ref": ref})
        elif step == "proposal_refused":
            cur["proposal_refusals"].append({**data, "ref": ref})
        elif step == "send_back_to_agent":
            cur["send_backs"].append({**data, "ref": ref})
        elif step in ("rule_not_searched", "agent_retry", "pipeline_error", "handover", "handover_ignored",
                      "policy_search", "internal_outcome_to_escalate", "slm_template", "unreadable_line"):
            cur["events"].append({"step": step, **data, "ref": ref})
        elif step == "slm_check":
            cur["slm_checks"].append({**data, "ref": ref})
        elif step == "pipeline_done":
            cur.update(end=rec.get("time"), done_ref=ref, route=data.get("route"), handover=data.get("handover"),
                       decision=data.get("decision"), final_reply=data.get("final_reply"),
                       reply_source=data.get("reply_source"), agent_text=data.get("agent_text"))
            cur["conversation_id"] = f"{path.stem}#{len(convs)}" if len(convs) else path.stem
            try:
                cur["seconds"] = round((datetime.fromisoformat(cur["end"]) -
                                        datetime.fromisoformat(cur["start"])).total_seconds(), 3)
            except (TypeError, ValueError):
                cur["seconds"] = None
            convs.append(cur)
            cur = None
    return convs        # a conversation without pipeline_done is still open: not returned


def load_conversations(folder) -> list[dict]:
    out = []
    for p in sorted(Path(folder).glob("*.jsonl")):
        out += parse_trace(p)
    return out


def dialogue_text(conv: dict) -> str:
    """The text Agent F's satisfaction model reads: the client's message and the reply the client received.
    (The prototype is single-turn: one client message, one final reply.)"""
    return f"Customer: {conv.get('client_text') or ''}\nAgent: {conv.get('final_reply') or ''}"
