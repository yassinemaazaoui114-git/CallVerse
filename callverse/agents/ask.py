"""ask_agent: one agent asks another agent a question (a tool, so it goes through the allow-list).

Why? Agent B (refunds) needs delivery facts such as days_late, but get_tracking is NOT on its
allow-list: delivery is Agent A's job. So B asks A. Agent A runs its normal loop with its own tools
and the answer comes back to B together with the delivery facts from A's get_tracking result, so B
cites facts that came from a tool, not from A's wording. Only those facts are returned (not A's
whole transcript): every token sent back to B is paid again at each of B's next model calls.

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
    out = {"agent": agent, "answer": result["answer"], "facts": compact_facts(result["tool_calls"])}
    trace.log("ask_agent", "ask", {"to": agent, "question": question, **out})
    return out


# Only the delivery facts Agent B needs (T07: fewer tokens than A's whole tool results).
DELIVERY_FACTS = ("order_id", "status", "delivered", "days_late", "days_since_delivery",
                  "promised_date", "delivered_date")


def compact_facts(tool_calls: list[dict]) -> dict:
    """The delivery facts from Agent A's get_tracking result (or its error), nothing else."""
    for call in reversed(tool_calls):          # the last tracking read is the freshest
        if call["tool"] == "get_tracking" and isinstance(call["result"], dict):
            if "error" in call["result"]:
                return {"error": call["result"]["error"]}
            return {"source": "get_tracking", **{k: call["result"].get(k) for k in DELIVERY_FACTS}}
    return {"error": "Agent A did not read the tracking data"}


SCHEMA = {
    "type": "function",
    "function": {
        "name": "ask_agent",
        "description": "Ask Agent A about delivery. Returns its answer and the tracking facts.",
        "parameters": {
            "type": "object",
            "properties": {"agent": {"type": "string", "enum": list(ASKABLE)}, "question": {"type": "string"}},
            "required": ["agent", "question"],
        },
    },
}
