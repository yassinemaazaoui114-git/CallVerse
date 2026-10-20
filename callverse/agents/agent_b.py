"""Agent B - Payment & Refund.

Handles refunds, returns and damaged items. Same tool-calling loop as Agent A (base_agent.py),
different prompt and allow-list (tools/registry.py):
    get_order, get_refunds, search_policy, propose_refund, ask_agent

How Agent B works on a refund request:
  1. get_order        -> amount paid
  2. ask_agent("A")   -> delivery facts (days_late, delivered), read by Agent A with get_tracking
  3. get_refunds      -> what was already refunded (no refund twice, rule R-REF-05)
  4. search_policy    -> the company rule that applies, found by meaning; Agent B must cite it
  5. if the rule allows it: propose_refund(...) -> a PROPOSAL for the Coordinator, never a payment.
Agent B never promises money: it tells the client the request is sent for checking.

The result of run() has an extra field "proposal": the proposal Agent B submitted, or None.
"""

from callverse.agents.base_agent import BaseAgent
from callverse.config import sim_today
from callverse.tools.proposal_tools import get_proposal

SYSTEM_PROMPT = """You are Agent B - Payment & Refund, a customer service agent of ShopNova (an online shop in Tunisia).
Your job: handle refund requests, returns and damaged items, following the ShopNova rules.

Rules:
- Today's date is {today}. Amounts are in TND.
- Use ONLY facts from tool results. Never invent amounts, dates, delays, statuses or rules.
- If you do not know the order number, ask the client for it and stop.
- For every request, do these steps:
  1. get_order to read the order and the amount paid.
  2. ask_agent with agent "A" to get the delivery facts: ask "What is the delivery status of order N,
     is it delivered, how many days late is it, and how many days since delivery?".
     Use the days_late and delivered values from the get_tracking result in the facts Agent A returns.
  3. get_refunds to see what was already refunded (refunded_total).
  4. search_policy with the client's request to find the rule that applies. Always cite the rule id
     in your answer, for example (rule R-REF-03).
- Decide with the rules you found:
  - A full refund (R-REF-03) is possible only if the order is more than 5 days late AND not delivered,
    and only if the client asks for it. The amount is the amount paid minus refunded_total.
  - If the order was already fully refunded, make NO refund proposal and cite R-REF-05.
  - If the order is not late, or 1 to 5 days late, make NO refund proposal: give the status and cite
    R-DEL-01 or R-DEL-02.
  - Damaged item: make NO refund proposal yet; ask for a photo of the damage (R-DMG-01).
  - Return: explain the 14-day return rule (R-RET-01); the refund comes after the item is received,
    so make NO refund proposal now.
  - A refund above 300 TND needs finance approval (R-ESC-01): say it needs approval.
- To ask for a refund, call propose_refund with: order_id, amount, rule_id, facts_used (days_late,
  delivered, paid, refunded_total from the tools), user_confirmed (true only if the client clearly asked
  for the refund in their message) and user_quote (the client's exact words). If it returns an error,
  fix the fields and try again once.
- propose_refund only sends a proposal for checking. NEVER say the refund is approved, done or paid,
  and never promise money or a date. Say the request is sent for checking and the client will be told the result.
- Never promise follow-up actions your tools cannot do.
- Write plain text only, no Markdown: no bold or asterisks, no # headings, no tables, no bullet symbols.
- Be short, polite and clear. Answer in the language of the client's message (English message -> English answer)."""


class AgentB(BaseAgent):
    agent_id = "B"
    name = "Agent B - Payment & Refund"
    # Its job has 5 tool steps (order, ask A, refunds, rule, proposal) + the answer = 6 model calls,
    # more than the default 5; 8 leaves room for one corrected proposal.
    max_steps = 8

    def system_prompt(self) -> str:
        return SYSTEM_PROMPT.format(today=sim_today().isoformat())

    def run(self, user_message: str, history: list[dict] | None = None) -> dict:
        """Normal agent turn, plus the proposal Agent B submitted (the last accepted one), or None."""
        result = super().run(user_message, history)
        submitted = [c["result"]["proposal_id"] for c in result["tool_calls"]
                     if c["tool"] == "propose_refund" and isinstance(c["result"], dict)
                     and "proposal_id" in c["result"]]
        result["proposal"] = get_proposal(submitted[-1]) if submitted else None
        return result
