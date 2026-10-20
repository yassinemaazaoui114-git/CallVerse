"""Run the SLM reply writer on one decision (or a whole set) and print the reply, the check and the time.

Usage (from the repo root; Ollama must be running with the model in config.yaml, role "slm"):
    python scripts/run_slm.py --id s01             one decision of the v1 test set (spent: dev use only since T05b)
    python scripts/run_slm.py --file my.json       a decision from a JSON file (one decision dict)
    python scripts/run_slm.py --dev d02            one decision of the dev set (callverse/slm/dev_decisions.json)
    python scripts/run_slm.py --all dev            every dev decision + a summary (for prompt work)
    python scripts/run_slm.py --all test           every v1 decision + a summary (spent set, dev use only)
    python scripts/run_slm.py --all test2          the v2 HELD-OUT set (T05b): run ONCE, at the end, never for tuning
    python scripts/run_slm.py --all dev --model qwen2.5:3b     the same, with another Ollama model (comparison)
"""

import argparse
import json
import sys
from pathlib import Path

# Allow "python scripts/run_slm.py" as well as "python -m scripts.run_slm".
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from callverse import trace  # noqa: E402
from callverse.config import load_config  # noqa: E402
from callverse.slm.check import check_reply  # noqa: E402
from callverse.slm.writer import write_reply  # noqa: E402

SETS = {"test": ROOT / "tests" / "data" / "slm_test_decisions.json",        # v1, spent (dev use only)
        "test2": ROOT / "tests" / "data" / "slm_test_decisions_v2.json",    # v2, held out: final run only
        "dev": ROOT / "callverse" / "slm" / "dev_decisions.json"}


def load_set(name: str) -> list[dict]:
    return json.loads(SETS[name].read_text(encoding="utf-8"))["decisions"]


def find(name: str, decision_id: str) -> dict:
    for d in load_set(name):
        if d["id"] == decision_id:
            return d
    sys.exit(f"No decision '{decision_id}' in {SETS[name]}")


def show(decision: dict) -> dict:
    result = write_reply(decision)
    print(f"--- {decision.get('id', 'decision')}  outcome={decision.get('outcome')}  order={decision.get('order_id')}"
          f"  style={decision.get('style')}")
    print(f"Reply   : {result['reply']}")
    status = "PASSED" if result["check"]["passed"] else f"FAILED {result['check']['problems']}"
    source = "template" if result["used_template"] else f"SLM (attempt {result['attempts']})"
    print(f"Check   : {status}   source: {source}   time: {result['seconds']:.2f} s")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SLM reply writer.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--id", help="decision id from the held-out test set (e.g. s01)")
    group.add_argument("--file", help="JSON file with one decision")
    group.add_argument("--dev", help="decision id from the dev set (e.g. d01)")
    group.add_argument("--all", choices=["dev", "test", "test2"], help="run a whole set and print a summary")
    parser.add_argument("--model", help="override the SLM model for this run only (e.g. qwen2.5:3b)")
    args = parser.parse_args()

    trace_path = trace.start_run()
    if args.model:   # comparison runs: change the model in memory only, config.yaml is not touched
        load_config()["models"]["slm"][0]["model"] = args.model
    model = load_config()["models"]["slm"][0]
    print(f"SLM model: {model['provider']}/{model['model']}\n")

    if args.id:
        show(find("test", args.id))
    elif args.dev:
        show(find("dev", args.dev))
    elif args.file:
        show(json.loads(Path(args.file).read_text(encoding="utf-8")))
    else:
        decisions = load_set(args.all)
        results = [show(d) for d in decisions]
        n = len(results)
        no_template = sum(1 for r in results if not r["used_template"])
        first_try = sum(1 for r in results if not r["used_template"] and r["attempts"] == 1)
        final_ok = sum(1 for d, r in zip(decisions, results) if check_reply(r["reply"], d)["passed"])
        print(f"\nSummary ({args.all}, {n} decisions):")
        print(f"  passed the check without template : {no_template}/{n}  (first try: {first_try}/{n})")
        print(f"  final replies passing the check   : {final_ok}/{n}")
        with_must = [(d, r) for d, r in zip(decisions, results) if d.get("must_say")]
        must_ok = sum(1 for d, r in with_must
                      if all(" ".join(m.lower().split()) in " ".join(r["reply"].lower().split()) for m in d["must_say"]))
        print(f"  must_say present (final replies)  : {must_ok}/{len(with_must)}")
        print(f"  average time per reply            : {sum(r['seconds'] for r in results) / n:.2f} s")
    print(f"\nTrace file: {trace_path}")


if __name__ == "__main__":
    main()
