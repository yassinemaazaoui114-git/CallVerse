"""Final evaluation of Intake on the HELD-OUT test set (tests/data/intake_test_messages.json).

Usage (from the repo root):
    python -m scripts.eval_intake

This script only MEASURES. Nothing here may be used to change thresholds or examples:
the threshold was chosen on the examples (scripts/choose_threshold.py).

Prints one row per message (expected vs found reasons, order id, priority), then the checks of T03:
reason accuracy, multi-reason messages, order ids found, priority pairs, speed, needs_llm count.
"""

import json
import time

from callverse import trace
from callverse.config import PROJECT_ROOT
from callverse.data.seed import seed
from callverse.intake import intake

TEST_PATH = PROJECT_ROOT / "tests" / "data" / "intake_test_messages.json"


def main() -> None:
    data = json.loads(TEST_PATH.read_text(encoding="utf-8"))
    seed()
    trace_path = trace.start_run()

    start = time.perf_counter()
    intake.load_models()
    load_seconds = time.perf_counter() - start

    rows, times = [], []
    for m in data["messages"]:
        t = intake.process(m["text"])
        times.append(t["seconds"])
        found = sorted(r["reason"] for r in t["reasons"])
        rows.append({
            "id": m["id"], "expected": sorted(m["reasons"]), "found": found,
            "reason_ok": found == sorted(m["reasons"]),
            "order_expected": m["order_id"], "order_found": t["order_id"],
            "priority": f"{t['priority_label']} {t['priority_score']:.2f}",
            "needs_llm": t["needs_llm"],
        })

    # ---- per-message table ----
    print(f"{'id':4} {'ok':3} {'expected':32} {'found':32} {'order exp/found':16} {'priority':12} llm")
    for r in rows:
        print(f"{r['id']:4} {'yes' if r['reason_ok'] else 'NO':3} {','.join(r['expected']):32} "
              f"{','.join(r['found']):32} {str(r['order_expected']) + '/' + str(r['order_found']):16} "
              f"{r['priority']:12} {'yes' if r['needs_llm'] else ''}")

    # ---- checks ----
    n = len(rows)
    exact = sum(r["reason_ok"] for r in rows)
    multi = [r for r in rows if len(r["expected"]) > 1]
    multi_ok = sum(set(r["expected"]) <= set(r["found"]) for r in multi)
    with_order = [r for r in rows if r["order_expected"] is not None]
    order_ok = sum(r["order_found"] == r["order_expected"] for r in with_order)
    needs_llm = sum(r["needs_llm"] for r in rows)

    print()
    print(f"Reason accuracy (exact set)   : {exact}/{n}   (target >= 17/{n})")
    print(f"Multi-reason messages         : {multi_ok}/{len(multi)} contain all expected reasons "
          f"({', '.join(r['id'] for r in multi)})")
    print(f"Order number found            : {order_ok}/{len(with_order)}")
    print(f"needs_llm (M2 calls)          : {needs_llm}")
    print(f"Model load time               : {load_seconds:.1f} s")
    print(f"Average intake time / message : {sum(times) / len(times):.3f} s (max {max(times):.3f} s)")

    for pair in data["priority_pairs"]:
        high = intake.process(pair["higher"])
        low = intake.process(pair["lower"])
        ok = high["priority_score"] > low["priority_score"]
        print(f"Priority pair {pair['id']}               : {'OK' if ok else 'FAILED'}  "
              f"higher {high['priority_label']} {high['priority_score']:.3f} "
              f"(sev {high['severity']}, time {high['time_pressure']}, emo {high['emotion_intensity']})  vs  "
              f"lower {low['priority_label']} {low['priority_score']:.3f} "
              f"(sev {low['severity']}, time {low['time_pressure']}, emo {low['emotion_intensity']})")

    print(f"Trace file                    : {trace_path}")


if __name__ == "__main__":
    main()
