"""Make a TEMPORARY accounts file + tickets database for trying the web UI without the pipeline (no model, no
real data touched). Usage:

    python -m webui.api.dev_fixture <folder>

It writes in <folder> only: accounts.yaml (every demo username, ONE password "demo-only", bcrypt), callverse.db
(six example tickets built with the ticket store, the way the channel saves them, with a few unusual outcomes so
the pages can be checked) and shopnova.db (the seeded sample: the store asks the simulation clock, which lives
there). Then it prints the three environment variables to set before `python -m webui.api.run`.
The real config/accounts.yaml and callverse/data/*.db are never read or written. Delete the folder when done.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bcrypt  # noqa: E402
import yaml  # noqa: E402

from callverse.auth import accounts  # noqa: E402
from callverse.data import db as shopnova_db  # noqa: E402
from callverse.data.atlas import db as atlas_db  # noqa: E402
from callverse.tickets import store  # noqa: E402

PASSWORD = "demo-only"


def write_accounts(folder: Path) -> Path:
    hashed = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=10)).decode()
    users = {u: {"name": name, "email": email, "roles": [role], "user_id": uid, "password": hashed,
                 "company": accounts.demo_company(u, role)}
             for u, name, email, role, uid in accounts.DEMO_ACCOUNTS}
    path = folder / "accounts.yaml"
    path.write_text(yaml.safe_dump({"credentials": {"usernames": users},
                                    "cookie": {"name": "demo", "key": "d" * 32, "expiry_days": 1}}), encoding="utf-8")
    return path


def ticket(company, user_id, text, reply, *, outcome, status, reason, priority, agent, extra_steps=()):
    t = store.create_ticket(company, user_id)
    mid = store.add_message(t["id"], "user", text)
    add = lambda kind, who, data: store.add_step(t["id"], mid, kind, who, data)   # noqa: E731
    add("intake", "intake", {"trace_step": "intake_ticket", "main_reason": reason, "emotion": {"label": "anger", "score": 0.83},
                             "sentiment": {"label": "negative", "score": 0.91}, "priority_label": priority,
                             "order_id": 4505 if company == "shopnova" else 7003, "seconds": 0.6})
    add("route", "router", {"trace_step": "route", "agent": agent, "reason": reason, "layer": 2})
    add("llm", "agent_b" if agent == "B" else "agents",
        {"trace_step": "llm_call", "role": "agent_b" if agent == "B" else "agents",
         "provider": "groq" if agent == "B" else "local", "model": "openai/gpt-oss-120b" if agent == "B" else "cv-qwen3.5-4b",
         "seconds": 2.4, "tokens": {"total": 1830 if agent == "B" else 640}})
    add("tool_call", agent, {"trace_step": "tool_call", "agent": agent, "tool": "get_order" if company == "shopnova" else "get_flight_booking",
                             "args": {"order_id": 4505} if company == "shopnova" else {"booking_id": 7003},
                             "result": {"id": 4505, "status": "shipped", "days_late": 8} if company == "shopnova"
                             else {"id": 7003, "flight": "AA 1234", "status": "cancelled"}})
    add("search_policy", agent, {"trace_step": "tool_call", "agent": agent, "tool": "search_policy",
                                 "args": {"query": text[:40]}, "result": {"results": [{"id": "R-REF-03", "score": 0.78}, {"id": "R-REF-01", "score": 0.71}]}})
    for kind, who, data in extra_steps:
        add(kind, who, data)
    add("coordinator", "coordinator", {"trace_step": "coordinator_check", "check": "rule_condition", "rule_id": "R-REF-03",
                                       "result": "pass", "detail": "8 days late: the rule applies"})
    add("coordinator", "coordinator", {"trace_step": "coordinator_check", "check": "amount_limit", "rule_id": "R-REF-03",
                                       "result": "pass" if outcome != "layer3_pending" else "pending",
                                       "detail": "within the finance limit" if outcome != "layer3_pending" else "above the limit: finance must decide"})
    add("coordinator", "coordinator", {"trace_step": "coordinator_decision", "outcome": outcome,
                                       "reason": {"approve": "all checks passed: refund by rule R-REF-03",
                                                  "escalate": "rebooking is not handled by an agent yet: passed to a human",
                                                  "layer3_pending": "amount above the limit: waiting for finance",
                                                  "send_back": "the proposal cites a rule that was not searched"}.get(outcome, f"outcome {outcome} recorded"),
                                       "proposal_id": "P-0001", "order_id": 4505})
    add("slm", "pipeline", {"trace_step": "final_reply", "outcome": outcome, "reply_source": "slm", "seconds": 1.9})
    store.add_message(t["id"], "assistant", reply, seconds=5.3)
    store.update_ticket(t["id"], status=status, main_reason=reason, priority=priority, lead_agent=agent)
    return t


def main(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    accounts_path = write_accounts(folder)
    shopnova_db.use_db(folder / "shopnova.db")   # the clock seeds it here, never the real file
    atlas_db.use_db(folder / "atlas_never_created.db")
    store.use_db(folder / "callverse.db")
    if (folder / "callverse.db").exists():
        (folder / "callverse.db").unlink()

    ticket("shopnova", 1, "My order 4505 is 8 days late. I want a refund.", "Your refund of 50.00 TND is approved.",
           outcome="approve", status="Solved", reason="refund_request", priority="high", agent="B",
           extra_steps=[("proposal", "proposal_tools", {"trace_step": "proposal", "action": "refund", "order_id": 4505, "amount": 50.0,
                                                        "rule_id": "R-REF-03", "user_confirmed": True, "facts_used": {"days_late": 8}})])
    ticket("shopnova", 2, "Where is my order 4506? Nobody answers.", "Your parcel is with Aramex and should arrive in 2 days.",
           outcome="approve", status="Solved", reason="tracking", priority="medium", agent="A")
    ticket("atlas", 1, "My flight was cancelled, I need to be rebooked tomorrow.", "A colleague will contact you to rebook.",
           outcome="escalate", status="Escalated", reason="rebooking", priority="high", agent="A")
    t4 = ticket("shopnova", 3, "The laptop arrived broken, refund the full 1,850 TND please.", "Your request is with our finance team.",
                outcome="layer3_pending", status="Waiting for finance", reason="refund_request", priority="high", agent="B",
                extra_steps=[("proposal", "proposal_tools", {"trace_step": "proposal", "action": "refund", "order_id": 4505, "amount": 1850.0,
                                                             "rule_id": "R-REF-03", "user_confirmed": True, "facts_used": {"days_late": 0}})])
    store.create_approval(t4["id"], 4505, 1850.0, "P-0001", company="shopnova")
    ticket("atlas", 4, "I need a photo of the damaged suitcase to be checked.", "Please send a photo of the damage.",
           outcome="ask_proof", status="Waiting for user", reason="baggage", priority="low", agent="B",
           extra_steps=[("brand_new_step", None, {"trace_step": "photo_proof_received", "ok": False, "note": "an outcome the Console has never seen"})])
    t6 = ticket("shopnova", 5, "I want to cancel order 4510.", "Can you confirm you want to cancel order 4510?",
                outcome="send_back", status="Waiting for user", reason="cancel_order", priority="medium", agent="B")
    mid = store.add_message(t6["id"], "user", "Yes, cancel it.")
    store.add_step(t6["id"], mid, "intake", "intake", {"trace_step": "intake_ticket", "main_reason": "cancel_order", "emotion": "neutral",
                                                       "sentiment": "neutral", "priority_label": "medium", "order_id": 4510, "seconds": 0.4})
    store.add_step(t6["id"], mid, "coordinator", "coordinator", {"trace_step": "coordinator_decision", "outcome": "approve",
                                                                 "reason": "the client confirmed with the cancel word", "proposal_id": "P-0002", "order_id": 4510})
    store.add_message(t6["id"], "assistant", "Order 4510 is cancelled.", seconds=4.1)
    store.update_ticket(t6["id"], status="Solved")

    print("Demo fixture written in", folder)
    print("Logins: every demo username (supervisor, admin, sara, ...) with the password", PASSWORD)
    print("Set these, then run `python -m webui.api.run`:")
    print(f"  CALLVERSE_WEBUI_ACCOUNTS={accounts_path}")
    print(f"  CALLVERSE_WEBUI_TICKETS_DB={folder / 'callverse.db'}")
    print(f"  CALLVERSE_WEBUI_SHOPNOVA_DB={folder / 'shopnova.db'}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m webui.api.dev_fixture <folder>")
    main(Path(sys.argv[1]))
