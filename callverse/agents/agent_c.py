"""Agent C - Urgent & Special Help (P20, official spec).

The ONLY agent that changes a client's situation. At ShopNova it can offer three things:
    replacement  a free new unit of the order's item, from stock (rule R-RPL-01), e.g. "the gift is needed tomorrow"
    hold         keep units of a product for the client for 1-3 days (rule R-HLD-01)
    assistance   pass a hard or disputed case to a human colleague (rule R-AST-01)
It combines A, B and D through the spec's links: it ASKS A for the delivery facts and "can it arrive by the client's
deadline?" (get_facts_from_a), ASKS D whether the item is available (check_availability_with_d), and hands a money
request to B as an urgent refund ([HANDOVER: B]). It reads the order itself (get_order: the items).

Like every agent it never acts: its three tools only build a PROPOSAL. The Coordinator (rules, no LLM) re-reads the
facts, checks the rule, and writes only after the client said yes (user_confirmed). Until then the client is
asked to confirm, and NOTHING changes.

How C is reached (pipeline.py): Agent A ends its reply with [HANDOVER: C] for an urgent need, a replacement, a hold
or special help; and as Layer 2 (switch pipeline.layer2_agent_c) when A or B ends in "escalate".
Same tool-calling loop as A and B (base_agent.py); allow-list in tools/registry.py.
"""

import re

from callverse.agents.base_agent import BaseAgent
from callverse.config import sim_today
from callverse.tools import atlas_c_tools
from callverse.tools.proposal_tools import C_ACTIONS, c_proposal

# Link (2) "C asks B: urgent refund": C never pays, so a money request goes to Agent B, marked urgent (pipeline.py).
HANDOVER_TAG = re.compile(r"\[HANDOVER:\s*B\]", re.IGNORECASE)

# Short on purpose (T07): the prompt is re-sent with every model call of a turn.
SYSTEM_PROMPT = """You are Agent C - Urgent & Special Help of ShopNova (online shop, Tunisia). Today is {today}.
You are the only agent that can change a client's situation, and nothing changes until the client says yes.
Use only facts from tools, never invent. No order number: ask for it and stop.
1. Call get_order and get_facts_from_a together (deadline = the date the client needs it, YYYY-MM-DD, if they say one;
   "tomorrow" = the day after today). Then call check_availability_with_d with the order_id.
2. If the client wants money back, make no offer: say it is passed on as urgent and end with the exact tag
   [HANDOVER: B]. Otherwise choose ONE offer:
- replacement (rule R-RPL-01): the order is late (days_late > 0) or arrived damaged with a photo received,
  the product is in stock, and the order is not refunded or cancelled. Call propose_replacement (order_id only:
  the item is the order's; never invent a product_id).
- hold (rule R-HLD-01): the client asks to keep an item for 1 to 3 days and it is in stock. Call propose_hold.
- colleague (rule R-AST-01): the client disagrees with a decision, or no offer fits. Call propose_assistance
  with the order_id and the reason.
3. You MUST call the proposal tool BEFORE your final answer; writing the offer in your answer (or as JSON) does
nothing, only the tool call counts. user_confirmed = true only if the client's message
already says yes to this offer (e.g. "yes, send me a replacement"), else false. user_quote = the client's exact words.
4. Never say the offer is done, approved or sent, never promise dates: say it is being checked.
Write plain text only, no Markdown. Be short and polite. Answer in the language of the client's message."""


ATLAS_PROMPT = """You are Agent C - Urgent & Special Help of Atlas Travel (hotel stays and flights, Tunisia). Today is {today}.
You are the only agent that can change a client's booking, and nothing changes until the client says yes.
Use only facts from tools, never invent. No booking number: ask for it and stop.
1. Call get_flight_booking.
2. Flight cancelled and the client wants another flight (rule AT-FLT-01): call find_alternative_flights and offer the
first flight with propose_rebooking. No flight found: make no offer and say a colleague will contact the client.
Special assistance such as a wheelchair (rule AT-AST-01, at least 48 hours before departure): call propose_assistance.
3. You MUST call the proposal tool BEFORE your final answer. user_confirmed = true only if the client's message already
says yes to this exact offer, else false. user_quote = the client's exact words.
4. Never say it is done or approved, never promise dates: say it is being checked.
Write plain text only, no Markdown. Be short and polite. Answer in the language of the client's message."""

PROMPTS = {"shopnova": SYSTEM_PROMPT, "atlas": ATLAS_PROMPT}


class AgentC(BaseAgent):
    agent_id = "C"
    name = "Agent C - Urgent & Special Help"
    # Its own model list in config.yaml (models.agent_c), like Agent B: switchable alone (CALLVERSE_AGENT_C_SET=local).
    role_key = "agent_c"
    # Its job: reads (1-2 steps), stock, proposal, answer = about 4 model calls; 8 leaves room for corrections.
    max_steps = 8

    def system_prompt(self) -> str:
        return PROMPTS[self.company].format(today=sim_today().isoformat())

    def postprocess(self, answer: str) -> dict:
        handover = "B" if HANDOVER_TAG.search(answer) else None
        return {"answer": HANDOVER_TAG.sub("", answer).strip(), "handover": handover}

    def run(self, user_message: str, history: list[dict] | None = None) -> dict:
        """Normal agent turn, plus the last proposal a C proposal tool accepted (platform shape), or None."""
        result = super().run(user_message, history)
        tools, build = ((atlas_c_tools.ACTIONS, atlas_c_tools.proposal) if self.company == "atlas"
                        else (C_ACTIONS, c_proposal))
        accepted = [c for c in result["tool_calls"] if c["tool"] in tools
                    and isinstance(c["result"], dict) and "error" not in c["result"]]
        result["proposal"] = build(self.agent_id, accepted[-1]["tool"], accepted[-1]["args"]) if accepted else None
        # T29 (F6): at Atlas, no later flight on the route = no rebooking offer. Marked here by code; the pipeline
        # then hands the case to a colleague with one fixed sentence (pipeline.run_c).
        if self.company == "atlas" and atlas_c_tools.no_later_flight(result["tool_calls"]):
            result["no_later_flight"] = True
            if result["proposal"] and result["proposal"]["action"] == "rebook":
                result["proposal"] = None
        return result
