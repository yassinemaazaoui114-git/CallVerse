"""List every policy search the agents made in existing trace files (read-only, no model, no API call).

Usage (from the repo root):
    python -m scripts.trace_policy_searches traces/<file>.jsonl [traces/<file2>.jsonl ...]

For each `policy_search` step it prints one line: the client's message, the agent that searched, its query,
the rules returned (with scores), the rule the agent then cited (its proposal's rule_id, or rule ids written
in its final answer) and the Coordinator's decision with its rule. Used in T13d to check whether the rule the
agents relied on was among the 2 rules the search gave them.
"""

import json
import re
import sys
from pathlib import Path

RULE_ID = re.compile(r"R-[A-Z]{3}-\d{2}")        # e.g. R-REF-03


def policy_searches(lines: list[dict]) -> list[dict]:
    """One dict per policy_search step, completed with what happened after it in the same message."""
    found = []
    open_searches = []                           # searches of the current message (closed at the next one)
    message = None
    for i, line in enumerate(lines):
        step, data = line["step"], line["data"]
        if step == "intake_start":               # a new client message starts
            message, open_searches = data["text"], []
        elif step == "policy_search":
            # The registry's tool_call line right after the search says which agent called it.
            call = next((x for x in lines[i + 1:i + 4] if x["step"] == "tool_call"), None)
            search = {"message": message, "agent": call["data"]["agent"] if call else "?",
                      "query": data["query"],
                      "returned": [(r["id"], r["score"]) for r in data["results"]],
                      "cited": [], "coordinator": None}
            found.append(search)
            open_searches.append(search)
        elif step == "proposal" and data.get("rule_id"):
            for s in open_searches:
                s["cited"].append(data["rule_id"])
        elif step == "final_answer":
            output = data.get("output", {})
            for s in open_searches:
                if s["agent"] == output.get("agent"):
                    s["cited"] += RULE_ID.findall(output.get("answer") or "")
        elif step == "coordinator_decision":
            for s in open_searches:
                s["coordinator"] = (data.get("outcome"), data.get("rule_id"))
    for s in found:
        s["cited"] = sorted(set(s["cited"]))
    return found


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    total = 0
    for path in sys.argv[1:]:
        lines = [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
        searches = policy_searches(lines)
        total += len(searches)
        print(f"\n### {Path(path).name}: {len(searches)} policy searches")
        for s in searches:
            returned = ", ".join(f"{rule} {score:.3f}" for rule, score in s["returned"])
            in_returned = all(c in [r for r, _ in s["returned"]] for c in s["cited"]) if s["cited"] else None
            print(f"- [{s['agent']}] {s['message']!r}\n    query: {s['query']!r}\n    returned: {returned}"
                  f"\n    cited: {s['cited'] or '-'} (all among returned: {in_returned})"
                  f"   coordinator: {s['coordinator']}")
    print(f"\nTotal: {total} policy searches")


if __name__ == "__main__":
    main()
