"""Score agents A, B, C, D on test cases (P20; first built on the old branch feature/agents-cd, task P18).

Usage (from the repo root):
    python -m scripts.eval_agents --file tests/dev/agents_cases.json --model cv-qwen3-4b-instruct
    python -m scripts.eval_agents --file tests/dev/agents_cases.json --model callverse-m2-v3 --agent C
D4\\v3\\compare_models.py calls main() of this file unchanged (same arguments).

What one A / B / C case does:
  1. rebuild the test data in a throwaway database (the real one is never touched) and reset the clock;
  2. run the agent like the pipeline does (pipeline.run_agent_with_coordinator: T10 retry, Coordinator review and
     send-backs), with every agent model forced to --model on Ollama;
  3. compare what happened with the case: tools that must / must not be called, the proposal (or none), the
     Coordinator's outcome (if the case gives one), the handover (Agent A), the rule cited, no forbidden promise.
A D case: Agent D is rules (agents/agent_d.py), so the case sets some stock values, runs D's scan and checks the
shortages, the promotions proposed and that every promotion waits for the owner. The model only words the owner's
note: the run reports how many notes kept the model's wording ("model") or fell back to the template.

Why force the model here and not in config.yaml? This is a test bench: it must try any local model on all agents
without changing the demo's model chains. It replaces the model list of the agent roles for this process only
(llm.load_config), so NO Groq or Gemini call can happen.

"overrides" in a case change what the agent READS from a tool (e.g. "3 days late"). The Coordinator still re-reads
the real data, so for those cases only the agent's proposal is scored.

The held-out file (tests/data/...) is refused unless --heldout is given (final check only, CLAUDE.md rule 2).
"""

import argparse
import json
import re
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

from callverse import llm, pipeline, trace
from callverse.agents import base_agent
from callverse.agents.agent_a import AgentA
from callverse.agents.agent_b import AgentB
from callverse.agents.agent_c import AgentC
from callverse.agents.agent_d import AgentD, shortage_note
from callverse.config import load_config
from callverse.data import clock, db
from callverse.data.seed import seed
from callverse.tools import registry
from callverse.tools.shopnova_tools import get_order

AGENTS = {"A": AgentA, "B": AgentB, "C": AgentC, "D": AgentD}
AGENT_ROLES = ("agents", "agent_b", "agent_c", "agent_d")


# ---------- setup: one local model for every agent, tool overrides ----------

def force_local_model(model: str) -> None:
    """Every agent role uses only this Ollama model (temperature 0, seed 42) for the rest of this process."""
    real = llm.load_config

    def patched():
        cfg = real()
        entry = {"provider": "ollama", "model": model, "temperature": 0, "seed": 42}
        cfg["models"] = {**cfg["models"], **{role: [entry] for role in AGENT_ROLES}}
        return cfg
    llm.load_config = patched


def with_overrides(overrides: dict):
    """A run_tool that merges the case's fake fields into the real tool result (allow-list check still first)."""
    real_run_tool = registry.run_tool

    # **kwargs: extra keywords of the real run_tool (e.g. booking_type, added in T14f) pass through unchanged.
    def run_tool(agent, name, args, chat_fn=None, company="shopnova", **kwargs):
        result = real_run_tool(agent, name, args, chat_fn=chat_fn, company=company, **kwargs)
        if name in overrides and isinstance(result, dict) and "error" not in result:
            result = {**result, **overrides[name]}
        return result
    return run_tool


def set_stock(stock: dict) -> None:
    """Case data: {"product_id": stock, ...} written in the throwaway database."""
    with closing(db.connect()) as con:
        for pid, value in stock.items():
            con.execute("UPDATE products SET stock = ? WHERE id = ?", (int(value), int(pid)))
        con.commit()


# ---------- scoring ----------

def forbidden_promises(answer: str) -> list[str]:
    """Forbidden promise wordings (the SLM rule list in config.yaml) found in the answer."""
    text = (answer or "").lower()
    return [kw for pattern, kw in load_config()["slm"]["forbidden"] if re.search(pattern, text)]


def called(tools: list[str], need) -> bool:
    """need = a tool name, or a list of names where any one is enough."""
    return any(t in tools for t in need) if isinstance(need, list) else need in tools


def proposal_matches(proposal: dict | None, expect: dict) -> bool:
    if not proposal or proposal.get("action") != expect["action"] or proposal.get("rule_id") != expect["rule_id"]:
        return False
    params = proposal.get("params", {})
    for key, value in expect["params"].items():
        got = params.get(key)
        if isinstance(value, float):
            if not isinstance(got, (int, float)) or abs(got - value) > 0.01:
                return False
        elif got != value:
            return False
    return True


def score(case: dict, run: dict) -> list[str]:
    """Failure types for one A / B / C run (empty list = pass). One run can have several."""
    fails = []
    tools, expect = run["tools"], case["expect"]
    if case["must_call"] and not tools:
        fails.append("no_tool")
    elif any(not called(tools, need) for need in case["must_call"]):
        fails.append("missing_tool")
    if any(t in tools for t in case["must_not_call"]) or run["refused"]:
        fails.append("wrong_tool")
    proposals = run["proposals"]
    if expect["act"] == "propose":
        if not proposals:
            fails.append("text_only_claim" if run["claimed"] else "did_not_act")
        elif not any(proposal_matches(p, expect) for p in proposals):
            fails.append("bad_args")
        elif expect.get("outcome") and run.get("outcome") not in (
                expect["outcome"] if isinstance(expect["outcome"], list) else [expect["outcome"]]):
            fails.append("wrong_outcome")
    elif expect["act"] in ("none", "handover") and proposals:
        fails.append("acted_wrongly")
    if case["agent"] == "A" and run["handover"] != expect.get("handover"):
        fails.append("wrong_handover")
    if case.get("cite") and case["cite"] not in (run["answer"] or ""):
        fails.append("answer_rule")
    elif run["promises"]:
        fails.append("answer_rule")
    return fails


def score_d(case: dict, out: dict) -> list[str]:
    """Failure types for one D run."""
    fails, expect = [], case["expect"]
    short = {f["product_id"] for f in out["shortages"]}
    promoted = {p["params"]["product_id"] for p in out["proposals"]}
    if any(pid not in short for pid in expect.get("shortage", [])):
        fails.append("missed_shortage")
    if any(pid in short for pid in expect.get("not_shortage", [])):
        fails.append("false_shortage")
    if any(pid not in promoted for pid in expect.get("promote", [])):
        fails.append("missed_promotion")
    if any(pid in promoted for pid in expect.get("not_promote", [])):
        fails.append("acted_wrongly")
    if any(d["outcome"] != "owner_pending" for d in out["decisions"]):
        fails.append("not_owner_pending")      # a promotion must wait for the owner, always
    if "warn_order" in expect:
        note = shortage_note(get_order(expect["warn_order"]["order_id"]))
        if (note is not None) != expect["warn_order"]["warned"]:
            fails.append("wrong_warning")
    return fails


# ---------- one case ----------

def _fresh_db(case: dict, tmp: Path) -> Path:
    db.use_db(tmp / f"{case['id']}.db")
    seed()
    clock.reset()
    set_stock(case.get("stock", {}))
    return trace.start_run(f"eval_{case['id']}", trace_dir=tmp)


def run_case_d(case: dict, tmp: Path) -> dict:
    path = _fresh_db(case, tmp)
    start = time.time()
    try:
        out, error = AgentD().scan(), None
    except Exception as e:
        out, error = {"shortages": [], "overstock": [], "proposals": [], "decisions": []}, f"{type(e).__name__}: {e}"
    rows = [json.loads(x) for x in open(path, encoding="utf-8")]
    sources = [r["data"].get("note_source") for r in rows if r["step"] == "proposal" and r["actor"] == "agent_D"]
    run = {"id": case["id"], "agent": "D", "seconds": round(time.time() - start, 1), "error": error,
           "tools": [], "proposals": [{k: p.get(k) for k in ("action", "rule_id", "params")} for p in out["proposals"]],
           "outcome": sorted({d["outcome"] for d in out["decisions"]}) or None, "handover": None,
           "shortages": len(out["shortages"]), "overstock": len(out["overstock"]),
           "notes_by_model": sources.count("model"), "notes_by_template": sources.count("template"),
           "models": sorted({f"{r['data'].get('provider')}/{r['data'].get('model')}" for r in rows
                             if r["step"] == "llm_call"}),
           "answer": " | ".join(p.get("note") or "" for p in out["proposals"])}
    run["fails"] = (["crash"] if error else []) + score_d(case, out)
    run["pass"] = not run["fails"]
    return run


def run_case(case: dict, tmp: Path) -> dict:
    if case["agent"] == "D":
        return run_case_d(case, tmp)
    path = _fresh_db(case, tmp)
    base_agent.run_tool = with_overrides(case.get("overrides", {}))
    ticket = {"ticket_id": case["id"], "text": case["message"], "order_id": case["order_id"],
              "main_reason": case["reason"], "priority_label": "low", "continue_agent": case.get("continue_agent")}
    message = f"{case['message']}\n\n{pipeline.ticket_note(ticket)}"
    start = time.time()
    try:
        result, proposals, decision = pipeline.run_agent_with_coordinator(AGENTS[case["agent"]], message, ticket)
        error = None
    except Exception as e:  # a crash is a result too: report it, go on with the next case
        result, proposals, decision, error = {"answer": "", "tool_calls": []}, [], None, f"{type(e).__name__}: {e}"
    finally:
        base_agent.run_tool = registry.run_tool
    seconds = time.time() - start

    rows = [json.loads(x) for x in open(path, encoding="utf-8")]
    run = {
        "id": case["id"], "agent": case["agent"], "seconds": round(seconds, 1), "error": error,
        # tools of the agent itself (not of Agent A answering an ask_agent question)
        "tools": [r["data"]["tool"] for r in rows if r["step"] == "tool_call" and r["data"]["agent"] == case["agent"]],
        "refused": [r["data"]["tool"] for r in rows if r["step"] == "tool_refused"],
        "claimed": sum(r["step"] == "proposal_claim_retry" for r in rows),
        "retries": sum(r["step"] == "agent_retry" for r in rows),
        "send_backs": sum(r["step"] == "send_back_to_agent" for r in rows),
        "models": sorted({f"{r['data'].get('provider')}/{r['data'].get('model')}" for r in rows if r["step"] == "llm_call"}),
        "proposals": [{k: p.get(k) for k in ("action", "rule_id", "params")} for p in proposals],
        "outcome": decision["outcome"] if decision else None,
        "handover": result.get("handover"),
        "answer": result.get("answer", ""),
    }
    run["promises"] = forbidden_promises(run["answer"])
    run["fails"] = (["crash"] if error else []) + score(case, run)
    run["pass"] = not run["fails"]
    return run


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", required=True)
    ap.add_argument("--model", required=True, help="Ollama model used for every agent")
    ap.add_argument("--agent", choices=list(AGENTS) + ["all"], default="all")
    ap.add_argument("--heldout", action="store_true", help="allow a tests/data/ file (final check only)")
    ap.add_argument("--out", help="write all runs as JSON here (default: traces/eval_<model>.json)")
    args = ap.parse_args(argv)

    if "tests/data" in args.file.replace("\\", "/") and not args.heldout:
        print("Refused: held-out file. Use --heldout only for the final check (CLAUDE.md rule 2).")
        return 2
    cases = json.loads(Path(args.file).read_text(encoding="utf-8"))["cases"]
    cases = [c for c in cases if args.agent in ("all", c["agent"])]
    force_local_model(args.model)
    tmp = Path(tempfile.mkdtemp(prefix="callverse_eval_"))

    runs = []
    try:
        for case in cases:
            run = run_case(case, tmp)
            runs.append(run)
            mark = "PASS" if run["pass"] else "FAIL " + ",".join(run["fails"])
            print(f"{run['id']}  {run['seconds']:>5}s  {mark:40}  tools={run['tools']}  "
                  f"proposals={len(run['proposals'])} outcome={run['outcome']} handover={run['handover']}", flush=True)
    finally:
        db.use_db(db.DEFAULT_DB_PATH)

    print(f"\nModel {args.model}")
    for agent in sorted({r["agent"] for r in runs}):
        mine = [r for r in runs if r["agent"] == agent]
        print(f"  Agent {agent}: {sum(r['pass'] for r in mine)}/{len(mine)} pass, "
              f"avg {sum(r['seconds'] for r in mine) / len(mine):.1f}s")
    print(f"  Total: {sum(r['pass'] for r in runs)}/{len(runs)} pass")
    wrong = sum("acted_wrongly" in r["fails"] for r in runs)
    print(f"  Wrong proposals (acted when it should not): {wrong}")
    d_runs = [r for r in runs if r["agent"] == "D"]
    if d_runs:
        print(f"  Agent D owner notes worded by the model: {sum(r['notes_by_model'] for r in d_runs)}, "
              f"by the template: {sum(r['notes_by_template'] for r in d_runs)}")
    other = sorted({m for r in runs for m in r["models"] if not m.startswith("ollama/")})
    print(f"  Non-local model calls: {other or 'none'}")

    out = Path(args.out or f"traces/eval_{args.model.replace(':', '_').replace('/', '_')}.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(runs, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"  Runs written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
