"""The tool-calling loop shared by all agents.

How one agent turn works:
  1. Send system prompt + conversation + the agent's ALLOWED tool schemas to the LLM (llm.chat).
  2. If the model asks for tools, run each one through the registry (which checks the allow-list)
     and send the results back to the model.
  3. Repeat until the model gives a final text answer, or stop after MAX_STEPS model calls
     (a safety limit so a confused model cannot loop forever and burn API quota).
Every step is written to the trace.
"""

import json

from callverse import llm, trace
from callverse.tools.registry import run_tool, schemas_for

MAX_STEPS = 5   # default limit; an agent with more steps in its job can set its own max_steps

# Shown to the client if the agent hits the step limit without a final answer.
STEP_LIMIT_ANSWER = ("Sorry, I could not complete your request right now. "
                     "A colleague will get back to you shortly.")


class BaseAgent:
    agent_id = "?"        # key in the registry allow-lists, e.g. "A"
    name = "Base agent"   # human-readable name, used in traces
    role_key = "agents"   # which models of config.yaml this agent uses (M2)
    max_steps = MAX_STEPS # most model calls in one turn

    def __init__(self, chat_fn=None):
        # chat_fn lets the tests plug in a fake LLM; normally it is the shared llm.chat.
        self.chat = chat_fn or llm.chat

    @property
    def actor(self) -> str:
        return f"agent_{self.agent_id}"

    def system_prompt(self) -> str:
        """Each agent writes its own instructions."""
        raise NotImplementedError

    def postprocess(self, answer: str) -> dict:
        """Hook for agents to read extra signals from the final answer. Default: nothing extra."""
        return {"answer": answer}

    def run(self, user_message: str, history: list[dict] | None = None) -> dict:
        """Run one agent turn and return {"agent", "answer", "tool_calls", "steps", "stopped_by", ...}."""
        messages = [{"role": "system", "content": self.system_prompt()}]
        messages += history or []
        messages.append({"role": "user", "content": user_message})
        tools = schemas_for(self.agent_id)
        tool_calls_made = []

        trace.log("agent_start", self.actor, {"agent": self.name, "input": user_message,
                                              "allowed_tools": [t["function"]["name"] for t in tools]})

        for step in range(1, self.max_steps + 1):
            reply = self.chat(self.role_key, messages, tools=tools)

            # No tool requested -> this is the final answer.
            if not reply.tool_calls:
                answer = reply.content or ""
                result = {"agent": self.agent_id, "tool_calls": tool_calls_made,
                          "steps": step, "stopped_by": "final_answer"}
                result.update(self.postprocess(answer))
                trace.log("final_answer", self.actor, {"step": step, "output": result})
                return result

            # The model wants tools. First put its request in the conversation history...
            messages.append({
                "role": "assistant",
                "content": reply.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in reply.tool_calls
                ],
            })
            # ...then run each tool (through the registry) and add its result.
            for tc in reply.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = None
                if isinstance(args, dict):
                    # chat_fn is passed on only to tools that run another agent (ask_agent).
                    output = run_tool(self.agent_id, tc.function.name, args, chat_fn=self.chat)
                else:
                    output = {"error": "tool arguments were not valid JSON"}
                tool_calls_made.append({"tool": tc.function.name, "args": args, "result": output})
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps(output, ensure_ascii=False, default=str)})

            trace.log("agent_step", self.actor, {"step": step,
                                                 "tool_calls": [tc.function.name for tc in reply.tool_calls]})

        # Safety limit reached without a final answer.
        result = {"agent": self.agent_id, "answer": STEP_LIMIT_ANSWER, "tool_calls": tool_calls_made,
                  "steps": self.max_steps, "stopped_by": "max_steps"}
        trace.log("step_limit", self.actor, {"output": result})
        return result
