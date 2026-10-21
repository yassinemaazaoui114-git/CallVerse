"""Agent A - Status & Tracking.

Answers "where is my order?" questions using ONLY the tools on its allow-list
(get_user, get_order, get_tracking, get_company_profile, search_policy). It cannot act and cannot
promise money: if the client asks for a refund, Agent A says the request is passed on for checking
and signals a handover to Agent B. Agent B can also ask Agent A for delivery facts (ask_agent).
T09: when the client asks to be told about a delivery event, Agent A calls propose_subscription: only a
proposal, which the Coordinator checks (R-NOT-01) before the platform records it.

Answers are plain text, no Markdown: the SLM and the voice channel need clean text.

How the handover signal works: the prompt asks the model to end its reply with the tag
[HANDOVER: B]. postprocess() removes the tag from the text shown to the client and
returns handover="B" in the result, so the next part of the system can route the request.
"""

import re

from callverse.agents.base_agent import BaseAgent
from callverse.config import sim_today
from callverse.tools.proposal_tools import subscription_proposal

HANDOVER_TAG = re.compile(r"\[HANDOVER:\s*B\]", re.IGNORECASE)

# Kept short on purpose (T07): the prompt is re-sent with every model call, also when Agent B asks Agent A.
SYSTEM_PROMPT = """You are Agent A - Status & Tracking of ShopNova (online shop, Tunisia). Today is {today}. Amounts in TND.
Your job: tell clients where their order is and whether it is late.
- Answer ONLY from tool results: get_order and get_tracking for an order, get_user for a client,
  get_company_profile for general questions (carriers, delivery promise, cities), search_policy for rules.
- Never invent order data, dates, delays, carriers or rules. Missing information or a tool error: say so
  and ask for the missing detail (e.g. the order number).
- Use the days_late value of get_tracking; do not compute delays yourself.
- Never promise actions your tools cannot do ("we will keep you updated", "we will contact the carrier").
- You cannot give refunds or compensation. If the client asks for money back, promise nothing: say the
  request is passed on for checking and end your reply with the exact tag [HANDOVER: B].
- If the client asks to be told when the order is shipped, out for delivery or arrives (or accepts that
  offer), you MUST call propose_subscription (event "delivered" for "when it arrives"; user_quote = the
  client's exact words) before answering.
  Never promise the message in your own text: the request is checked first.
- Write plain text only, no Markdown: no bold or asterisks, no headings, no lists.
- Be short and polite. Answer in the language of the client's message (English message -> English answer)."""


class AgentA(BaseAgent):
    agent_id = "A"
    name = "Agent A - Status & Tracking"

    def system_prompt(self) -> str:
        return SYSTEM_PROMPT.format(today=sim_today().isoformat())

    def run(self, user_message: str, history: list[dict] | None = None) -> dict:
        """Normal agent turn, plus the last subscription proposal the tool accepted (T09), or None."""
        result = super().run(user_message, history)
        accepted = [c["args"] for c in result["tool_calls"]
                    if c["tool"] == "propose_subscription" and isinstance(c["result"], dict)
                    and "error" not in c["result"]]
        result["proposal"] = subscription_proposal(self.agent_id, accepted[-1]) if accepted else None
        return result

    def postprocess(self, answer: str) -> dict:
        handover = "B" if HANDOVER_TAG.search(answer) else None
        clean = HANDOVER_TAG.sub("", answer).strip()
        return {"answer": clean, "handover": handover}
