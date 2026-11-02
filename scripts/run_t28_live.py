"""T28 live check (step 09): short CONVERSATIONS through the same door as the apps, with the real models.

Usage (from the repo root; Ollama running with callverse-m2-v3 and qwen2.5:1.5b):
    set CALLVERSE_AGENTS_SET=local
    set CALLVERSE_LAYER3_MODE=queue
    python -m scripts.run_t28_live [--only S1,U2] [--out out/t28_live.json]

Like scripts/run_t14c.py: before EACH scenario the ShopNova and Atlas databases and the clock are rebuilt from their seed
(today = 2026-10-09), so a scenario never sees another one's writes. WARNING: that rebuilds callverse/data/shopnova.db
and atlas.db (make a copy first if the demo data matters). The tickets go in their own file (out/t28_live_tickets.db),
so callverse.db is not touched. Every message of a scenario goes on the SAME ticket (ticket_id of the first reply), as
in the web chat. Messages are Claude-written practice messages (not from any test set).

Per message it records: text, ticket, outcome, seconds, reply, the handovers (to C / to B, urgent), and per scenario
the refund rows written for the order. The urgent candidates U1-U4 look for ONE message that gives A -> C -> B
(T28 step 7b: the Urgent badge, F5b in docs/DEMO_RUNBOOK.md).
"""

import argparse
import json
import time
from pathlib import Path

from callverse import trace
from callverse.channels import web_chat
from callverse.data import clock
from callverse.data.atlas.seed import seed as seed_atlas
from callverse.data.seed import seed
from callverse.intake import intake
from callverse.slm.writer import warm_up
from callverse.tickets import store
from callverse.tools.registry import run_tool

OUT_DIR = Path("out")
TICKETS_DB = OUT_DIR / "t28_live_tickets.db"

SCENARIOS = [
    # Step 9: the 3-message conversation (memory for "it", then B's "Please confirm" and a bare yes).
    {"id": "S1", "what": "3 messages: status, money back for 'it', bare yes", "user_id": 1, "order_id": 4512,
     "messages": ["Where is my order 4512?", "It is so late. Can I get my money back for it?", "yes"]},
    # Step 9: C's offer then "Yes" (P20, already worked: F5).
    {"id": "S2", "what": "C offer then Yes (F5)", "user_id": 1, "order_id": 4512,
     "messages": ["Order 4512 is late and I need it tomorrow, it's a birthday gift!", "Yes"]},
    # Step 9: two requests in one message (refund 4512 + where is 4509, both Sara's).
    {"id": "S3", "what": "two requests in one message", "user_id": 1, "order_id": 4512,
     "messages": ["Please refund order 4512, it is very late, and where is order 4509?"]},
    # Step 9: a bare yes with nothing open.
    {"id": "S4", "what": "bare yes, nothing open", "user_id": 1, "order_id": 4512, "messages": ["yes"]},
    # Step 7b: candidates for A -> C -> [HANDOVER: B] (urgent refund).
    {"id": "U1", "what": "urgent candidate", "user_id": 1, "order_id": 4512,
     "messages": ["Order 4512 was a birthday gift for tomorrow and it is still stuck. It will be too late now, so I "
                  "just want my money back."]},
    {"id": "U2", "what": "urgent candidate", "user_id": 1, "order_id": 4512,
     "messages": ["I needed order 4512 for my wedding tomorrow, it is urgent! It won't come in time, give me my money "
                  "back."]},
    {"id": "U3", "what": "urgent candidate", "user_id": 1, "order_id": 4512,
     "messages": ["My order 4512 is late and it was urgent, I needed it for my exam tomorrow. Forget the replacement, "
                  "I want my money back."]},
    {"id": "U4", "what": "urgent candidate", "user_id": 1, "order_id": 4512,
     "messages": ["Urgent: order 4512 was for my daughter's birthday today and it never came. Please return my "
                  "money."]},
    # Second try for step 9 (S1's B approved at once, so no "Please confirm" was asked): softer money words.
    {"id": "P1", "what": "B may ask first, then a bare yes", "user_id": 1, "order_id": 4512,
     "messages": ["Order 4512 is so late. Maybe I should just ask for my money back?", "yes"]},
    {"id": "P3", "what": "B may ask first, then a bare yes", "user_id": 1, "order_id": 4512,
     "messages": ["If order 4512 does not come this week, I would like my money back.", "yes"]},
    # Third try for step 9: U5's text made B ask "Please confirm" live; then the bare yes.
    {"id": "P5", "what": "B asks Please confirm, then a bare yes, then yes again", "user_id": 1, "order_id": 4512,
     "messages": ["Order 4512 is late and I need it tomorrow for a birthday. If it can't arrive in time, I'd rather "
                  "have the money returned to me.", "yes", "yes"]},
    # Second try for step 7b: urgency first, softer money words, so Intake may route to A (then A -> C -> B).
    {"id": "U5", "what": "urgent candidate", "user_id": 1, "order_id": 4512,
     "messages": ["Order 4512 is late and I need it tomorrow for a birthday. If it can't arrive in time, I'd rather "
                  "have the money returned to me."]},
    {"id": "U6", "what": "urgent candidate", "user_id": 1, "order_id": 4512,
     "messages": ["My order 4512 was supposed to be a birthday gift tomorrow and it is still stuck! It is urgent, "
                  "please help me, otherwise I want it reimbursed."]},
    {"id": "U7", "what": "urgent candidate", "user_id": 1, "order_id": 4512,
     "messages": ["Order 4512 is late and I need it by tomorrow, it is urgent. No replacement please, money back "
                  "instead."]},
]


def handovers(ticket_id: str, message_id: int) -> list[str]:
    """The handovers of one message, e.g. ["C by agent_A", "B by agent_C (urgent)"]."""
    out = []
    for s in store.steps(ticket_id):
        d = s["data"]
        if s["message_id"] == message_id and d.get("trace_step") == "handover":
            out.append(f"{d.get('to')} by {d.get('by')}" + (" (urgent)" if d.get("urgent") else ""))
    return out


def run_scenario(sc: dict) -> dict:
    seed()
    seed_atlas()
    clock.reset()
    ticket_id, turns = None, []
    for text in sc["messages"]:
        start = time.perf_counter()
        out = web_chat.send(sc["user_id"], "shopnova", text, ticket_id=ticket_id)
        ticket_id = out["ticket_id"]
        user_messages = [m for m in store.messages(ticket_id) if m["sender"] == "user"]
        turns.append({"text": text, "ticket": ticket_id, "outcome": out["outcome"], "status": out["status"],
                      "seconds": round(time.perf_counter() - start, 1), "reply": out["reply"],
                      "handovers": handovers(ticket_id, user_messages[-1]["id"])})
        print(f"  {sc['id']} {text[:60]!r} -> {out['outcome']} ({turns[-1]['seconds']} s) {turns[-1]['handovers']}")
    refunds = run_tool("B", "get_refunds", {"order_id": sc["order_id"]})
    return {**sc, "turns": turns, "refunded_total": refunds.get("refunded_total"),
            "refund_rows": len(refunds.get("refunds", [])),
            "approvals": [dict(a) for a in store.approvals() if a["ticket_id"] == ticket_id]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="comma-separated scenario ids")
    parser.add_argument("--out", default=str(OUT_DIR / "t28_live.json"))
    args = parser.parse_args()
    scenarios = [s for s in SCENARIOS if not args.only or s["id"] in args.only.split(",")]
    OUT_DIR.mkdir(exist_ok=True)
    TICKETS_DB.unlink(missing_ok=True)
    store.use_db(TICKETS_DB)
    trace_path = trace.start_run()
    intake.load_models()
    warm_up()
    results = []
    for sc in scenarios:
        print(f"{sc['id']}: {sc['what']}")
        results.append(run_scenario(sc))
    Path(args.out).write_text(json.dumps({"trace": str(trace_path), "results": results}, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    store.use_db(store.DEFAULT_DB_PATH)
    print(f"Saved {args.out} (trace {trace_path})")


if __name__ == "__main__":
    main()
