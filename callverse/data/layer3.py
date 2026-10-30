"""Layer 3 stub: ShopNova's finance team, played by a simple rule (rule R-ESC-01).

In the real company, a refund above 300 TND must be approved by a human in finance. For the
prototype we imitate that person with a fixed rule:
- amount <= 300 TND               -> "not_required" (no finance approval needed)
- 300 < amount <= stub maximum    -> "approved" by finance
- amount > stub maximum           -> "refused" by finance
The 300 comes from R-ESC-01's condition in the policy file; the stub maximum (500 TND) comes from
config.yaml (layer3.stub_max_approve_tnd). Nothing is hard-coded twice.

This function only DECIDES: it writes nothing to the database. The Coordinator (later task) calls it
and then, if approved, writes the refund with create_refund(). It is in no agent allow-list.

T18: layer3_mode() says who plays finance. "stub" (config default) = the rule above. "queue" (env var
CALLVERSE_LAYER3_MODE=queue) = the ShopNova admin decides later on the Refund approvals page
(callverse/channels/approvals.py); the Coordinator then returns "layer3_pending" and does not call the stub.

T21: atlas_layer3_decide = the same stub for Atlas Travel (tests only: the real path is the queue).
"""

import os
from contextlib import closing

from callverse import companies, trace
from callverse.config import load_config
from callverse.data.db import connect
from callverse.data.writes import is_valid_amount
from callverse.kb.policies import layer3_threshold

MODES = ("stub", "queue")
MODE_ENV = "CALLVERSE_LAYER3_MODE"


def layer3_mode() -> str:
    """"stub" or "queue": the env var CALLVERSE_LAYER3_MODE if set, else config.yaml layer3.mode (default stub)."""
    mode = os.environ.get(MODE_ENV) or load_config()["layer3"].get("mode", "stub")
    if mode not in MODES:
        raise ValueError(f"layer3 mode '{mode}' is not allowed (allowed: {', '.join(MODES)})")
    return mode


def layer3_decide(order_id: int, amount: float, reason: str) -> dict:
    """Ask the finance stub about a refund. Returns
    {order_id, amount, decision, by, rule_id, reason} or {"error": ...}."""
    args = {"order_id": order_id, "amount": amount, "reason": reason}

    if not is_valid_amount(amount):
        result = {"error": "amount must be a finite number above 0"}
    else:
        with closing(connect()) as con:
            exists = con.execute("SELECT 1 FROM orders WHERE id = ?", (int(order_id),)).fetchone()
        if exists is None:
            result = {"error": f"order {order_id} not found"}
        else:
            threshold = layer3_threshold()                                    # 300, from R-ESC-01
            max_approve = float(load_config()["layer3"]["stub_max_approve_tnd"])  # 500, from config.yaml
            if amount <= threshold:
                decision, by = "not_required", None   # finance is not involved
            elif amount <= max_approve:
                decision, by = "approved", "finance"
            else:
                decision, by = "refused", "finance"
            result = {"order_id": int(order_id), "amount": amount, "decision": decision,
                      "by": by, "rule_id": "R-ESC-01", "reason": reason}

    trace.log("layer3_decision", "layer3", {"args": args, "result": result})
    return result


def atlas_layer3_decide(booking_type: str, booking_id: int, action: str, amount: float, reason: str) -> dict:
    """Atlas's finance stub. The Coordinator only comes here for a case above AT-ESC-01's limit:
    a refund up to the stub maximum is approved, above it refused; a compensation is always refused.
    Only DECIDES: it writes nothing."""
    args = {"booking_type": booking_type, "booking_id": booking_id, "action": action, "amount": amount, "reason": reason}
    if not is_valid_amount(amount):
        result = {"error": "amount must be a finite number above 0"}
    else:
        max_approve = float(companies.get("atlas")["stub_max_approve_tnd"])
        decision = "approved" if action == "refund" and amount <= max_approve else "refused"
        result = {"booking_type": booking_type, "booking_id": int(booking_id), "amount": amount, "decision": decision,
                  "by": "finance", "rule_id": "AT-ESC-01", "reason": reason}
    trace.log("layer3_decision", "layer3", {"args": args, "result": result})
    return result
