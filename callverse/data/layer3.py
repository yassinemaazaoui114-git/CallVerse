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
"""

from contextlib import closing

from callverse import trace
from callverse.config import load_config
from callverse.data.db import connect
from callverse.kb.policies import layer3_threshold


def layer3_decide(order_id: int, amount: float, reason: str) -> dict:
    """Ask the finance stub about a refund. Returns
    {order_id, amount, decision, by, rule_id, reason} or {"error": ...}."""
    args = {"order_id": order_id, "amount": amount, "reason": reason}

    if not isinstance(amount, (int, float)) or amount <= 0:
        result = {"error": "amount must be a positive number"}
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
