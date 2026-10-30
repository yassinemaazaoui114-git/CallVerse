"""Tool registry: the per-agent allow-lists and the ONLY way an agent can run a tool.

Rule: a tool call outside the agent's allow-list is refused and logged.
Agents never call tool functions directly; they always go through run_tool(), which checks
the list first. This is a hard rule in code, not a request in a prompt.

Four kinds of tools:
- READ tools (shopnova_tools.py): look up facts, change nothing;
- search_policy (kb/search.py): find company rules by meaning;
- proposal tools (proposal_tools.py): only write a PROPOSAL for the Coordinator, never act;
- ask_agent (agents/ask.py): ask another agent (Agent A) a question.

T21: the allow-lists are per COMPANY and agent. Each company has its own table of tools, so a tool of one company simply
does not exist for an agent working on a ticket of the other. run_tool() gets the company from the agent (which got it
from the ticket); the model can never choose it.
"""

from callverse import trace
from callverse.agents import ask
from callverse.kb import search
from callverse.tools import atlas_tools, proposal_tools, shopnova_tools

# All tools that exist in the prototype (name -> function / schema).
TOOL_FUNCTIONS = {
    **shopnova_tools.FUNCTIONS,
    "search_policy": search.search_policy_tool,
    "propose_refund": proposal_tools.propose_refund,
    "propose_subscription": proposal_tools.propose_subscription,
    "ask_agent": ask.ask_agent,
}
TOOL_SCHEMAS = {
    **shopnova_tools.SCHEMAS,
    "search_policy": search.SCHEMA,
    "propose_refund": proposal_tools.SCHEMA,
    "propose_subscription": proposal_tools.SUBSCRIPTION_SCHEMA,
    "ask_agent": ask.SCHEMA,
}

# Tools that run another agent: they get the caller's LLM function (so tests can use a fake LLM).
RUNS_AN_AGENT = {"ask_agent"}

# Allow-lists: which tools each agent may use.
# Status & Tracking: read-only tools + rules + company profile (carriers, delivery promise, cities).
# T09: + propose_subscription (only a proposal: the Coordinator approves, then the platform records it).
AGENT_A = ["get_user", "get_order", "get_tracking", "get_company_profile", "search_policy", "propose_subscription"]
# Payment & Refund: no get_tracking (delivery facts come from Agent A through ask_agent);
# propose_refund only creates a proposal.
AGENT_B = ["get_order", "get_refunds", "search_policy", "propose_refund", "ask_agent"]

ALLOW_LISTS = {
    "A": AGENT_A,
    "B": AGENT_B,
    # Intake is not an agent, but it reads facts through the same gate: order + tracking only, no user data.
    "INTAKE": ["get_order", "get_tracking"],
}


# T21: Atlas Travel. No write function is here: proposal tools only propose (no amount), and no agent can reach
# callverse/data/atlas/writes.py. Agent A reads; Agent B reads, proposes and can ask Agent A.
ATLAS_AGENT_A = ["get_user", "get_hotel_booking", "get_flight_booking", "get_flight", "get_company_profile",
                 "search_policy"]
ATLAS_AGENT_B = ["get_hotel_booking", "get_flight_booking", "get_refunds", "search_policy", "propose_refund",
                 "propose_compensation", "propose_hotel_cancellation", "ask_agent"]

ATLAS_ALLOW_LISTS = {
    "A": ATLAS_AGENT_A,
    "B": ATLAS_AGENT_B,
    "INTAKE": ["get_hotel_booking", "get_flight_booking"],
}
ATLAS_TOOL_FUNCTIONS = {**atlas_tools.FUNCTIONS, **proposal_tools.ATLAS_FUNCTIONS, "ask_agent": ask.ask_agent}
ATLAS_TOOL_SCHEMAS = {**atlas_tools.SCHEMAS, **proposal_tools.ATLAS_SCHEMAS, "ask_agent": ask.ATLAS_SCHEMA}

# Company -> (its allow-lists, its tool functions, its tool schemas).
COMPANY_TOOLS = {
    "shopnova": (ALLOW_LISTS, TOOL_FUNCTIONS, TOOL_SCHEMAS),
    "atlas": (ATLAS_ALLOW_LISTS, ATLAS_TOOL_FUNCTIONS, ATLAS_TOOL_SCHEMAS),
}


def schemas_for(agent: str, company: str = "shopnova") -> list[dict]:
    """Tool schemas sent to the LLM for this agent: the model only SEES the tools it is allowed to use."""
    allow_lists, _, schemas = COMPANY_TOOLS[company]
    return [schemas[name] for name in allow_lists.get(agent, [])]


def run_tool(agent: str, name: str, args: dict, chat_fn=None, company: str = "shopnova") -> dict:
    """Run tool `name` for `agent` if it is on the agent's allow-list for this company; otherwise refuse.

    The result (or the refusal) is logged to the trace and returned as a dict,
    so it can be sent back to the model. chat_fn is only passed to tools that run an agent.
    """
    allow_lists, functions, _ = COMPANY_TOOLS[company]
    allowed = allow_lists.get(agent, [])
    if name not in allowed:
        result = {"error": f"tool '{name}' is not allowed for agent {agent}"}
        trace.log("tool_refused", "registry", {"agent": agent, "tool": name, "args": args,
                                               "allowed": allowed})
        return result

    call_args = dict(args)
    if name in RUNS_AN_AGENT:
        call_args["chat_fn"] = chat_fn   # set by our code, so the model cannot choose it
        call_args["company"] = company   # the same: the agent asked works for the same company
    try:
        result = functions[name](**call_args)
    except Exception as e:  # bad arguments from the model, etc.: report it instead of crashing
        result = {"error": f"{type(e).__name__}: {e}"}

    trace.log("tool_call", "registry", {"agent": agent, "tool": name, "args": args, "result": result})
    return result
