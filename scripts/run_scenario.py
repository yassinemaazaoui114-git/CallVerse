"""Run a demo scenario end to end and print what happened, step by step.

Usage (from the repo root):
    python -m scripts.run_scenario S0                  # status question for 4510 (info, no proposal)
    python -m scripts.run_scenario S1                  # late order 4512, refund approved
    python -m scripts.run_scenario S2                  # = S1 with --inject-error: first proposal 70.00
    python -m scripts.run_scenario S1 --inject-error   # same as S2
    python -m scripts.run_scenario S4                  # 4515, 378 TND: finance (Layer 3) approves
    python -m scripts.run_scenario S3                  # 4510: "tell me when it arrives" -> clock -> 1 message

Every scenario first rebuilds the data and resets the clock, so the order of the runs never matters.
The SLM is warmed up first (one tiny call), so the first reply is not slowed by loading the model.

--inject-error simulates an agent mistake: Agent B's FIRST proposal reaches the Coordinator with
amount 70.00 instead of what B proposed. It is written in the trace (step "inject_error"), so the
demo never hides it. The Coordinator sends it back (R-REF-05), B corrects, the Coordinator approves.

The end shows the FINAL REPLY the user gets (written by the SLM from the decision, T08), its source
(slm / slm_retry / template), and a leak check: internal words must never reach the user.
"""

import json
import re
import sys
import time

from callverse import pipeline, trace
from callverse.data import clock, reports
from callverse.data.seed import seed
from callverse.intake import intake
from callverse.notifier.notifier import run_notifier
from callverse.slm.writer import warm_up
from callverse.tools.shopnova_tools import get_order, get_refunds

SCENARIOS = {
    "S3": {"message": "Hi, can you let me know when my order 4510 arrives?", "inject": False},
    "S0": {"message": "Hi, where is my order 4510?", "inject": False},
    "S1": {"message": "Order 4512 is a week late. I want my money back.", "inject": False},
    "S2": {"message": "Order 4512 is a week late. I want my money back.", "inject": True},
    "S4": {"message": "Order 4515 is very late, I want a full refund.", "inject": False},
}
INJECTED_AMOUNT = 70.00

# Internal words that must never be in a final reply (T08 leak check).
LEAK_RE = re.compile(r"coordinator|agent|proposal|P-0|\bR-[A-Z]{0,3}-?\d|sent for checking", re.IGNORECASE)


def leaks(reply: str) -> list[str]:
    """Internal words found in a reply (empty list = clean)."""
    return [m.group(0) for m in LEAK_RE.finditer(reply or "")]


def inject_first_amount(review):
    """Wrap the Coordinator's review: the first proposal gets the wrong amount (demo of S2)."""
    state = {"done": False}

    def wrapped(proposal, case):
        if not state["done"]:
            state["done"] = True
            trace.log("inject_error", "scenario", {"original_amount": proposal["params"]["amount"],
                                                   "injected_amount": INJECTED_AMOUNT})
            proposal = {**proposal, "params": {**proposal["params"], "amount": INJECTED_AMOUNT}}
        return review(proposal, case)
    return wrapped


def step_list(path) -> list[str]:
    """Readable lines from the trace: routing, agent tools, proposals, checks, decisions, writes."""
    lines = []
    for raw in open(path, encoding="utf-8"):
        r = json.loads(raw)
        s, d = r["step"], r["data"]
        if s == "route":
            lines.append(f"Router        -> agent {d['agent']} (reason {d['reason']}, priority {d['priority_label']})")
        elif s == "agent_start":
            lines.append(f"{d['agent']} starts")
        elif s == "tool_call" and d["agent"] != "INTAKE":
            lines.append(f"  {d['agent']} tool {d['tool']}({json.dumps(d['args'], ensure_ascii=False)[:90]})")
        elif s == "tool_refused":
            lines.append(f"  REFUSED tool {d['tool']} for agent {d['agent']}")
        elif s == "inject_error":
            lines.append(f"INJECTED ERROR: amount {d['original_amount']} -> {d['injected_amount']}")
        elif s == "coordinator_check":
            lines.append(f"  Coordinator check {d['check']:<17} {d['result'].upper():4s} {d.get('rule_id') or ''}")
        elif s == "layer3_decision":
            lines.append(f"  Layer 3 (finance): {d['result'].get('decision')}")
        elif s == "coordinator_decision":
            lines.append(f"Coordinator   -> {d['outcome'].upper()} {d['proposal_id']}: {d['reason']}")
        elif s == "send_back_to_agent":
            lines.append(f"Back to agent {d['agent']}: {d['note']}")
        elif s == "db_write":
            lines.append(f"  Platform write {d['function']}: {json.dumps(d['result'], ensure_ascii=False, default=str)[:110]}")
        elif s == "llm_call":
            lines.append(f"    (LLM {d['model']}, {d['tokens']['total']} tokens)")
        elif s in ("llm_wait", "llm_fallback"):
            lines.append(f"    ({s}: {d['model']} {d.get('seconds', '')})")
        elif s == "slm_warmup":
            lines.append(f"SLM warm-up: {'ok' if d['ok'] else 'FAILED (' + str(d['error']) + ')'} in {d['seconds']} s")
    return lines


def run_s3_after_reply() -> list[dict]:
    """S3, after the user's reply: move the clock and run the notifier (expected 0, 1, 0 messages)."""
    results = []
    for label, hours in (("+24 h", 24), ("+6 h (total 30 h)", 6), ("again, no clock move", None)):
        if hours:
            moved = clock.advance(hours)
            events = [f"{a['order_id']} -> {a['status']}" for a in moved["applied"]]
            print(f"\nClock {label}: now {moved['to']}  timeline: {events or 'nothing new'}")
        else:
            print(f"\nNotifier {label}")
        messages = run_notifier()
        print(f"Notifier: {len(messages)} message(s)")
        for m in messages:
            print(f"  -> order {m['order_id']} [{m['reply_source']}]: {m['text']}   leak check: {leaks(m['text']) or 'clean'}")
        results.append({"step": label, "messages": messages})
    subs = reports.list_rows("subscriptions")
    print(f"\nSubscriptions: {[(s['id'], s['order_id'], s['event'], s['status']) for s in subs]}")
    return results


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    name = args[0].upper() if args else "S1"
    if name not in SCENARIOS:
        sys.exit(f"unknown scenario {name}: use one of {list(SCENARIOS)}")
    scenario = SCENARIOS[name]
    inject = scenario["inject"] or "--inject-error" in args

    seed()                              # same placeholder data on every run
    trace_path = trace.start_run()
    clock.reset()                       # the clock back to 2026-10-09 09:00 (story S3 moves it)
    intake.load_models()
    warm = warm_up()                    # load the SLM now, not during the first reply
    if not warm["ok"]:
        print(f"Warning: {warm['warning']} ({warm['error']})")
    if inject:
        pipeline.review = inject_first_amount(pipeline.review)

    print(f"Scenario {name}{' (inject error)' if inject else ''}")
    print(f"Client   : {scenario['message']}\n")
    start = time.perf_counter()
    out = pipeline.handle(scenario["message"])
    seconds = round(time.perf_counter() - start, 1)

    print("\n".join(step_list(trace_path)))
    decision = out["decision"] or {}
    order_id = out["ticket"]["order_id"]
    print(f"\nAgent text (trace only, not sent): {out['agent_text']}")
    print(f"Decision : {decision.get('outcome')}  proposal {decision.get('proposal_id')}  rule {decision.get('rule_id')}")
    # As recorded by the platform (so an injected error shows its real amount).
    recorded = sorted(reports.list_rows("proposals"), key=lambda p: p["id"])
    print("Proposals: " + "  ".join(f"{p['id']} {p['action']} {p['params'].get('amount') or p['params'].get('event')}"
                                    f" -> {p['decision']}" for p in recorded))
    if order_id:
        print(f"Order {order_id}: status {get_order(order_id)['status']}, refunds {get_refunds(order_id)['refunds']}")
    slm_models = sorted({json.loads(x)["data"].get("model") for x in open(trace_path, encoding="utf-8")
                         if '"role": "slm"' in x and '"step": "llm_call"' in x})
    print(f"\nFINAL REPLY [{out['reply_source']}]: {out['final_reply']}")
    print(f"Leak check : {leaks(out['final_reply']) or 'clean'}")
    print(f"Seconds    : {seconds} (message to reply)   SLM model: {', '.join(slm_models) or 'none (template)'}")
    if name == "S3":
        run_s3_after_reply()
    print(f"Trace file : {trace_path}")


if __name__ == "__main__":
    main()
