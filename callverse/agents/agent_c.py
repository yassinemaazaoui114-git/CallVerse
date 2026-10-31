"""Agent C - Urgent & Special Help (P20, official spec).

The ONLY agent that changes a client's situation. At ShopNova it can offer three things:
    replacement  a free new unit of the order's item, from stock (rule R-RPL-01), e.g. "the gift is needed tomorrow"
    hold         keep units of a product for the client for 1-3 days (rule R-HLD-01)
    assistance   pass a hard or disputed case to a human colleague (rule R-AST-01)
It combines what the other agents read: delivery facts (like A: get_tracking), order and money facts (like B:
get_order) and stock (like D: get_stock).

Like every agent it never acts: its three tools only build a PROPOSAL. The Coordinator (rules, no LLM) re-reads the
facts, checks the rule, and writes only after the client said yes (user_confirmed). Until then the client is
asked to confirm, and NOTHING changes.

How C is reached (pipeline.py): Agent A ends its reply with [HANDOVER: C] for an urgent need, a replacement, a hold
or special help; and as Layer 2 (switch pipeline.layer2_agent_c) when A or B ends in "escalate".
Same tool-calling loop as A and B (base_agent.py); allow-list in tools/registry.py.
"""

from callverse.agents.base_agent import BaseAgent
from callverse.config import sim_today
from callverse.tools.proposal_tools import C_ACTIONS, c_proposal

# Short on purpose (T07): the prompt is re-sent with every model call of a turn.
SYSTEM_PROMPT = """You are Agent C - Urgent & Special Help of ShopNova (online shop, Tunisia). Today is {today}.
You are the only agent that can change a client's situation, and nothing changes until the client says yes.
Use only facts from tools, never invent. No order number: ask for it and stop.
1. Call get_order and get_tracking, together. Then call get_stock with the product_id of the order's item.
2. Choose ONE offer:
- replacement (rule R-RPL-01): the order is late (days_late > 0) or arrived damaged with a photo received,
  the product is in stock, and the order is not refunded or cancelled. Call propose_replacement.
- hold (rule R-HLD-01): the client asks to keep an item for 1 to 3 days and it is in stock. Call propose_hold.
- colleague (rule R-AST-01): the client disagrees with a decision, or no offer fits. Call propose_assistance
  with the reason.
3. You MUST call the proposal tool BEFORE your final answer; writing the offer in your answer (or as JSON) does
nothing, only the tool call counts. user_confirmed = true only if the client's message
already says yes to this offer (e.g. "yes, send me a replacement"), else false. user_quote = the client's exact words.
4. Never say the offer is done, approved or sent, never promise dates: say it is being checked.
Write plain text only, no Markdown. Be short and polite. Answer in the language of the client's message."""


class AgentC(BaseAgent):
    agent_id = "C"
    name = "Agent C - Urgent & Special Help"
    # Its own model list in config.yaml (models.agent_c), like Agent B: switchable alone (CALLVERSE_AGENT_C_SET=local).
    role_key = "agent_c"
    # Its job: reads (1-2 steps), stock, proposal, answer = about 4 model calls; 8 leaves room for corrections.
    max_steps = 8

    def system_prompt(self) -> str:
        return SYSTEM_PROMPT.format(today=sim_today().isoformat())

    def run(self, user_message: str, history: list[dict] | None = None) -> dict:
        """Normal agent turn, plus the last proposal a C proposal tool accepted (platform shape), or None."""
        result = super().run(user_message, history)
        accepted = [c for c in result["tool_calls"] if c["tool"] in C_ACTIONS
                    and isinstance(c["result"], dict) and "error" not in c["result"]]
        result["proposal"] = c_proposal(self.agent_id, accepted[-1]["tool"], accepted[-1]["args"]) if accepted else None
        return result
