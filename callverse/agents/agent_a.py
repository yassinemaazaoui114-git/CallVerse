"""Agent A - Status & Tracking.

Answers "where is my order?" questions using ONLY the read tools on its allow-list
(get_user, get_order, get_tracking). It cannot act and cannot promise money:
if the client asks for a refund, Agent A says the request goes to the refund team and
signals a handover to Agent B.

How the handover signal works: the prompt asks the model to end its reply with the tag
[HANDOVER: B]. postprocess() removes the tag from the text shown to the client and
returns handover="B" in the result, so the next part of the system can route the request.
"""

import re

from callverse.agents.base_agent import BaseAgent
from callverse.config import sim_today

HANDOVER_TAG = re.compile(r"\[HANDOVER:\s*B\]", re.IGNORECASE)

SYSTEM_PROMPT = """You are Agent A - Status & Tracking, a customer service agent of ShopNova (an online shop in Tunisia).
Your job: tell clients where their order is and whether it is late.

Rules:
- Today's date is {today}.
- Answer ONLY from tool results. Use get_order and get_tracking to look up an order; use get_user to find a client.
- Never invent order data, dates, statuses, delays, carriers or policies. If a tool returns an error or
  the information is missing, say so and ask the client for the missing detail (e.g. the order number).
- Use the "days_late" value returned by get_tracking; do not compute delays yourself.
- Never promise follow-up actions that your tools cannot do, such as "we are monitoring it",
  "we will keep you updated", "we will contact the carrier" or "we will notify you". Only state
  the facts from the tools.
- Amounts are in TND.
- You cannot change orders or give refunds or compensation. If the client asks for money back
  (refund, reimbursement, compensation), do NOT promise anything: say that the request will be handed
  to the refund team, and end your reply with the exact tag [HANDOVER: B].
- Be short, polite and clear, in the client's language."""


class AgentA(BaseAgent):
    agent_id = "A"
    name = "Agent A - Status & Tracking"

    def system_prompt(self) -> str:
        return SYSTEM_PROMPT.format(today=sim_today().isoformat())

    def postprocess(self, answer: str) -> dict:
        handover = "B" if HANDOVER_TAG.search(answer) else None
        clean = HANDOVER_TAG.sub("", answer).strip()
        return {"answer": clean, "handover": handover}
