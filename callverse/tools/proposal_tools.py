"""ACTION tools: they never act. They only write a PROPOSAL for the Coordinator.

Rule of the project: agents never act directly. When Agent B thinks a refund is due, it calls
propose_refund(...). That call does NOT pay anything and does NOT touch the database:
  1. it checks that the fields are complete and of the right type (else the proposal is refused,
     so the agent can fix it);
  2. it gives the proposal an id (P-0001, P-0002, ...);
  3. it keeps the proposal in memory and writes it to the trace (step "proposal");
  4. it answers "submitted to Coordinator".
The Coordinator (rules, no LLM, task T07) will later check each proposal against the policy conditions
and is the only part allowed to write. The platform's `proposals` table comes with task P06; until then
the proposals live in memory and in the trace.

What is checked here is only the SHAPE of the proposal. Whether the rule really applies
(days_late > 5, amount <= paid - refunded_total, ...) is the Coordinator's job, not this tool's.
"""

import math

from callverse import trace
from callverse.kb.policies import get_policy

_proposals: dict[str, dict] = {}   # proposal id -> proposal (in memory until the P06 table exists)
_counter = 0


def reset() -> None:
    """Forget every proposal and restart the counter at P-0001 (used by the tests and the demos)."""
    global _counter
    _proposals.clear()
    _counter = 0


def get_proposal(proposal_id: str) -> dict | None:
    """One proposal by id, or None."""
    return _proposals.get(proposal_id)


def _problems(order_id, amount, rule_id, facts_used, user_confirmed, user_quote) -> list[str]:
    """Everything wrong with the fields (empty list = the proposal is well formed)."""
    problems = []
    # bool is a kind of int in Python, so True/False are refused explicitly.
    if isinstance(order_id, bool) or not isinstance(order_id, int):
        problems.append("order_id must be an integer")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount <= 0:
        problems.append("amount must be a number > 0")
    if not isinstance(rule_id, str) or not rule_id.strip():
        problems.append("rule_id is missing: cite the rule found with search_policy")
    elif get_policy(rule_id) is None:
        problems.append(f"rule_id {rule_id} does not exist")
    if not isinstance(facts_used, dict) or not facts_used:
        problems.append("facts_used must be a non-empty object of the facts read from tools")
    if not isinstance(user_confirmed, bool):
        problems.append("user_confirmed must be true or false")
    if not isinstance(user_quote, str) or not user_quote.strip():
        problems.append("user_quote must quote the client's own words")
    return problems


def propose_refund(order_id=None, amount=None, rule_id=None, facts_used=None,
                   user_confirmed=None, user_quote=None) -> dict:
    """Submit a refund PROPOSAL to the Coordinator. Pays nothing, writes nothing in the database."""
    global _counter
    fields = {"order_id": order_id, "amount": amount, "rule_id": rule_id, "facts_used": facts_used,
              "user_confirmed": user_confirmed, "user_quote": user_quote}

    problems = _problems(**fields)
    if problems:
        trace.log("proposal_refused", "proposal_tools", {"fields": fields, "problems": problems})
        return {"error": "proposal refused: " + "; ".join(problems)}

    _counter += 1
    proposal = {"proposal_id": f"P-{_counter:04d}", "type": "refund", **fields,
                "amount": round(float(amount), 2), "status": "submitted"}
    _proposals[proposal["proposal_id"]] = proposal
    trace.log("proposal", "proposal_tools", proposal)
    return {"proposal_id": proposal["proposal_id"], "status": "submitted to Coordinator"}


SCHEMA = {
    "type": "function",
    "function": {
        "name": "propose_refund",
        "description": ("Submit a refund PROPOSAL to the Coordinator, who checks it and decides. "
                        "It does not pay anything. Returns a proposal id, or an error to fix."),
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "integer", "description": "Order number, e.g. 4512"},
                "amount": {"type": "number", "description": "Refund amount in TND, > 0"},
                "rule_id": {"type": "string", "description": "Id of the rule that allows it, found with search_policy, e.g. R-REF-03"},
                "facts_used": {"type": "object", "description": "The facts read from tools that the rule needs, e.g. {\"days_late\": 6, \"delivered\": false, \"paid\": 59.9, \"refunded_total\": 0}"},
                "user_confirmed": {"type": "boolean", "description": "True only if the client clearly asked for this refund"},
                "user_quote": {"type": "string", "description": "The client's own words asking for it"},
            },
            "required": ["order_id", "amount", "rule_id", "facts_used", "user_confirmed", "user_quote"],
        },
    },
}
