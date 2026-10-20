"""ask_agent: one agent asks another agent a question (a tool, so it goes through the allow-list).

Why? Agent B (refunds) needs delivery facts such as days_late, but get_tracking is NOT on its
allow-list: delivery is Agent A's job. So B asks A. Agent A runs its normal loop with its own tools
and the answer comes back to B together with the facts A read (each tool call + its result), so B
cites facts that came from tools, not from A's wording.

Only Agent A can be asked for now. Agent A itself has no ask_agent tool, so agents cannot ask
each other in a loop.
"""

from callverse import trace

ASKABLE = ("A",)


def ask_agent(agent: str, question: str, chat_fn=None) -> dict:
    """Run `agent` on `question`; return {agent, answer, facts}. chat_fn = fake LLM in tests (given by the registry)."""
    if agent not in ASKABLE:
        return {"error": f"agent {agent} cannot be asked; ask one of {list(ASKABLE)}"}
    if not isinstance(question, str) or not question.strip():
        return {"error": "give a non-empty question"}

    from callverse.agents.agent_a import AgentA   # imported here: agent_a -> registry -> this file
    result = AgentA(chat_fn=chat_fn).run(question)
    facts = [{"tool": c["tool"], "args": c["args"], "result": c["result"]} for c in result["tool_calls"]]
    out = {"agent": agent, "answer": result["answer"], "facts": facts}
    trace.log("ask_agent", "ask", {"to": agent, "question": question, "answer": out["answer"],
                                   "facts_tools": [f["tool"] for f in facts]})
    return out


SCHEMA = {
    "type": "function",
    "function": {
        "name": "ask_agent",
        "description": ("Ask another ShopNova agent a question. Agent A (Status & Tracking) knows delivery "
                        "status, promised and delivered dates and days_late. Returns its answer and the tool facts it used."),
        "parameters": {
            "type": "object",
            "properties": {
                "agent": {"type": "string", "enum": list(ASKABLE), "description": "Which agent to ask: A"},
                "question": {"type": "string", "description": "The question, with the order number"},
            },
            "required": ["agent", "question"],
        },
    },
}
