"""Decline and cancel check (T14a): real messages through the same door as the ShopNova app, each checked by rules.

Usage (from the repo root; Ollama running, Agent B on Groq):
    set CALLVERSE_AGENTS_SET=local
    python -m scripts.run_decline_check --file tests/dev/decline_practice_messages.json

File format: {"messages": [{"id", "user_id", "order_id", "text", "expect": {...}}]}.
For EACH message: a FRESH ShopNova database and clock, then web_chat.send(user_id, "shopnova", text), as the app does.
The tickets go in their own file (out/decline_check_tickets.db, deleted at the end), so callverse.db is not touched.

Checks: the global checks of scripts/run_live_check.py (no crash, no leak, no wrong write, reply length, ...), every
sentence of the decision's must_say in the final reply, and the message's expect: outcome, rule_id, order_status (after),
refund_rows, refund_amount.
A daily-limit error from Groq ABORTS the run without scoring, as in run_live_check.py (T10b).
One line per message, a summary, and the full results in out/decline_check_<file>.json (git-ignored).
"""

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

from callverse import llm, trace
from callverse.channels import web_chat
from callverse.data import clock
from callverse.data.seed import seed
from callverse.intake import intake
from callverse.slm.writer import warm_up
from callverse.tickets import store
from callverse.tools.shopnova_tools import get_order, get_refunds, get_tracking
from scripts.quota_check import check_models
from scripts.run_live_check import OUT_DIR, abort, global_checks, pause_seconds, refund_rows

TICKETS_DB = OUT_DIR / "decline_check_tickets.db"


def squash(text: str) -> str:
    """Lower case with single spaces, for "contains this sentence" checks."""
    return " ".join(str(text).lower().split())


def before_run(order_id: int) -> dict:
    """The message's order before the run, in the shape global_checks needs. A refund on another order finds
    nothing here, so it counts as a wrong write."""
    return {"paid": {order_id: get_order(order_id)["paid"]}, "refunded": {order_id: get_refunds(order_id)["refunded_total"]},
            "tracking": {order_id: get_tracking(order_id)}}


def last_decision(ticket_id: str) -> dict:
    """The Coordinator's last decision on this ticket, from the ticket's saved steps."""
    decisions = [s["data"] for s in store.steps(ticket_id) if s["data"].get("trace_step") == "coordinator_decision"]
    return decisions[-1] if decisions else {}


def groq_tokens(ticket_id: str) -> int:
    return sum((s["data"].get("tokens") or {}).get("total") or 0 for s in store.steps(ticket_id)
               if s["data"].get("trace_step") == "llm_call" and s["data"].get("provider") == "groq")


def expect_checks(expect: dict, outcome, decision: dict, order_id: int, new_refunds: list) -> list[str]:
    """Problems against the message's own expectations."""
    problems = []
    if "outcome" in expect and outcome != expect["outcome"]:
        problems.append(f"outcome {outcome} != {expect['outcome']}")
    if "rule_id" in expect and decision.get("rule_id") != expect["rule_id"]:
        problems.append(f"rule {decision.get('rule_id')} != {expect['rule_id']}")
    status = get_order(order_id)["status"]
    if "order_status" in expect and status != expect["order_status"]:
        problems.append(f"order status {status} != {expect['order_status']}")
    if "refund_rows" in expect and len(new_refunds) != expect["refund_rows"]:
        problems.append(f"refund rows {len(new_refunds)} != {expect['refund_rows']}")
    amounts = [round(r["amount"], 2) for r in new_refunds]
    if "refund_amount" in expect and amounts != [round(expect["refund_amount"], 2)]:
        problems.append(f"refund amounts {amounts} != [{expect['refund_amount']}]")
    return problems


def run_one(message: dict) -> dict:
    """Fresh data, one message through the channel, its checks. Never raises."""
    seed()
    clock.reset()
    order_id = message["order_id"]
    before = before_run(order_id)
    refunds_before = {r["id"] for r in refund_rows()}
    start = time.perf_counter()
    try:
        sent = web_chat.send(message["user_id"], "shopnova", message["text"])
        error = None
    except Exception as e:  # a crash is a FAIL, never a stop of the whole check
        sent, error = {}, f"{type(e).__name__}: {e}"
        trace.log("live_check_crash", "decline_check", {"id": message["id"], "error": error,
                                                        "traceback": traceback.format_exc()})
    seconds = round(time.perf_counter() - start, 1)
    new_refunds = [r for r in refund_rows() if r["id"] not in refunds_before]
    outcome, reply = sent.get("outcome"), sent.get("reply")
    ticket_id = sent.get("ticket_id")
    decision = last_decision(ticket_id) if ticket_id else {}

    problems = [f"CRASH: {error}"] if error else []
    if not error:
        problems += global_checks(message["text"], {"final_reply": reply, "decision": {"outcome": outcome}}, new_refunds, before)
        problems += expect_checks(message.get("expect") or {}, outcome, decision, order_id, new_refunds)
        if decision.get("outcome") == outcome:
            problems += [f"must_say missing: {s}" for s in decision.get("must_say") or [] if squash(s) not in squash(reply)]
    return {"id": message["id"], "case": message.get("case"), "outcome": outcome, "rule_id": decision.get("rule_id"),
            "order_status": get_order(order_id)["status"], "refunds": [r["amount"] for r in new_refunds], "reply": reply,
            "reply_source": sent.get("reply_source"), "seconds": seconds,
            "groq_tokens": groq_tokens(ticket_id) if ticket_id else 0, "passed": not problems, "problems": problems}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    args = parser.parse_args()
    path = Path(args.file)
    messages = json.loads(path.read_text(encoding="utf-8"))["messages"]

    OUT_DIR.mkdir(exist_ok=True)
    TICKETS_DB.unlink(missing_ok=True)
    store.use_db(TICKETS_DB)
    trace_path = trace.start_run()
    intake.load_models()
    warm = warm_up()
    if not warm["ok"]:
        print(f"Warning: {warm['warning']} ({warm['error']})")

    quota = check_models()
    if any(q["status"] == "daily_limit" for q in quota):
        abort(path, f"daily limit before the start: {[q['model'] for q in quota if q['status'] == 'daily_limit']}", 0)

    results = []
    for i, m in enumerate(messages):
        if i > 0:
            time.sleep(pause_seconds())   # not counted in the message's seconds
        hits_before = len(llm.DAILY_LIMIT_HITS)
        r = run_one(m)
        if len(llm.DAILY_LIMIT_HITS) > hits_before:
            abort(path, f"daily limit during message {m['id']}: {llm.DAILY_LIMIT_HITS[hits_before:]}", len(results))
        results.append(r)

    for r in results:   # printed only when the run finished (an aborted run shows no scores)
        print(f"{r['id']:<4} {str(r['outcome']):<14} {str(r['rule_id']):<9} {r['order_status']:<15} refunds {r['refunds'] or '-'}  "
              f"{'PASS' if r['passed'] else 'FAIL'}  {'; '.join(r['problems'])}  ({r['seconds']} s, {r['groq_tokens']} tokens)")
        print(f"     reply [{r['reply_source']}]: {r['reply']}")

    passed = sum(r["passed"] for r in results)
    count = lambda word: sum(any(p.startswith(word) for p in r["problems"]) for r in results)
    secs = [r["seconds"] for r in results]
    summary = {"file": str(path), "messages": len(results), "passed": passed, "crashes": count("CRASH"),
               "leaks": count("internal words"), "wrong_writes": count("WRONG WRITE"),
               "avg_seconds": round(sum(secs) / len(secs), 1) if secs else 0, "max_seconds": max(secs) if secs else 0,
               "groq_tokens": sum(r["groq_tokens"] for r in results), "trace": str(trace_path)}
    print(f"\nSUMMARY: {passed}/{len(results)} passed · crashes {summary['crashes']} · leaks {summary['leaks']} · wrong writes "
          f"{summary['wrong_writes']} · avg {summary['avg_seconds']} s · max {summary['max_seconds']} s · "
          f"Groq tokens {summary['groq_tokens']}")
    out_path = OUT_DIR / f"decline_check_{path.stem}.json"
    out_path.write_text(json.dumps({"summary": summary, "results": results}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Results: {out_path}   Trace: {trace_path}")
    store.use_db(store.DEFAULT_DB_PATH)
    TICKETS_DB.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
