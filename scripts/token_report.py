"""Tokens used per Agent B turn, read from trace files (no API call).

Usage (from the repo root):
    python -m scripts.token_report traces/run_A.jsonl traces/run_B.jsonl ...

A "B turn" = everything between Agent B's agent_start and its final_answer (or step_limit):
B's own LLM calls + Agent A's calls made inside ask_agent. Tokens come from the llm_call lines.
"""

import json
import sys


def b_turns(path: str) -> list[dict]:
    """[{tokens, calls, models}] for every Agent B turn of one trace file."""
    turns, current = [], None
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        if r["step"] == "agent_start" and r["actor"] == "agent_B":
            current = {"tokens": 0, "calls": 0, "models": set()}
        elif current is not None and r["step"] == "llm_call":
            current["tokens"] += r["data"]["tokens"]["total"] or 0
            current["calls"] += 1
            current["models"].add(r["data"]["model"])
        elif current is not None and r["actor"] == "agent_B" and r["step"] in ("final_answer", "step_limit"):
            turns.append(current)
            current = None
    return turns


def main() -> None:
    all_turns = []
    for path in sys.argv[1:]:
        for t in b_turns(path):
            all_turns.append(t)
            print(f"{path}: {t['tokens']} tokens, {t['calls']} LLM calls, models {sorted(t['models'])}")
    if all_turns:
        avg = sum(t["tokens"] for t in all_turns) / len(all_turns)
        print(f"\nAgent B turns: {len(all_turns)}   average tokens per turn: {avg:.0f}")


if __name__ == "__main__":
    main()
