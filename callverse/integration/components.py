"""Finds the team's components that exist in the repository, at call time.

Why at call time: when a teammate's branch is merged (router T04, Coordinator, SLM T05, Agent B), the
workflow picks the real module up with NO change here. Each entry is (module, name) = the interface the
task files define (the T04 router is merged and is now imported directly by workflow.py; it stays listed
here only for /api/health):
  - router       callverse/queues/router.py        route(ticket) -> {agent, layer, reason, priority_label}  (T04)
  - coordinator  callverse/coordinator/coordinator.py  review(proposal) -> decision                        (Brief #2)
  - slm          callverse/slm/writer.py           write_reply(decision, history=None) -> {reply, ...}      (T05)
  - agent_b      callverse/agents/agent_b.py       class AgentB(BaseAgent)                                  (Brief #2)
"""

import importlib

INTERFACES = {
    "router": ("callverse.queues.router", "route"),
    "coordinator": ("callverse.coordinator.coordinator", "review"),
    "slm": ("callverse.slm.writer", "write_reply"),
    "agent_b": ("callverse.agents.agent_b", "AgentB"),
}


def get(name: str):
    """The real function/class for `name`, or None when that component is not in the repository yet."""
    module_name, attr = INTERFACES[name]
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        if e.name and module_name.startswith(e.name):   # the module itself is missing: not built yet
            return None
        raise                                            # a real import error inside a built module
    return getattr(module, attr, None)


def status() -> dict:
    """{"router": "built"|"not built", ...} for /api/health and the docs."""
    return {name: ("built" if get(name) else "not built") for name in INTERFACES}
