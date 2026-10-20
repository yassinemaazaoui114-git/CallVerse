"""Platform demo over HTTP: the same S1, S2, S3 and extras as demo_platform.py, but every platform call
goes through the local server's endpoints (no LLM, no API key, no second terminal).

The server app is started inside this process with FastAPI's TestClient, so the requests are real HTTP
requests handled by callverse/server/app.py, without opening a network port.
The Coordinator writes need a token: this script sets a random one for its own process only
(it is never written to .env). The RESULT lines are the same as demo_platform.py.

Usage (from the repo root):
    python scripts/demo_platform_http.py        (or: python -m scripts.demo_platform_http)
"""

import os
import secrets
import sys
from pathlib import Path

# Allow "python scripts/demo_platform_http.py" as well as "python -m scripts.demo_platform_http".
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from callverse import trace  # noqa: E402
from callverse.kb.policies import check_condition  # noqa: E402
from callverse.server.app import TOKEN_ENV, app  # noqa: E402

os.environ[TOKEN_ENV] = secrets.token_hex(16)        # temporary token for this demo process only
HEADERS = {"X-Coordinator-Token": os.environ[TOKEN_ENV]}
client = TestClient(app)


def get(path: str):
    return client.get(path).json()


def post(path: str, body: dict | None = None):
    """POST with the Coordinator token; returns the JSON body (an {"error": ...} dict when refused)."""
    return client.post(path, json=body, headers=HEADERS).json()


def say(text: str) -> None:
    print("  " + text)


def title(text: str) -> None:
    print("\n" + text + "\n" + "-" * len(text))


def facts_for(order_id: int, amount: float | None = None) -> dict:
    """Facts for the conditions, read over HTTP (as the Coordinator will: never from the agent)."""
    order, tracking, refunds = get(f"/orders/{order_id}"), get(f"/orders/{order_id}/tracking"), \
        get(f"/orders/{order_id}/refunds")
    facts = {"paid": order["paid"], "days_late": tracking["days_late"],
             "delivered": tracking["delivered"], "refunded_total": refunds["refunded_total"]}
    if amount is not None:
        facts["amount"] = amount
    return facts


def check(rule_id: str, facts: dict) -> bool:
    """Read the rule over HTTP, check its condition, print the result."""
    rule = get(f"/policies/{rule_id}")
    ok = check_condition(rule["condition"], facts)
    say(f"{rule_id} '{rule['condition']}' -> {'PASS' if ok else 'FAIL'}")
    return ok


def propose(order_id: int, amount: float, rule_id: str = "R-REF-03") -> str:
    """Imitate Agent B's refund proposal: POST it to the audit table and return its id."""
    pid = post("/coordinator/proposals", {"agent": "B", "action": "refund",
                                          "params": {"order_id": order_id, "amount": amount}, "rule_id": rule_id,
                                          "facts_used": facts_for(order_id), "user_confirmed": True})["id"]
    say(f"POST /coordinator/proposals (B, refund {order_id}, {amount:.2f}, {rule_id}) -> {pid}")
    return pid


def decide(pid: str, decision: str, reason: str) -> None:
    """Imitate the Coordinator's decision: POST it to the audit table."""
    row = post(f"/coordinator/proposals/{pid}/decision", {"decision": decision, "reason": reason})
    say(f"POST /coordinator/proposals/{pid}/decision ({decision}) -> decision {row['decision']}")


def s1() -> None:
    title("S1 - order 4512 is 6 days late, client asks for a refund -> approved")
    order, tracking, refunds = get("/orders/4512"), get("/orders/4512/tracking"), get("/orders/4512/refunds")
    say(f"GET /orders/4512          -> paid {order['paid']:.2f} TND, status {order['status']}")
    say(f"GET /orders/4512/tracking -> {tracking['days_late']} days late, delivered = {tracking['delivered']}")
    say(f"GET /orders/4512/refunds  -> {len(refunds['refunds'])} refunds, "
        f"refunded_total {refunds['refunded_total']:.2f} TND")
    pid = propose(4512, 59.90)
    facts = facts_for(4512, amount=59.90)
    if check("R-REF-03", facts) and check("R-REF-05", facts):
        l3 = post("/layer3/decide", {"order_id": 4512, "amount": 59.90, "reason": "late delivery refund"})
        say(f"POST /layer3/decide (4512, 59.90) -> {l3['decision']} (R-ESC-01: only above 300 TND)")
        decide(pid, "approve", "R-REF-03 and R-REF-05 hold")
        row = post("/coordinator/refunds", {"order_id": 4512, "amount": 59.90, "rule_id": "R-REF-03",
                                            "proposal_id": pid})
        say(f"POST /coordinator/refunds (4512, 59.90, R-REF-03) -> refund #{row['id']}, status {row['status']}")
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
    # Imitate Agent A's proposal and the Coordinator's approval, then the write (must match the proposal).
    pid = post("/coordinator/proposals", {"agent": "A", "action": "subscribe",
                                          "params": {"order_id": 4512, "event": "delivered"}, "rule_id": "R-NOT-01",
                                          "facts_used": {"status": "stuck_at_depot"}, "user_confirmed": True})["id"]
    say(f"POST /coordinator/proposals (A, subscribe 4512, delivered, R-NOT-01) -> {pid}")
    decide(pid, "approve", "R-NOT-01: 'delivered' is a notification event")
    sub = post("/coordinator/subscriptions", {"order_id": 4512, "event": "delivered", "proposal_id": pid})
    say(f"POST /coordinator/subscriptions (4512, delivered, {pid}) -> subscription #{sub['id']}, status {sub['status']}")
    for status in ("out_for_delivery", "delivered"):
        r = post("/coordinator/orders/4512/status", {"new_status": status})
        event = f"event #{r['event']['id']} '{r['event']['event']}'" if r["event"] else "no event"
        say(f"POST /coordinator/orders/4512/status ({status}) -> {r['old_status']} -> {r['new_status']}, {event}")
    # What the notifier (later task) does: read the pending notifications, send them, mark them sent.
    pending = get("/notifications/pending")
    for n in pending:
        say(f"GET /notifications/pending -> subscription #{n['subscription_id']} '{n['event']}' on {n['event_at']}"
            f" for {n['user']['name']} ({n['user']['email']})")
    print(f"  RESULT S3: {len(pending)} notification ready to send (the notifier will mark it 'sent').")
    for n in pending:
        row = post(f"/coordinator/subscriptions/{n['subscription_id']}/sent")
        say(f"POST /coordinator/subscriptions/{n['subscription_id']}/sent -> status {row['status']}")
    again = client.post(f"/coordinator/subscriptions/{sub['id']}/sent", headers=HEADERS)
    say(f"POST /coordinator/subscriptions/{sub['id']}/sent again -> HTTP {again.status_code}: {again.json()['error']}")
    print(f"  RESULT S3: subscription #{sub['id']} marked 'sent'; {len(get('/notifications/pending'))} notifications pending.")


def extras() -> None:
    title("Extra - double refund, database safety net, Layer 3")
    say("Order 4506 was already refunded 189 TND. Proposal: refund 1 TND more")
    if not check("R-REF-05", facts_for(4506, amount=1)):
        print("  RESULT: 4506 second refund REFUSED by R-REF-05 (already fully refunded).")
    # Even if the Coordinator had a bug (approving it) and tried to write it, the platform refuses it (HTTP 400).
    buggy = propose(4506, 1.00)
    decide(buggy, "approve", "demo: a buggy Coordinator approves it")
    resp = client.post("/coordinator/refunds", json={"order_id": 4506, "amount": 1.00, "rule_id": "R-REF-03",
                                                     "proposal_id": buggy}, headers=HEADERS)
    r = resp.json()
    say(f"POST /coordinator/refunds (4506, 1.00) -> HTTP {resp.status_code}: {r.get('error', r)}")
    if "error" in r:
        print("  RESULT: 4506 second refund REFUSED by the database safety net (create_refund).")

    say("")
    say("Order 4515: 2 Smart Watches, 378.00 TND paid, stuck at the depot (Layer 3 story)")
    tracking = get("/orders/4515/tracking")
    say(f"GET /orders/4515/tracking -> {tracking['days_late']} days late, delivered = {tracking['delivered']}")
    pid = propose(4515, 378.00)
    facts = facts_for(4515, amount=378.00)
    if check("R-REF-03", facts) and check("R-REF-05", facts) and check("R-ESC-01", facts):
        l3 = post("/layer3/decide", {"order_id": 4515, "amount": 378.00,
                                     "reason": "late delivery refund above 300 TND"})
        say(f"POST /layer3/decide (4515, 378.00) -> {l3['decision']} by {l3['by']}")
        if l3["decision"] == "approved":
            decide(pid, "approve", "finance approved (Layer 3, R-ESC-01)")
            row = post("/coordinator/refunds", {"order_id": 4515, "amount": 378.00, "rule_id": "R-REF-03",
                                                "proposal_id": pid})
            say(f"POST /coordinator/refunds (4515, 378.00, R-REF-03) -> refund #{row['id']}, status {row['status']}")
            print("  RESULT: 4515 refund of 378.00 TND APPROVED BY FINANCE (Layer 3, R-ESC-01).")

    # Stub test only (no DB change): an amount above the stub limit (500 TND) is refused by finance.
    l3 = post("/layer3/decide", {"order_id": 4515, "amount": 600, "reason": "stub test: above 500 TND"})
    print(f"  RESULT (stub test): layer3_decide(4515, 600) -> {l3['decision'].upper()} by {l3['by']}")


def main() -> None:
    trace_path = trace.start_run()
    print("CallVerse platform demo over HTTP (no LLM). Demo date 2026-10-09.")
    for scenario in (s1, s2, s3, extras):
        post("/admin/reset")       # fresh data for each scenario
        scenario()
    post("/admin/reset")           # leave the real database clean
    print(f"\nTrace file: {trace_path}")


if __name__ == "__main__":
    main()
