"""Offline end-to-end demonstration of Agents E and F (research components; nothing in callverse/ is changed).

    python -m v4.d.demo_end_to_end [--run <agent E run_id>]        (from experiments/agents_ef)

Part 1  incoming tickets (real Intake output, v4/d/fixtures) -> queue statistics -> Agent E RL proposal
        -> independent safety check (Worker D rules) -> simulated resource update
Part 2  closed conversations (prototype trace format) -> Agent F: satisfaction + validity, quality flags with
        evidence, rule/knowledge warnings -> owner report
Part 3  F -> E feedback contract with the validity gate enforced (expected today: everything KPI only)
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

AEF = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AEF))
from v4.d.bridge import QUEUES, CapacityState, TicketBook, apply, validate  # noqa: E402
from v4.d.fe_contract import aggregate, from_agent_f  # noqa: E402

FV3 = Path("/tmp/claude-0/-home-user/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/f_v3")


def part1(run_id):
    from v4.e.adapter import AgentEAdapter
    print("=== Part 1: ticket -> Agent E -> safety check -> simulated update")
    ad = AgentEAdapter.load(run_id) if run_id else AgentEAdapter.load()
    tickets = json.loads((AEF / "v4/d/fixtures/intake_tickets.json").read_text())["tickets"]
    tb, state = TicketBook(), CapacityState(alloc=np.array([5, 3, 2, 6]), t_step=0)
    for step in range(3):
        for k, t in enumerate(tickets[step * 4:(step + 1) * 4]):
            q = tb.add(t, arrived_min=step * 5 + k)
            if step == 0 and k < 4:
                print(f"  ticket {t['ticket_id']}: {t['main_reason']:<15} {t['priority_label']:<6} -> {QUEUES[q]}")
        tb.end_step()
        snap = tb.snapshot(now_min=(step + 1) * 5.0, state=state)
        prop = ad.propose(snap)
        ok, why = validate(state, prop["action_id"])
        load = np.array([len(q["waiting"]) + q["ewma_arrivals"] for q in snap["queues"]], float)
        print(f"  step {step}: waiting {[len(q['waiting']) for q in snap['queues']]} sessions {state.alloc.tolist()}"
              f" -> {prop['policy']}: {prop['action']['text'] if 'text' in prop['action'] else prop['action']}"
              f" | veto {prop['safety_veto']} | independent check {'OK' if ok else 'REFUSED ' + '; '.join(why)}"
              f" | {prop['audit']['latency_ms']} ms")
        if ok:
            state = apply(state, prop["action_id"], load)
        state.t_step += 1
        state.budget_spent += float(state.alloc.sum())
    print(f"  final sessions {state.alloc.tolist()} (queue C never below 2: {state.alloc[2] >= 2})")


def part2_3():
    from v4.f.agent_f import AgentF
    print("\n=== Part 2: closed conversation -> Agent F -> owner report")
    scorer = FV3 / "ckpt" / "tfidf_ridge_tail256"
    f = AgentF.load({"scorer": f"tfidf:{scorer}" if scorer.exists() else "none"})
    outs = []
    for p in sorted((AEF / "v4/f/demo_traces").glob("*.jsonl")):
        o = f.process(p)
        outs += o if isinstance(o, list) else [o]
    for o in outs:
        s = o["predicted_satisfaction"]
        print(f"  {o['conversation_id']}: {o['outcome']:<9} grade {o['grade']:<8} satisfaction "
              f"{'—' if s is None else s} [{o['satisfaction_validity']['validity']}] flags "
              f"{[fl['code'] for fl in o['quality_flags'] if fl['severity'] != 'low']}")
    rep = f.owner_report(outs, corpus_label="demo traces (scripted agents, real pipeline)")
    out = AEF / "v4/d/results"
    out.mkdir(exist_ok=True)
    (out / "demo_owner_report.md").write_text(rep["markdown"])
    print(f"  owner report -> {out / 'demo_owner_report.md'}")
    print("\n=== Part 3: F -> E feedback contract (validity gate enforced)")
    agg = aggregate([from_agent_f(o, f.card) for o in outs])
    print(f"  reward channel cells: {len(agg['reward'])}   KPI-only cells: {len(agg['kpi_only'])}   "
          f"refused for reward: {len(agg['refusals'])}/{len(outs)}")
    if agg["refusals"]:
        print("  first refusal reason:", agg["refusals"][0]["why"][0][:160])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=None, help="Agent E run_id (default: Worker E's recommended candidate)")
    a = ap.parse_args()
    part1(a.run)
    part2_3()
