"""Tool registry: the per-agent allow-lists and the ONLY way an agent can run a tool.

Rule: a tool call outside the agent's allow-list is refused and logged.
Agents never call tool functions directly; they always go through run_tool(), which checks
the list first. This is a hard rule in code, not a request in a prompt.

Four kinds of tools:
- READ tools (shopnova_tools.py): look up facts, change nothing;
- search_policy (kb/search.py): find company rules by meaning;
- proposal tools (proposal_tools.py): only write a PROPOSAL for the Coordinator, never act;
- ask_agent (agents/ask.py): ask another agent (Agent A) a question.

T14b: what an agent (or Intake) READS at ShopNova is cleaned first: the database labels `source` / `source_id` and the
fields `city` / `payment` (T14c: and the labels `ai_generated` / `scripted`) are removed from the tool result (hide_fields), because the agents do not need them and a small
model comments on them. The database, the Coordinator and writes.py still read the full rows (they call the tool functions
directly, not through run_tool). Atlas has its own HIDDEN list in data/atlas/reads.py.

T21: the allow-lists are per COMPANY and agent. Each company has its own table of tools, so a tool of one company simply
does not exist for an agent working on a ticket of the other. run_tool() gets the company from the agent (which got it
from the ticket); the model can never choose it.
"""

from callverse import trace
from callverse.agents import ask, ask_c
from callverse.kb import search
from callverse.tools import atlas_c_tools, atlas_tools, proposal_tools, shopnova_tools, stock_tools

# All tools that exist in the prototype (name -> function / schema).
TOOL_FUNCTIONS = {
    **shopnova_tools.FUNCTIONS,
    "search_policy": search.search_policy_tool,
    "propose_refund": proposal_tools.propose_refund,
    "propose_subscription": proposal_tools.propose_subscription,
    "propose_cancellation": proposal_tools.propose_cancellation,
    "ask_agent": ask.ask_agent,
    # P20: Agent C's stock read and its three proposal tools (they only propose).
    "get_stock": stock_tools.get_stock,
    **proposal_tools.C_FUNCTIONS,
    **ask_c.FUNCTIONS,   # C asks A ("get the facts") and D ("is it available?")
}
TOOL_SCHEMAS = {
    **shopnova_tools.SCHEMAS,
    "search_policy": search.SCHEMA,
    "propose_refund": proposal_tools.SCHEMA,
    "propose_subscription": proposal_tools.SUBSCRIPTION_SCHEMA,
    "propose_cancellation": proposal_tools.CANCELLATION_SCHEMA,
    "ask_agent": ask.SCHEMA,
    "get_stock": stock_tools.SCHEMA,
    **proposal_tools.C_SCHEMAS,
    **ask_c.SCHEMAS,
}

# T14b: fields the ShopNova read tools do not show to agents (anywhere inside the result, rows of lists included).
# T14c: + the data labels ai_generated / scripted (Atlas's reads.py already hides them): they say how a demo row was
# made, which is not a fact about the client's case.
HIDDEN_FIELDS = ("source", "source_id", "city", "payment", "ai_generated", "scripted")


def hide_fields(value):
    """A copy of a tool result without HIDDEN_FIELDS, at every depth."""
    if isinstance(value, dict):
        return {k: hide_fields(v) for k, v in value.items() if k not in HIDDEN_FIELDS}
    if isinstance(value, list):
        return [hide_fields(v) for v in value]
    return value


# Tools that run another agent: they get the caller's LLM function (so tests can use a fake LLM).
RUNS_AN_AGENT = {"ask_agent", *ask_c.FUNCTIONS}

# Allow-lists: which tools each agent may use.
# Status & Tracking: read-only tools + rules + company profile (carriers, delivery promise, cities).
# T09: + propose_subscription (only a proposal: the Coordinator approves, then the platform records it).
AGENT_A = ["get_user", "get_order", "get_tracking", "get_company_profile", "search_policy", "propose_subscription"]
# Payment & Refund: no get_tracking (delivery facts come from Agent A through ask_agent);
# propose_refund and propose_cancellation (T14a) only create a proposal.
AGENT_B = ["get_order", "get_refunds", "search_policy", "propose_refund", "propose_cancellation", "ask_agent"]

# P20: Urgent & Special Help. Its facts come through the spec's links: it ASKS A for the delivery facts and D for the
# stock (no get_tracking / get_stock of its own), reads the order (items) itself, and hands a refund to B
# ([HANDOVER: B], not a tool; no refunds read: T06, B only). Its three action tools only create a proposal
# (replacement, hold, assistance); the Coordinator writes after the client says yes.
AGENT_C = ["get_order", "get_facts_from_a", "check_availability_with_d", "search_policy",
           "propose_replacement", "propose_hold", "propose_assistance"]
# Agent D (Availability & Supply) is NOT here: it is rules, not an LLM with tools (agents/agent_d.py).

ALLOW_LISTS = {
    "A": AGENT_A,
    "B": AGENT_B,
    "C": AGENT_C,
    # Intake is not an agent, but it reads facts through the same gate: order + tracking only, no user data.
    "INTAKE": ["get_order", "get_tracking"],
}


# T21: Atlas Travel. No write function is here: proposal tools only propose (no amount), and no agent can reach
# callverse/data/atlas/writes.py. Agent A reads; Agent B reads, proposes and can ask Agent A.
ATLAS_AGENT_A = ["get_user", "get_hotel_booking", "get_flight_booking", "get_flight", "get_company_profile",
                 "search_policy"]
ATLAS_AGENT_B = ["get_hotel_booking", "get_flight_booking", "get_refunds", "search_policy", "propose_refund",
                 "propose_compensation", "propose_hotel_cancellation", "ask_agent"]

# P20: Agent C at Atlas: reads the flight booking, finds later flights, proposes a new flight (AT-FLT-01) or a
# wheelchair (AT-AST-01). Only proposals: the Atlas Coordinator writes after the client's yes.
ATLAS_AGENT_C = ["get_flight_booking", "get_flight", "find_alternative_flights", "search_policy",
                 "propose_rebooking", "propose_assistance"]

ATLAS_ALLOW_LISTS = {
    "A": ATLAS_AGENT_A,
    "B": ATLAS_AGENT_B,
    "C": ATLAS_AGENT_C,
    "INTAKE": ["get_hotel_booking", "get_flight_booking"],
}
ATLAS_TOOL_FUNCTIONS = {**atlas_tools.FUNCTIONS, **proposal_tools.ATLAS_FUNCTIONS, "ask_agent": ask.ask_agent,
                        **atlas_c_tools.FUNCTIONS}
ATLAS_TOOL_SCHEMAS = {**atlas_tools.SCHEMAS, **proposal_tools.ATLAS_SCHEMAS, "ask_agent": ask.ATLAS_SCHEMA,
                      **atlas_c_tools.SCHEMAS}

# Company -> (its allow-lists, its tool functions, its tool schemas).
COMPANY_TOOLS = {
    "shopnova": (ALLOW_LISTS, TOOL_FUNCTIONS, TOOL_SCHEMAS),
    "atlas": (ATLAS_ALLOW_LISTS, ATLAS_TOOL_FUNCTIONS, ATLAS_TOOL_SCHEMAS),
}


def schemas_for(agent: str, company: str = "shopnova") -> list[dict]:
    """Tool schemas sent to the LLM for this agent: the model only SEES the tools it is allowed to use."""
    allow_lists, _, schemas = COMPANY_TOOLS[company]
    return [schemas[name] for name in allow_lists.get(agent, [])]


def run_tool(agent: str, name: str, args: dict, chat_fn=None, company: str = "shopnova",
             booking_type: str | None = None) -> dict:
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
        call_args["booking_type"] = booking_type
    if company == "atlas" and name == "search_policy":
        # T14f (t05): the rules of the ticket's booking type come first (flight -> AT-FLT ...). Set by our code from
        # Intake's look-up, so the model cannot get it wrong. Any model argument of that name is replaced.
        call_args["booking_type"] = booking_type
    try:
        result = functions[name](**call_args)
        if company == "shopnova" and name in shopnova_tools.FUNCTIONS:
            result = hide_fields(result)   # T14b
    except Exception as e:  # bad arguments from the model, etc.: report it instead of crashing
        result = {"error": f"{type(e).__name__}: {e}"}

    trace.log("tool_call", "registry", {"agent": agent, "tool": name, "args": args, "result": result})
    return result
