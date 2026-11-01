"""Make a TEMPORARY accounts file + tickets database for trying the web UI without the pipeline (no model, no
real data touched). Usage:

    python -m webui.api.dev_fixture <folder>

It writes in <folder> only: accounts.yaml (every demo username, ONE password "demo-only", bcrypt), callverse.db
(example tickets built with the ticket store, the way the channel saves them, with a few unusual outcomes so
the pages can be checked), shopnova.db and atlas.db (the seeded samples, scripted orders 4505-4515 and bookings
7001-7012). Every ticket belongs to the customer who owns the order / booking it talks about.
The three PENDING approvals of the admin queues are made by the real Coordinators in queue mode (no model): the
proposal is recorded, the checks run, the amount is above the finance limit, so the case waits for finance:
  - ShopNova: youssef's order 4515, refund 378.00 TND (R-REF-03, 8 days late, stuck at the depot);
  - Atlas: nizar's flight 7004, compensation 839.50 TND (AT-FLT-03, arrived 3 h 20 late, carrier cause);
  - Atlas: sonia's flight 7006, refund 1,900.00 TND (AT-FLT-04, departed 5 h 30 late).
Then it prints the environment variables to set before `python -m webui.api.run`.
The real config/accounts.yaml and callverse/data/*.db are never read or written. Delete the folder when done.
webui/api/tests/test_dev_fixture.py runs this file in a temp folder and decides the three cases through the API.
"""

import os
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

TEST_DATA = "[TEST DATA] "   # every fake reply starts with this, so a screenshot can never pass for a real one


def fake_slm(role_key, messages, **kwargs):
    """A FAKE reply writer for the admin decision screen (no Ollama): the reply text is marked as test data."""
    from types import SimpleNamespace
    return SimpleNamespace(content=TEST_DATA + "Fake reply written after the finance decision (no model ran).",
                           tool_calls=None)


def fake_send(user_id, company, text, ticket_id=None, on_step=None, about_order=None, **kwargs):
    """A FAKE channel for looking at the chat screen without Ollama / Groq (CALLVERSE_WEBUI_FAKE_CHAT=1).
    It behaves like web_chat.send from the outside (ticket rule, saved messages, live steps, result dict) but
    calls no model and decides nothing: the reply is a fixed sentence marked as test data. The word "busy" in
    the message gives the channel's busy outcome, "slow" waits 20 s (to try a disconnect), "fail" raises."""
    import time
    from callverse.tickets import store as tickets
    if "fail" in text.lower():
        raise RuntimeError("fake channel failure (test data)")
    t = tickets.ticket_for_message(company, user_id, ticket_id)
    word = "booking" if company == "atlas" else "order"
    shown = f"{text} ({word} {about_order})" if about_order and word not in text.lower() else text
    tickets.add_message(t["id"], "user", shown)
    for i, said in enumerate(["Reading your message…", "Checking your order…", "Checking the rules…", "Writing the reply…"]):
        on_step(said)
        time.sleep(5 if "slow" in text.lower() else 0.8)
    if "busy" in text.lower():
        reply, status, outcome = "Our assistant is busy, please try again later.", "Open", "busy"
    else:
        reply, status, outcome = TEST_DATA + "This is a fake reply: no model ran and nothing was decided.", "Solved", "approve"
    tickets.add_message(t["id"], "assistant", reply, seconds=3.2)
    tickets.update_ticket(t["id"], status=status)
    return {"ticket_id": t["id"], "status": status, "reply": reply, "outcome": outcome, "reply_source": "fake",
            "steps": 4, "seconds": 3.2}


def write_accounts(folder: Path) -> Path:
    hashed = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=10)).decode()
    users = {u: {"name": name, "email": email, "roles": [role], "user_id": uid, "password": hashed,
                 "company": accounts.demo_company(u, role)}
             for u, name, email, role, uid in accounts.DEMO_ACCOUNTS}
    path = folder / "accounts.yaml"
    path.write_text(yaml.safe_dump({"credentials": {"usernames": users},
                                    "cookie": {"name": "demo", "key": "d" * 32, "expiry_days": 1}}), encoding="utf-8")
    return path


def ticket(company, user_id, text, reply, *, outcome, status, reason, priority, agent, extra_steps=(), order_id=None):
    """One finished ticket written with the store (no pipeline): the steps are DISPLAY data for the Console
    (the trace of a run that never happened). order_id = the order / booking the customer owns and talks about."""
    order_id = order_id or (4505 if company == "shopnova" else 7003)
    t = store.create_ticket(company, user_id)
    mid = store.add_message(t["id"], "user", text)
    add = lambda kind, who, data: store.add_step(t["id"], mid, kind, who, data)   # noqa: E731
    add("intake", "intake", {"trace_step": "intake_ticket", "main_reason": reason, "emotion": {"label": "anger", "score": 0.83},
                             "sentiment": {"label": "negative", "score": 0.91}, "priority_label": priority,
                             "order_id": order_id, "seconds": 0.6})
    add("route", "router", {"trace_step": "route", "agent": agent, "reason": reason, "layer": 2})
    add("llm", "agent_b" if agent == "B" else "agents",
        {"trace_step": "llm_call", "role": "agent_b" if agent == "B" else "agents",
         "provider": "groq" if agent == "B" else "local", "model": "openai/gpt-oss-120b" if agent == "B" else "cv-qwen3.5-4b",
         "seconds": 2.4, "tokens": {"total": 1830 if agent == "B" else 640}})
    add("tool_call", agent, {"trace_step": "tool_call", "agent": agent, "tool": "get_order" if company == "shopnova" else "get_flight_booking",
                             "args": {"order_id": order_id} if company == "shopnova" else {"booking_id": order_id},
                             "result": {"id": order_id, "status": "shipped", "days_late": 8} if company == "shopnova"
                             else {"id": order_id, "flight": "AA 1234", "status": "cancelled"}})
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
                                       "proposal_id": "P-0001", "order_id": order_id})
    add("slm", "pipeline", {"trace_step": "final_reply", "outcome": outcome, "reply_source": "slm", "seconds": 1.9})
    store.add_message(t["id"], "assistant", reply, seconds=5.3)
    store.update_ticket(t["id"], status=status, main_reason=reason, priority=priority, lead_agent=agent)
    return t


def pending_shop_refund(user_id: int = 2, order_id: int = 4515) -> dict:
    """A pending ShopNova REFUND as the channel makes it (same recipe as the API tests): the Coordinator in queue
    mode records the proposal, runs its checks on the seeded order, finds the amount above the finance limit and
    answers layer3_pending; then the ticket and the approvals row. Order 4515 belongs to youssef (user 2):
    378.00 TND paid, promised 2026-10-01, stuck at the depot (R-REF-03)."""
    from callverse.coordinator.coordinator import new_case, review
    from callverse.tools.shopnova_tools import get_order
    order = get_order(order_id)
    assert order and order.get("user_id") == user_id, ("the order must belong to the customer", order)
    amount = float(order["paid"])
    text = f"My order {order_id} is very late and still at the depot, I want a refund please."
    t = store.create_ticket("shopnova", user_id)
    mid = store.add_message(t["id"], "user", text)
    store.add_step(t["id"], mid, "intake", "intake", {"style": {"formality": "formal", "length": "short"},
                                                      "emotion": {"label": "anger"}, "sentiment": {"label": "negative"},
                                                      "main_reason": "refund_request", "order_id": order_id})
    proposal = {"agent": "B", "action": "refund", "params": {"order_id": order_id, "amount": amount},
                "rule_id": "R-REF-03", "facts_used": {"days_late": 8, "delivered": False, "paid": amount, "refunded_total": 0.0},
                "user_confirmed": True, "user_quote": "I want a refund please."}
    decision = review(proposal, new_case(t["id"]))
    assert decision["outcome"] == "layer3_pending", decision
    store.add_message(t["id"], "assistant", "Your request is with our finance team.", seconds=2.1)
    store.update_ticket(t["id"], status="Waiting for finance", main_reason="refund_request", priority="high", lead_agent="B")
    return store.create_approval(t["id"], order_id, decision["facts"]["amount_tnd"], decision["proposal_id"], company="shopnova")


def pending_atlas(user_id: int, booking_id: int, action: str, rule_id: str, reason: str, text: str, quote: str) -> dict:
    """A pending Atlas case (refund or compensation) as the channel makes it: the Atlas Coordinator in queue mode
    confirms the request by code from the client's words, computes the amount from the seeded booking and answers
    layer3_pending; then the ticket and the approvals row (company atlas, booking_type flight, the action)."""
    from callverse.coordinator import atlas_coordinator
    from callverse.coordinator.coordinator import new_case
    from callverse.data.atlas import reads as atlas_reads
    booking = atlas_reads.get_flight_booking(booking_id)
    assert booking and booking.get("user_id") == user_id, ("the booking must belong to the customer", booking)
    t = store.create_ticket("atlas", user_id)
    mid = store.add_message(t["id"], "user", text)
    store.add_step(t["id"], mid, "intake", "intake", {"style": {"formality": "formal", "length": "short"},
                                                      "emotion": {"label": "anger"}, "sentiment": {"label": "negative"},
                                                      "main_reason": reason, "order_id": booking_id})
    proposal = {"agent": "B", "action": action, "params": {"booking_type": "flight", "booking_id": booking_id},
                "rule_id": rule_id, "facts_used": {"read": True}, "user_confirmed": True, "user_quote": quote}
    case = {**new_case(t["id"]), "order_id": booking_id, "booking_type": "flight", "main_reason": reason,
            "user_message": text, "searched_rules": [rule_id]}
    decision = atlas_coordinator.review(proposal, case)
    assert decision["outcome"] == "layer3_pending", decision
    store.add_message(t["id"], "assistant", "Your request is with our finance team.", seconds=2.1)
    store.update_ticket(t["id"], status="Waiting for finance", main_reason=reason, priority="high", lead_agent="B")
    return store.create_approval(t["id"], booking_id, decision["facts"]["amount_tnd"], decision["proposal_id"],
                                 company="atlas", booking_type="flight", action=action)


def main(folder: Path) -> dict:
    """Write the fixture; returns {"shop_refund", "atlas_compensation", "atlas_refund"}: the three approval rows."""
    from callverse.data.atlas.seed import seed as atlas_seed
    from callverse.data.seed import seed as shop_seed
    folder.mkdir(parents=True, exist_ok=True)
    accounts_path = write_accounts(folder)
    for name in ("callverse.db", "shopnova.db", "atlas.db"):
        if (folder / name).exists():
            (folder / name).unlink()
    shop_seed(folder / "shopnova.db")            # the seeded samples, never the real files
    shopnova_db.use_db(folder / "shopnova.db")
    atlas_seed(folder / "atlas.db")
    atlas_db.use_db(folder / "atlas.db")
    store.use_db(folder / "callverse.db")
    # the Coordinators must queue the cases above the finance limit (not decide them with the finance stub)
    os.environ["CALLVERSE_LAYER3_MODE"] = "queue"

    # Finished tickets for the Console (display data; each about something the customer owns).
    ticket("shopnova", 1, "My order 4512 is 6 days late, still at the depot. I want a refund.", "Your refund of 59.90 TND is approved.",
           outcome="approve", status="Solved", reason="refund_request", priority="high", agent="B", order_id=4512,
           extra_steps=[("proposal", "proposal_tools", {"trace_step": "proposal", "action": "refund", "order_id": 4512, "amount": 59.9,
                                                        "rule_id": "R-REF-03", "user_confirmed": True, "facts_used": {"days_late": 6}})])
    ticket("shopnova", 2, "Where is my order 4510? Nobody answers.", "Your parcel is with Aramex and should arrive by 2026-10-10.",
           outcome="approve", status="Solved", reason="tracking", priority="medium", agent="A", order_id=4510)
    ticket("atlas", 1, "My flight 7005 was cancelled, I need to be rebooked tomorrow.", "A colleague will contact you to rebook.",
           outcome="escalate", status="Escalated", reason="rebooking", priority="high", agent="A", order_id=7005)
    ticket("atlas", 4, "My suitcase on flight 7008 arrived damaged, what do I do?", "Please send a photo of the damage.",
           outcome="ask_proof", status="Waiting for user", reason="baggage", priority="low", agent="B", order_id=7008,
           extra_steps=[("brand_new_step", None, {"trace_step": "photo_proof_received", "ok": False, "note": "an outcome the Console has never seen"})])
    t6 = ticket("shopnova", 5, "I want to cancel order 4514.", "Can you confirm you want to cancel order 4514?",
                outcome="send_back", status="Waiting for user", reason="cancel_order", priority="medium", agent="B", order_id=4514)
    mid = store.add_message(t6["id"], "user", "Yes, cancel it.")
    store.add_step(t6["id"], mid, "intake", "intake", {"trace_step": "intake_ticket", "main_reason": "cancel_order", "emotion": "neutral",
                                                       "sentiment": "neutral", "priority_label": "medium", "order_id": 4514, "seconds": 0.4})
    store.add_step(t6["id"], mid, "coordinator", "coordinator", {"trace_step": "coordinator_decision", "outcome": "approve",
                                                                 "reason": "the client confirmed with the cancel word", "proposal_id": "P-0002", "order_id": 4514})
    store.add_message(t6["id"], "assistant", "Order 4514 is cancelled.", seconds=4.1)
    store.update_ticket(t6["id"], status="Solved")

    # The three PENDING cases of the admin queues, made by the real Coordinators (queue mode, no model).
    made = {
        "shop_refund": pending_shop_refund(user_id=2, order_id=4515),
        "atlas_compensation": pending_atlas(5, 7004, "compensation", "AT-FLT-03", "compensation_request",
                                            "My flight 7004 was delayed for hours, I want a compensation please.",
                                            "I want a compensation please."),
        "atlas_refund": pending_atlas(2, 7006, "refund", "AT-FLT-04", "refund_request",
                                      "My flight booking 7006 left hours late, I want a refund please.",
                                      "I want a refund please."),
    }

    print("Demo fixture written in", folder)
    print("Logins: every demo username (supervisor, admin, sara, ...) with the password", PASSWORD)
    print("Set these, then run `python -m webui.api.run`:")
    print(f"  CALLVERSE_WEBUI_ACCOUNTS={accounts_path}")
    print(f"  CALLVERSE_WEBUI_TICKETS_DB={folder / 'callverse.db'}")
    print(f"  CALLVERSE_WEBUI_SHOPNOVA_DB={folder / 'shopnova.db'}")
    print(f"  CALLVERSE_WEBUI_ATLAS_DB={folder / 'atlas.db'}")
    print("  CALLVERSE_LAYER3_MODE=queue   (the approval queues are only filled in queue mode)")
    print("  CALLVERSE_WEBUI_FAKE_CHAT=1   (fake chat and a fake reply writer: no model)")
    print("Pending approvals (test data): ShopNova #%d youssef order 4515 refund %.2f TND; Atlas #%d nizar flight 7004 "
          "compensation %.2f TND; Atlas #%d sonia flight 7006 refund %.2f TND"
          % (made["shop_refund"]["id"], made["shop_refund"]["amount"], made["atlas_compensation"]["id"],
             made["atlas_compensation"]["amount"], made["atlas_refund"]["id"], made["atlas_refund"]["amount"]))
    return made


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m webui.api.dev_fixture <folder>")
    main(Path(sys.argv[1]))
