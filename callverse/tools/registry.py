"""Tool registry: the per-agent allow-lists and the ONLY way an agent can run a tool.

Rule: a tool call outside the agent's allow-list is refused and logged.
Agents never call tool functions directly; they always go through run_tool(), which checks
the list first. This is a hard rule in code, not a request in a prompt.
"""

from callverse import trace
from callverse.tools import shopnova_tools

# All tools that exist in the prototype (name -> function / schema).
TOOL_FUNCTIONS = dict(shopnova_tools.FUNCTIONS)
TOOL_SCHEMAS = dict(shopnova_tools.SCHEMAS)

# Allow-lists: which tools each agent may use.
AGENT_A = ["get_user", "get_order", "get_tracking"]  # Status & Tracking: read-only tools

ALLOW_LISTS = {
    "A": AGENT_A,
}


def schemas_for(agent: str) -> list[dict]:
    """Tool schemas sent to the LLM for this agent: the model only SEES the tools it is allowed to use."""
    return [TOOL_SCHEMAS[name] for name in ALLOW_LISTS.get(agent, [])]


def run_tool(agent: str, name: str, args: dict) -> dict:
    """Run tool `name` for `agent` if it is on the agent's allow-list; otherwise refuse.

    The result (or the refusal) is logged to the trace and returned as a dict,
    so it can be sent back to the model.
    """
    allowed = ALLOW_LISTS.get(agent, [])
    if name not in allowed:
        result = {"error": f"tool '{name}' is not allowed for agent {agent}"}
        trace.log("tool_refused", "registry", {"agent": agent, "tool": name, "args": args,
                                               "allowed": allowed})
        return result

    try:
        result = TOOL_FUNCTIONS[name](**args)
    except Exception as e:  # bad arguments from the model, etc.: report it instead of crashing
        result = {"error": f"{type(e).__name__}: {e}"}

    trace.log("tool_call", "registry", {"agent": agent, "tool": name, "args": args, "result": result})
    return result
