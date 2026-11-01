"""T14c check: real messages for BOTH companies through the same door as the apps, each checked by rules.

Usage (from the repo root; Ollama running, Agent B on Groq):
    set CALLVERSE_AGENTS_SET=local
    python -m scripts.run_t14c --file tests/dev/t14c_practice_messages.json [--out out/t14c_practice.json]

Copied from scripts/run_decline_check.py (T14a/T14b) and extended to Atlas Travel. For EACH message: FRESH ShopNova and
Atlas databases and clock (today = 2026-10-09), then web_chat.send(user_id, company, text), as the apps do. Layer 3 in
"queue" mode, like the apps: big refunds and every compensation wait for the admin (nothing is written). The tickets go
in their own file (out/t14c_tickets.db, deleted at the end), so callverse.db is not touched.

File format: {"messages": [{"id", "company", "user_id", "order_id" | "booking_id", "text", "expect": {...}}]}.
`expect` keys (a missing key is not checked): outcome, rule_id, refund_rows, compensation_rows, order_status,
booking_status_after, approvals_pending, approval_amount, refund_amount.

Hard checks for every message (the T14c pass bar): no crash; no leak (internal words of run_live_check.py, and the words
card / cash / city / payment / source); no wrong write (a new money row the rules do not allow, judged on the data
BEFORE the run, or on another order / booking); no "days late" / "0 days" / "late by" when the decision is not about
lateness; every must_say sentence in the reply. A daily-limit error from Groq ABORTS the run without scoring.
One line per message, a summary, and the full results in the --out file (default out/t14c_<file>.json, git-ignored).
"""

import argparse
import json
import os
import sys
import time
import traceback
from contextlib import closing
from pathlib import Path

# Like the apps: refunds above the limit and compensations wait in the finance queue (layer3_pending).
os.environ.setdefault("CALLVERSE_LAYER3_MODE", "queue")

from callverse import llm, trace
from callverse.channels import web_chat
from callverse.coordinator import atlas_coordinator
from callverse.data import clock
from callverse.data.atlas import db as atlas_db
from callverse.data.atlas import reads as atlas_reads
from callverse.data.atlas.seed import seed as seed_atlas
from callverse.data.seed import seed
from callverse.intake import intake
from callverse.kb.policies import check_condition, get_policy
from callverse.slm.writer import warm_up
from callverse.tickets import store
from scripts.quota_check import check_models
from scripts.run_decline_check import (before_run, forbidden_words, groq_tokens, last_decision, order_status, squash)
from scripts.run_live_check import OUT_DIR, abort, global_checks, pause_seconds, refund_rows

TICKETS_DB = OUT_DIR / "t14c_tickets.db"
LEAK_WORDS = ["card", "cash", "city", "payment", "source"]
LATENESS_WORDS = ["days late", "0 days", "late by"]
# Decisions that are about lateness: there the lateness words may be said.
LATENESS_RULES = ("R-REF-03", "R-DEL-02", "AT-FLT-03", "AT-FLT-04", "AT-FLT-05")


def atlas_rows(table: str) -> list[dict]:
    """All rows of an Atlas money table (refunds or compensations)."""
    with closing(atlas_db.connect()) as con:
        return [dict(r) for r in con.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()]   # our own names only


def atlas_wrong_writes(new_refunds: list, new_comps: list, booking_id, before: dict | None) -> list[str]:
    """WRONG WRITE problems for new Atlas money rows, judged on the booking's facts BEFORE the run."""
    problems = []
    for kind, rows in (("refund", new_refunds), ("compensation", new_comps)):
        for row in rows:
            if before is None or row["booking_id"] != booking_id:
                problems.append(f"WRONG WRITE: {kind} on booking {row['booking_id']}, the message is about {booking_id}")
                continue
            rule = get_policy(row["rule_id"], "atlas") if row.get("rule_id") else None
            if rule is None:
                problems.append(f"WRONG WRITE: {kind} row cites no rule ({row.get('rule_id')})")
                continue
            actions = ("refund", "cancel_hotel") if kind == "refund" else ("compensation",)
            if not any(atlas_coordinator._rule_holds(a, rule, before) for a in actions):
                problems.append(f"WRONG WRITE: rule {row['rule_id']} condition false on the data")
            elif kind == "refund" and row["amount"] > atlas_coordinator.left_to_refund(before) + 1e-9:
                problems.append(f"WRONG WRITE: refund {row['amount']} > what is left to refund")
            elif kind == "compensation" and (before["compensated"] or check_condition(
                    get_policy("AT-FLT-06", "atlas")["condition"], before)):
                problems.append("WRONG WRITE: compensation already paid or extraordinary cause")
    return problems


def expect_checks(expect: dict, got: dict) -> list[str]:
    """Problems against the message's own expectations (`got` = what the run produced)."""
    problems = []
    for key in ("outcome", "rule_id", "order_status", "booking_status_after", "approvals_pending"):
        if key in expect and got.get(key) != expect[key]:
            problems.append(f"{key} {got.get(key)} != {expect[key]}")
    for key, rows in (("refund_rows", got["refunds"]), ("compensation_rows", got["compensations"])):
        if key in expect and len(rows) != expect[key]:
            problems.append(f"{key} {len(rows)} != {expect[key]}")
    if "refund_amount" in expect and [round(a, 2) for a in got["refunds"]] != [round(expect["refund_amount"], 2)]:
        problems.append(f"refund amounts {got['refunds']} != [{expect['refund_amount']}]")
    amounts = [round(a, 2) for a in got["approval_amounts"]]
    if "approval_amount" in expect and amounts != [round(expect["approval_amount"], 2)]:
        problems.append(f"approval amounts {amounts} != [{expect['approval_amount']}]")
    return problems


def run_one(message: dict) -> dict:
    """Fresh data, one message through the channel, its checks. Never raises."""
    seed()
    seed_atlas()
    clock.reset()
    company = message.get("company", "shopnova")
    atlas = company == "atlas"
    case_id = message.get("booking_id") if atlas else message.get("order_id")
    before = None if atlas else before_run(case_id)
    atlas_before = None
    if atlas and case_id is not None and atlas_reads.booking_type(case_id):
        atlas_before = atlas_coordinator.read_facts(atlas_reads.booking_type(case_id), case_id)
    refunds_before = {r["id"] for r in (atlas_rows("refunds") if atlas else refund_rows())}
    comps_before = {r["id"] for r in atlas_rows("compensations")}
    approvals_before = {a["id"] for a in store.approvals()}
    start = time.perf_counter()
    try:
        sent = web_chat.send(message["user_id"], company, message["text"])
        error = None
    except Exception as e:  # a crash is a FAIL, never a stop of the whole check
        sent, error = {}, f"{type(e).__name__}: {e}"
        trace.log("live_check_crash", "t14c_check", {"id": message["id"], "error": error,
                                                     "traceback": traceback.format_exc()})
    seconds = round(time.perf_counter() - start, 1)
    new_refunds = [r for r in (atlas_rows("refunds") if atlas else refund_rows()) if r["id"] not in refunds_before]
    new_comps = [r for r in atlas_rows("compensations") if r["id"] not in comps_before]
    new_approvals = [a for a in store.approvals() if a["id"] not in approvals_before and a["status"] == "pending"]
    outcome, reply = sent.get("outcome"), sent.get("reply")
    ticket_id = sent.get("ticket_id")
    decision = last_decision(ticket_id) if ticket_id else {}
    booking = atlas_reads.find_booking(case_id) if atlas and case_id is not None else {}
    got = {"outcome": outcome, "rule_id": decision.get("rule_id"),
           "order_status": None if atlas else order_status(case_id),
           "booking_status_after": booking.get("status"), "approvals_pending": len(new_approvals),
           "approval_amounts": [a["amount"] for a in new_approvals],
           "refunds": [r["amount"] for r in new_refunds], "compensations": [r["amount"] for r in new_comps]}

    problems = [f"CRASH: {error}"] if error else []
    if not error:
        out = {"final_reply": reply, "decision": {"outcome": outcome}}
        problems += global_checks(message["text"], out, [] if atlas else new_refunds, before or {})
        if atlas:
            problems += atlas_wrong_writes(new_refunds, new_comps, case_id, atlas_before)
        problems += [p.replace("forbidden word", "internal words (hidden field)")
                     for p in forbidden_words(LEAK_WORDS, reply)]
        if decision.get("rule_id") not in LATENESS_RULES and decision.get("action") != "status":
            problems += forbidden_words(LATENESS_WORDS, reply)
        problems += expect_checks(message.get("expect") or {}, got)
        if decision.get("outcome") == outcome:
            problems += [f"must_say missing: {s}" for s in decision.get("must_say") or [] if squash(s) not in squash(reply)]
    return {"id": message["id"], "company": company, "case": message.get("case"), **got, "reply": reply,
            "reply_source": sent.get("reply_source"), "seconds": seconds,
            "groq_tokens": groq_tokens(ticket_id) if ticket_id else 0, "passed": not problems, "problems": problems}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--out", help="result file (default out/t14c_<file>.json)")
    parser.add_argument("--only", help="comma-separated message ids to run (default: all)")
    args = parser.parse_args()
    path = Path(args.file)
    messages = json.loads(path.read_text(encoding="utf-8"))["messages"]
    if args.only:
        messages = [m for m in messages if m["id"] in args.only.split(",")]

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

    out_file = Path(args.out) if args.out else OUT_DIR / f"t14c_{path.stem}.json"
    results = []
    for i, m in enumerate(messages):
        if i > 0:
            time.sleep(pause_seconds())   # not counted in the message's seconds
        hits_before = len(llm.DAILY_LIMIT_HITS)
        r = run_one(m)
        if len(llm.DAILY_LIMIT_HITS) > hits_before:
            abort(path, f"daily limit during message {m['id']}: {llm.DAILY_LIMIT_HITS[hits_before:]}", len(results))
        results.append(r)
        out_file.write_text(json.dumps({"partial": True, "results": results}, indent=1, ensure_ascii=False), encoding="utf-8")

    for r in results:   # printed only when the run finished (an aborted run shows no scores)
        money = f"refunds {r['refunds'] or '-'} comp {r['compensations'] or '-'} approvals {r['approval_amounts'] or '-'}"
        print(f"{r['id']:<4} {r['company']:<8} {str(r['outcome']):<14} {str(r['rule_id']):<9} {money}  "
              f"{'PASS' if r['passed'] else 'FAIL'}  {'; '.join(r['problems'])}  ({r['seconds']} s, {r['groq_tokens']} tokens)")
        print(f"     reply [{r['reply_source']}]: {r['reply']}")

    passed = sum(r["passed"] for r in results)
    count = lambda word: sum(any(p.startswith(word) for p in r["problems"]) for r in results)
    secs = [r["seconds"] for r in results]
    summary = {"file": str(path), "messages": len(results), "passed": passed, "crashes": count("CRASH"),
               "leaks": count("internal words"), "wrong_writes": count("WRONG WRITE"),
               "forbidden_words": count("forbidden word"),
               "avg_seconds": round(sum(secs) / len(secs), 1) if secs else 0, "max_seconds": max(secs) if secs else 0,
               "groq_tokens": sum(r["groq_tokens"] for r in results), "trace": str(trace_path)}
    print(f"\nSUMMARY: {passed}/{len(results)} passed · crashes {summary['crashes']} · leaks {summary['leaks']} · wrong writes "
          f"{summary['wrong_writes']} · forbidden words {summary['forbidden_words']} · avg {summary['avg_seconds']} s · "
          f"max {summary['max_seconds']} s · Groq tokens {summary['groq_tokens']}")
    out_file.write_text(json.dumps({"summary": summary, "results": results}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Results: {out_file}   Trace: {trace_path}")
    store.use_db(store.DEFAULT_DB_PATH)
    TICKETS_DB.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
