"""Agent B - Payment & Refund.

Handles refunds, returns and damaged items. Same tool-calling loop as Agent A (base_agent.py),
different prompt and allow-list (tools/registry.py):
    get_order, get_refunds, search_policy, propose_refund, ask_agent

How Agent B works on a refund request:
  1. in ONE model step: get_order (amount paid), get_refunds (already refunded, rule R-REF-05) and
     ask_agent("A") (delivery facts days_late / delivered, read by Agent A with get_tracking).
     Asking for the three tools together saves two model calls (= fewer tokens, see T07);
  2. search_policy -> the company rule that applies, found by meaning; Agent B must cite it;
  3. if the rule allows it: propose_refund(...) -> a PROPOSAL for the Coordinator, never a payment.
Agent B never promises money: it tells the client the request is sent for checking.

The result of run() has an extra field "proposal": the last accepted proposal in the platform's
shape ({agent, action, params, rule_id, facts_used, user_confirmed, user_quote}), or None.
"""

from callverse.agents.base_agent import BaseAgent
from callverse.config import sim_today
from callverse.tools.proposal_tools import refund_proposal

# Kept short on purpose: the prompt is re-sent with every model call of a turn (tokens, T07).
SYSTEM_PROMPT = """You are Agent B - Payment & Refund of ShopNova (Tunisia). Today is {today}. Amounts in TND.
Use only facts from tools, never invent. No order number: ask for it and stop.
1. Call get_order, get_refunds and ask_agent (agent "A": "Delivery status and days_late of order N?"), together if you can.
2. Call search_policy with the request. Cite the rule id in your answer, e.g. (rule R-REF-03).
3. Rules: full refund (R-REF-03) only if days_late > 5, not delivered and the client asks; amount = paid - refunded_total.
Already fully refunded: no proposal (R-REF-05). Not late or 1-5 days late: no proposal (R-DEL-01, R-DEL-02).
Damaged: no proposal, ask for a photo (R-DMG-01). Return: explain R-RET-01, no proposal. Above 300 TND: needs finance approval (R-ESC-01).
4. When a refund rule applies, you MUST call propose_refund BEFORE your final answer; never write that you
will send a proposal without calling it. Fields: facts_used (days_late, delivered, paid, refunded_total),
user_confirmed (true only if the client asked), user_quote (the client's exact words).
Error or sent back: fix it and propose again.
Never say a refund is approved or paid, never promise money or dates: say it is sent for checking.
Write plain text only, no Markdown: no bold or asterisks, no headings, no lists.
Be short and polite. Answer in the language of the client's message (English message -> English answer)."""


class AgentB(BaseAgent):
    agent_id = "B"
    name = "Agent B - Payment & Refund"
    # Its job: 1 step with 3 tools, search, proposal, answer = 4 model calls; 8 leaves room for corrections.
    max_steps = 8

    def system_prompt(self) -> str:
        return SYSTEM_PROMPT.format(today=sim_today().isoformat())

    def run(self, user_message: str, history: list[dict] | None = None) -> dict:
        """Normal agent turn, plus the last proposal the tool accepted (platform shape), or None."""
        result = super().run(user_message, history)
        accepted = [c["args"] for c in result["tool_calls"]
                    if c["tool"] == "propose_refund" and isinstance(c["result"], dict)
                    and "error" not in c["result"]]
        result["proposal"] = refund_proposal(self.agent_id, accepted[-1]) if accepted else None
        return result
