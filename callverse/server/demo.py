"""Demo screen (P09): type a client message or press a story button, and see how CallVerse handled it.

This is a small first version of the back office. It adds no logic of its own:
- a message goes through the ONE pipeline: callverse.pipeline.handle();
- the stories reuse the scenario helpers of scripts/run_scenario.py (imported, not copied);
- the stages shown on the page are read back from that run's trace file (read only).

Safety, because the server keeps running between requests:
- the demo routes are OFF by default (config.yaml -> server.demo_enabled: false): then they answer 404;
- one request at a time (a lock): the demo is single-user, a second click while busy gets 409;
- each request gets its own trace run (run_id = that run's file); the server's own trace is put back after;
- S2's injected error wraps pipeline.review only for that request (try/finally), so it never leaks into later ones;
- a POST coming from another website (Origin header not this server) is refused (403);
- a request whose Host is not 127.0.0.1:<port> or localhost:<port> is refused (403; port 8000 or server.port);
- anything that looks like an API key is removed from every answer.
"""

import importlib
import json
import re
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from callverse import pipeline, trace
from callverse.config import load_config
from callverse.data import clock
from callverse.data.seed import seed

PAGE = Path(__file__).resolve().parent / "demo.html"
RUN_ID_RE = re.compile(r"^run_[A-Za-z0-9_]+$")
KEY_RE = re.compile(r"gsk_[A-Za-z0-9]{8,}|AIza[0-9A-Za-z_\-]{10,}|sk-[A-Za-z0-9_\-]{16,}")
SHORT = 160   # characters kept for long values on the cards

LOCK = threading.Lock()
# Not listed on /docs: the demo routes are off (404) unless config.yaml turns them on, so listing them
# would be misleading; and the normal server API keeps no route that moves the clock (P08 test).
router = APIRouter(include_in_schema=False)


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------
def demo_enabled() -> bool:
    return bool((load_config().get("server") or {}).get("demo_enabled", False))


def answer(data: Any, status: int = 200) -> JSONResponse:
    """JSON answer with anything that looks like an API key removed (defence in depth)."""
    text = KEY_RE.sub("[redacted]", json.dumps(data, ensure_ascii=False, default=str))
    return JSONResponse(json.loads(text), status_code=status)


def allowed_hosts() -> set[str]:
    """The only Host headers the demo answers: this PC, on the server's port (config server.port, default 8000)."""
    port = (load_config().get("server") or {}).get("port", 8000)
    return {f"127.0.0.1:{port}", f"localhost:{port}"}


def refusal(request: Request) -> JSONResponse | None:
    """None if the demo request may run; otherwise the error answer (404 when off, 403 wrong host / cross-site)."""
    if not demo_enabled():
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    if request.headers.get("host", "").lower() not in allowed_hosts():
        return JSONResponse({"error": "host refused: the demo answers only on this PC"}, status_code=403)
    origin = request.headers.get("origin")
    if request.method == "POST" and origin:
        own = f"{request.url.scheme}://{request.headers.get('host', '')}"
        if origin.rstrip("/") != own:
            return JSONResponse({"error": "cross-site request refused"}, status_code=403)
    return None


class _Busy(Exception):
    pass


class _OwnTraceRun:
    """Give one demo request its own trace run, then put the server's trace back (used under LOCK)."""

    def __enter__(self):
        self.saved = (trace._run_id, trace._trace_dir)
        self.path = trace.start_run()
        return self.path

    def __exit__(self, *exc):
        trace._run_id, trace._trace_dir = self.saved
        return False


def locked(fn):
    """Run fn under the demo lock; a second request while one is running gets 409 (single-user demo)."""
    if not LOCK.acquire(blocking=False):
        return answer({"error": "the demo is busy with another request, try again"}, 409)
    try:
        return fn()
    finally:
        LOCK.release()


# ---------------------------------------------------------------------------
# Running a message / a story
# ---------------------------------------------------------------------------
def _run(text: str, inject: bool = False) -> dict:
    """One pipeline run in its own trace file. inject=True: S2's injected first amount (always undone)."""
    with _OwnTraceRun() as path:
        run_id = path.stem
        start = time.perf_counter()
        original_review = pipeline.review
        try:
            if inject:
                from scripts.run_scenario import inject_first_amount   # reuse, do not copy
                pipeline.review = inject_first_amount(original_review)
            out = pipeline.handle(text)
            result = {"run_id": run_id, "final_reply": out["final_reply"], "reply_source": out["reply_source"],
                      "route": out["route"], "decision": out["decision"]}
        except Exception as e:   # e.g. a model is missing: show where it stopped instead of crashing
            result = {"run_id": run_id, "error": f"{type(e).__name__}: {e}"}
        finally:
            pipeline.review = original_review
        result["seconds"] = round(time.perf_counter() - start, 2)
    result["stages"] = stages(read_run(run_id) or [])
    return result


def stories() -> dict:
    """The stories available on this branch: the scenario table of scripts/run_scenario.py."""
    from scripts.run_scenario import SCENARIOS
    return SCENARIOS


def notifier_run():
    """The notifier's entry point once T09 provides it, else None."""
    try:
        module = importlib.import_module("callverse.notifier.notifier")
    except ImportError:
        return None
    for name in ("run_notifier", "run", "send_pending", "notify_pending"):
        if callable(getattr(module, name, None)):
            return getattr(module, name)
    return None


# ---------------------------------------------------------------------------
# Trace -> stages (read only)
# ---------------------------------------------------------------------------
def read_run(run_id: str) -> list[dict] | None:
    """The trace lines of one run, or None if the id is not a run id or the file does not exist."""
    if not RUN_ID_RE.match(run_id or ""):
        return None
    folder = Path(trace._trace_dir).resolve()
    path = (folder / f"{run_id}.jsonl").resolve()
    if path.parent != folder or not path.exists():
        return None
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _short(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= SHORT else text[:SHORT] + " ..."


def _item(text: str, status: str = "info", **data) -> dict:
    return {"text": text, "status": status, **({"data": data} if data else {})}


def stages(records: list[dict]) -> list[dict]:
    """Group a run's trace into the stages of the demo screen (only stages with something to show)."""
    order = ["Intake", "Route", "Agent", "Coordinator", "Platform writes", "Final reply", "Notifications", "Clock"]
    out = {name: [] for name in order}
    for r in records:
        s, a, d = r["step"], r["actor"], r.get("data") or {}
        if s == "intake_ticket":
            reasons = ", ".join(f"{x['reason']} ({x['score']})" if x.get("score") is not None else x["reason"]
                                for x in d.get("reasons", []))
            out["Intake"] += [
                _item(f"order id: {d.get('order_id')}"),
                _item(f"reasons: {reasons or 'none'}; main reason: {d.get('main_reason')}"),
                _item(f"emotion: {(d.get('emotion') or {}).get('label')} ({(d.get('emotion') or {}).get('score')}); "
                      f"sentiment: {(d.get('sentiment') or {}).get('label')} ({(d.get('sentiment') or {}).get('score')})"),
                _item(f"priority: {d.get('priority_label')} ({d.get('priority_score')})"
                      + (" - needed the LLM fallback" if d.get("needs_llm") else ""))]
        elif s == "intake_llm_fallback":
            out["Intake"].append(_item(f"LLM fallback: {_short(d.get('result'))}", "warn"))
        elif s == "route":
            out["Route"].append(_item(f"agent {d.get('agent')} (layer {d.get('layer')}), reason {d.get('reason')}, "
                                      f"priority {d.get('priority_label')}"))
        elif s == "handover":
            out["Route"].append(_item(f"handover to agent {d.get('to')} by {d.get('by')}: \"{d.get('text')}\""))
        elif s == "agent_start":
            out["Agent"].append(_item(f"{d.get('agent')} starts (tools: {', '.join(d.get('allowed_tools', []))})"))
        elif s == "tool_call" and a == "registry" and str(d.get("agent")).upper() == "INTAKE":
            out["Intake"].append(_item(f"read tool {d.get('tool')}({_short(d.get('args'))}) -> {_short(d.get('result'))}"))
        elif s == "tool_call" and a == "registry":
            out["Agent"].append(_item(f"{d.get('agent')} tool {d.get('tool')}({_short(d.get('args'))}) -> "
                                      f"{_short(d.get('result'))}"))
        elif s == "tool_refused":
            out["Agent"].append(_item(f"REFUSED tool {d.get('tool')} for agent {d.get('agent')}", "fail"))
        elif s == "policy_search":
            found = [x.get("id") for x in d.get("results", [])] if isinstance(d.get("results"), list) else ""
            out["Agent"].append(_item(f"policy search \"{_short(d.get('query'))}\" -> {found}"))
        elif s in ("proposal", "proposal_refused"):
            out["Agent"].append(_item(f"{'proposal' if s == 'proposal' else 'proposal REFUSED'}: {_short(d)}",
                                      "info" if s == "proposal" else "fail"))
        elif s == "llm_call" and d.get("role") != "slm":
            tokens = (d.get("tokens") or {}).get("total")
            out["Agent"].append(_item(f"LLM {d.get('model')} ({d.get('role')}): {tokens} tokens, {d.get('seconds')} s"))
        elif s in ("llm_wait", "llm_fallback", "llm_skip"):
            stage = "Final reply" if d.get("role") == "slm" else "Agent"
            out[stage].append(_item(f"{s.replace('_', ' ')}: {d.get('model')} "
                                    f"{d.get('seconds', '') or _short(d.get('error') or d.get('reason') or '')}", "warn"))
        elif s == "inject_error":
            out["Agent"].append(_item(f"INJECTED ERROR (demo S2): amount {d.get('original_amount')} -> "
                                      f"{d.get('injected_amount')}", "warn"))
        elif s == "send_back_to_agent":
            out["Agent"].append(_item(f"back to agent {d.get('agent')}: {_short(d.get('note'))}", "warn"))
        elif s == "coordinator_check":
            ok = d.get("result") == "pass"
            out["Coordinator"].append(_item(f"{d.get('check')} {d.get('rule_id') or ''}: {'PASS' if ok else 'FAIL'}"
                                            f" - {_short(d.get('detail') or '')}", "pass" if ok else "fail"))
        elif s == "rule_not_searched":
            out["Coordinator"].append(_item(f"warning: rule {d.get('rule_id')} was not searched by the agent", "warn"))
        elif s == "layer3_decision":
            res = d.get("result") or {}
            out["Coordinator"].append(_item(f"Layer 3 (finance): {res.get('decision') or res.get('error')} "
                                            f"for {res.get('amount')} TND", "pass" if res.get("decision") in
                                            ("approved", "not_required") else "fail"))
        elif s == "coordinator_decision":
            outcome = d.get("outcome")
            status = {"approve": "pass", "info": "info", "send_back": "warn"}.get(outcome, "fail")
            out["Coordinator"].append(_item(f"DECISION {str(outcome).upper()} {d.get('proposal_id') or ''}: "
                                            f"{_short(d.get('reason') or '')}", status))
        elif s == "internal_outcome_to_escalate":
            out["Coordinator"].append(_item(f"{d.get('from')} at the end of the case -> escalate", "warn"))
        elif s in ("db_write", "db_write_refused"):
            what = d.get("result") if s == "db_write" else d.get("reason")
            out["Platform writes"].append(_item(f"{d.get('function')}: {_short(what)}",
                                                "pass" if s == "db_write" else "fail"))
        elif s in ("slm_check", "slm_template"):
            ok = d.get("passed")
            label = "template used" if s == "slm_template" else f"SLM attempt {d.get('attempt')} check"
            out["Final reply"].append(_item(f"{label}: {'PASS' if ok else 'FAIL ' + _short(d.get('problems'))}",
                                            "pass" if ok else "fail"))
        elif s == "llm_call" and d.get("role") == "slm":
            out["Final reply"].append(_item(f"SLM {d.get('model')}: {d.get('seconds')} s"))
        elif s == "final_reply":
            out["Final reply"].append(_item(f"reply [{d.get('reply_source')}] in {d.get('seconds')} s: "
                                            f"{d.get('reply')}", "pass"))
        elif s == "notification_sent":
            out["Notifications"].append(_item(f"sent to order {d.get('order_id')} ({d.get('event')}) "
                                              f"[{d.get('reply_source')}]: {d.get('text')}", "pass"))
        elif s == "notifier_run":
            out["Notifications"].append(_item(f"notifier run: {d.get('sent')} message(s) sent"))
        elif a == "notifier" or s.startswith("notif"):
            out["Notifications"].append(_item(f"{s}: {_short(d)}"))
        elif s in ("clock_advance", "clock_reset", "clock_refused"):
            out["Clock"].append(_item(f"{s.replace('_', ' ')}: {_short(d)}", "fail" if s == "clock_refused" else "info"))
    return [{"name": name, "items": out[name]} for name in order if out[name]]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
class MessageIn(BaseModel):
    text: str


class HoursIn(BaseModel):
    hours: float


@router.get("/demo", response_class=HTMLResponse, include_in_schema=False)
def demo_page(request: Request):
    if (r := refusal(request)) is not None:
        return r
    return HTMLResponse(PAGE.read_text(encoding="utf-8"))


@router.post("/demo/message")
def demo_message(body: MessageIn, request: Request):
    """Run the whole pipeline on one typed client message."""
    if (r := refusal(request)) is not None:
        return r
    text = body.text.strip()
    if not text:
        return answer({"error": "empty message"}, 400)
    return locked(lambda: answer(_run(text[:2000])))


@router.post("/demo/story/{name}")
def demo_story(name: str, request: Request):
    """Run a story (S0, S1, S2, S4, ...) from fresh demo data. A story not on this branch -> {"error"}."""
    if (r := refusal(request)) is not None:
        return r
    scenario = stories().get(name.upper())
    if scenario is None:
        return answer({"error": "not available yet", "story": name.upper()})

    def go():
        seed()                         # every story starts from the same data...
        clock.reset()                  # ...and the same time (2026-10-09 09:00), like scripts/run_scenario.py
        result = {"story": name.upper(), **_run(scenario["message"], inject=scenario.get("inject", False))}
        if name.upper() == "S3":       # the rest of S3 is played with the buttons: time passes, then the notifier
            result["next"] = ["+24 h", "+30 h", "Send notifications"]
        return answer(result)
    return locked(go)


@router.get("/demo/runs/{run_id}")
def demo_run(run_id: str, request: Request):
    """The stages of one run (its trace, read only). Only ids like run_2026..., never a path."""
    if (r := refusal(request)) is not None:
        return r
    records = read_run(run_id)
    if records is None:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return answer({"run_id": run_id, "stages": stages(records)})


@router.post("/demo/clock/advance")
def demo_clock_advance(body: HoursIn, request: Request):
    if (r := refusal(request)) is not None:
        return r

    def go():
        with _OwnTraceRun():
            result = clock.advance(body.hours)
        return answer(result, 400 if "error" in result else 200)
    return locked(go)


@router.post("/demo/clock/reset")
def demo_clock_reset(request: Request):
    if (r := refusal(request)) is not None:
        return r
    return locked(lambda: answer(clock.reset()))


@router.post("/demo/notifier/run")
def demo_notifier(request: Request):
    """Send the pending notifications, once the notifier (T09) exists on this branch."""
    if (r := refusal(request)) is not None:
        return r
    run = notifier_run()
    if run is None:
        return answer({"error": "not available yet", "what": "notifier (T09)"})

    def go():
        with _OwnTraceRun() as path:
            try:
                messages = run()
            except Exception as e:
                return answer({"run_id": path.stem, "error": f"{type(e).__name__}: {e}", "messages": [],
                               "stages": stages(read_run(path.stem) or [])})
        return answer({"run_id": path.stem, "messages": messages, "sent": len(messages),
                       "stages": stages(read_run(path.stem) or [])})
    return locked(go)


@router.post("/demo/reset")
def demo_reset(request: Request):
    """Fresh demo data and the clock back to the start, so every live demo begins the same way."""
    if (r := refusal(request)) is not None:
        return r

    def go():
        seed()
        clock.reset()
        return answer({"reset": True, "clock": clock.now().isoformat()})
    return locked(go)
