"""Platform demo: plays scenarios S1, S2, S3 with ShopNova platform functions only (no LLM, no API key).

Why: it proves the platform (data, policies, write functions, Layer 3 stub) works on its own, and it is
the backup demo if the Groq API is down. It IMITATES the agents and the Coordinator in a few plain lines;
the real ones are built in the core tasks.

Usage (from the repo root):
    python -m scripts.demo_platform        (or: python scripts/demo_platform.py)

Each scenario starts from a fresh seed so its numbers are always the same. At the end the database is
re-seeded again, so the real DB is left clean. Every function call is in the trace file printed at the end.
"""

import sys
from pathlib import Path

# Allow "python scripts/demo_platform.py" as well as "python -m scripts.demo_platform".
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from callverse import trace  # noqa: E402
from callverse.data.layer3 import layer3_decide  # noqa: E402
from callverse.data.seed import seed  # noqa: E402
from callverse.data.reports import get_pending_notifications  # noqa: E402
from callverse.data.writes import (create_refund, create_subscription, mark_subscription_sent,  # noqa: E402
                                   record_decision, record_proposal, set_order_status)
from callverse.kb.policies import check_condition, get_policy  # noqa: E402
from callverse.tools.shopnova_tools import get_order, get_refunds, get_tracking  # noqa: E402


def say(text: str) -> None:
    print("  " + text)


def title(text: str) -> None:
    print("\n" + text + "\n" + "-" * len(text))


def facts_for(order_id: int, amount: float | None = None) -> dict:
    """Read the facts the conditions need, from the platform (as the Coordinator will: never from the agent)."""
    order, tracking, refunds = get_order(order_id), get_tracking(order_id), get_refunds(order_id)
    facts = {"paid": order["paid"], "days_late": tracking["days_late"],
             "delivered": tracking["delivered"], "refunded_total": refunds["refunded_total"]}
    if amount is not None:
        facts["amount"] = amount
    return facts


def check(rule_id: str, facts: dict) -> bool:
    """Check one rule's condition on the facts and print the result."""
    rule = get_policy(rule_id)
    ok = check_condition(rule["condition"], facts)
    say(f"{rule_id} '{rule['condition']}' -> {'PASS' if ok else 'FAIL'}")
    return ok


def propose(order_id: int, amount: float, rule_id: str = "R-REF-03") -> str:
    """Imitate Agent B's refund proposal: record it in the audit table and return its id."""
    pid = record_proposal({"agent": "B", "action": "refund", "params": {"order_id": order_id, "amount": amount},
                           "rule_id": rule_id, "facts_used": facts_for(order_id), "user_confirmed": True})
    say(f"record_proposal(B, refund {order_id}, {amount:.2f}, {rule_id}) -> {pid}")
    return pid


def decide(pid: str, decision: str, reason: str) -> None:
    """Imitate the Coordinator's decision: record it in the audit table."""
    row = record_decision(pid, decision, reason)
    say(f"record_decision({pid}, {decision}) -> decision {row['decision']}")


def s1() -> None:
    title("S1 - order 4512 is 6 days late, client asks for a refund -> approved")
    order, tracking, refunds = get_order(4512), get_tracking(4512), get_refunds(4512)
    say(f"get_order(4512)    -> paid {order['paid']:.2f} TND, status {order['status']}")
    say(f"get_tracking(4512) -> {tracking['days_late']} days late, delivered = {tracking['delivered']}")
    say(f"get_refunds(4512)  -> {len(refunds['refunds'])} refunds, refunded_total {refunds['refunded_total']:.2f} TND")
    pid = propose(4512, 59.90)
    facts = facts_for(4512, amount=59.90)
    if check("R-REF-03", facts) and check("R-REF-05", facts):
        l3 = layer3_decide(4512, 59.90, "late delivery refund")
        say(f"layer3_decide(4512, 59.90) -> {l3['decision']} (R-ESC-01: only above 300 TND)")
        decide(pid, "approve", "R-REF-03 and R-REF-05 hold")
        row = create_refund(4512, 59.90, "R-REF-03", pid)
        say(f"create_refund(4512, 59.90, 'R-REF-03', '{pid}') -> refund #{row['id']}, status {row['status']}")
        print(f"  RESULT S1: refund of {row['amount']:.2f} TND APPROVED under R-REF-03.")


def s2() -> None:
    title("S2 - wrong amount proposed (70.00), sent back, corrected (59.90) -> passes")
    say("Proposal 1: refund 70.00 TND on order 4512 (paid 59.90)")
    pid = propose(4512, 70.00)
    if not check("R-REF-05", facts_for(4512, amount=70.00)):
        decide(pid, "send_back", "R-REF-05: 70.00 > paid 59.90 - refunded 0.00")
        say("RESULT: SENT BACK - 70.00 is more than paid minus already refunded (R-REF-05)")
    say("Proposal 2 (corrected): refund 59.90 TND")
    pid = propose(4512, 59.90)
    if check("R-REF-05", facts_for(4512, amount=59.90)):
        print("  RESULT S2: corrected proposal PASSES R-REF-05 (would then be approved as in S1).")


def s3() -> None:
    title("S3 - client subscribes to 'delivered', the order moves, the event is recorded")
    sub = create_subscription(4512, "delivered")
    say(f"create_subscription(4512, 'delivered') -> subscription #{sub['id']}, status {sub['status']}")
    for status in ("out_for_delivery", "delivered"):
        r = set_order_status(4512, status)
        event = f"event #{r['event']['id']} '{r['event']['event']}'" if r["event"] else "no event"
        say(f"set_order_status(4512, '{status}') -> {r['old_status']} -> {r['new_status']}, {event}")
    # What the notifier (later task) does: read the pending notifications, send them, mark them sent.
    pending = get_pending_notifications()
    for n in pending:
        say(f"get_pending_notifications() -> subscription #{n['subscription_id']} '{n['event']}' on {n['event_at']}"
            f" for {n['user']['name']} ({n['user']['email']})")
    print(f"  RESULT S3: {len(pending)} notification ready to send (the notifier will mark it 'sent').")
    for n in pending:
        row = mark_subscription_sent(n["subscription_id"])
        say(f"mark_subscription_sent({n['subscription_id']}) -> status {row['status']}")
    again = mark_subscription_sent(sub["id"])
    say(f"mark_subscription_sent({sub['id']}) again -> {again.get('error', again)}")
    print(f"  RESULT S3: subscription #{sub['id']} marked 'sent'; {len(get_pending_notifications())} notifications pending.")


def extras() -> None:
    title("Extra - double refund, database safety net, Layer 3")
    say("Order 4506 was already refunded 189 TND. Proposal: refund 1 TND more")
    if not check("R-REF-05", facts_for(4506, amount=1)):
        print("  RESULT: 4506 second refund REFUSED by R-REF-05 (already fully refunded).")
    # Even if the Coordinator had a bug (approving it) and tried to write it, the database layer refuses it.
    buggy = propose(4506, 1.00)
    decide(buggy, "approve", "demo: a buggy Coordinator approves it")
    r = create_refund(4506, 1.00, "R-REF-03", buggy)
    say(f"create_refund(4506, 1.00) -> {r.get('error', r)}")
    if "error" in r:
        print("  RESULT: 4506 second refund REFUSED by the database safety net (create_refund).")

    say("")
    say("Order 4515: 2 Smart Watches, 378.00 TND paid, stuck at the depot (Layer 3 story)")
    tracking = get_tracking(4515)
    say(f"get_tracking(4515) -> {tracking['days_late']} days late, delivered = {tracking['delivered']}")
    pid = propose(4515, 378.00)
    facts = facts_for(4515, amount=378.00)
    if check("R-REF-03", facts) and check("R-REF-05", facts) and check("R-ESC-01", facts):
        l3 = layer3_decide(4515, 378.00, "late delivery refund above 300 TND")
        say(f"layer3_decide(4515, 378.00) -> {l3['decision']} by {l3['by']}")
        if l3["decision"] == "approved":
            decide(pid, "approve", "finance approved (Layer 3, R-ESC-01)")
            row = create_refund(4515, 378.00, "R-REF-03", pid)
            say(f"create_refund(4515, 378.00, 'R-REF-03', '{pid}') -> refund #{row['id']}, status {row['status']}")
            print("  RESULT: 4515 refund of 378.00 TND APPROVED BY FINANCE (Layer 3, R-ESC-01).")

    # Stub test only (no DB change): an amount above the stub limit (500 TND) is refused by finance.
    l3 = layer3_decide(4515, 600, "stub test: above 500 TND")
    print(f"  RESULT (stub test): layer3_decide(4515, 600) -> {l3['decision'].upper()} by {l3['by']}")


def main() -> None:
    trace_path = trace.start_run()
    print("CallVerse platform demo (no LLM). Demo date 2026-10-09.")
    for scenario in (s1, s2, s3, extras):
        seed()            # fresh data for each scenario
        scenario()
    seed()                # leave the real database clean
    print(f"\nTrace file: {trace_path}")


if __name__ == "__main__":
    main()
