"""Demo: send one client message to Agent A and print its answer.

Usage (from the repo root, so Python can find the `callverse` package):
    python -m scripts.run_demo "Hi, where is my order 4512?"
"""

import sys

from callverse import trace
from callverse.agents.agent_a import AgentA
from callverse.data.seed import seed


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")   # LLM answers may hold characters the Windows console code page lacks
    message = " ".join(sys.argv[1:]) or "Hi, where is my order 4512?"

    seed()                         # fresh placeholder database, so every demo starts from the same data
    trace_path = trace.start_run()  # one trace file per demo run

    result = AgentA().run(message)

    print(f"Client : {message}")
    print(f"Agent A: {result['answer']}")
    print()
    print(f"Tools used : {[c['tool'] for c in result['tool_calls']] or 'none'}")
    print(f"Handover   : {result.get('handover') or 'none'}")
    print(f"Steps      : {result['steps']} (stopped by {result['stopped_by']})")
    print(f"Trace file : {trace_path}")


if __name__ == "__main__":
    main()
