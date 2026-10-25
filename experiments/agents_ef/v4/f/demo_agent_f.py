"""Offline demo of Agent F (M7 v4): read closed conversations, review them, score them with validity, write the report.

    cd experiments/agents_ef
    python -m v4.f.demo_agent_f [--traces v4/f/demo_traces] [--scorer tfidf:<f_v3>/ckpt/tfidf_ridge_tail256]

No API, no LLM, CPU only. Without --scorer (or if the checkpoint folder is missing) no satisfaction score is given,
and the demo says so: everything else (quality review, rule audit, F -> E decision) still runs.
Output: one summary line per conversation on screen, and v4/f/results/demo/owner_report.md + results.jsonl.
"""

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from v4.f.agent_f import AgentF, strip_private  # noqa: E402

DEFAULT_SCORER = Path("/tmp/claude-0/-home-user/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/f_v3/ckpt/"
                      "tfidf_ridge_tail256")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", default=str(HERE / "demo_traces"))
    ap.add_argument("--scorer", default=f"tfidf:{DEFAULT_SCORER}" if DEFAULT_SCORER.exists() else "none")
    ap.add_argument("--out", default=str(HERE / "results" / "demo"))
    a = ap.parse_args(argv)
    t0 = time.perf_counter()
    f = AgentF.load({"scorer": a.scorer})
    results = f.process_folder(a.traces)
    print(f"Agent F loaded ({a.scorer}) and processed {len(results)} closed conversations in "
          f"{time.perf_counter() - t0:.2f} s\n")
    for r in results:
        v = r["satisfaction_validity"]
        sat = "no score" if r["predicted_satisfaction"] is None else f"{r['predicted_satisfaction']:.2f}"
        flags = ", ".join(f"{x['code']}({x['severity']})" for x in r["quality_flags"]) or "none"
        print(f"- {r['conversation_id']}: outcome {r['outcome']}, grade {r['grade']}; satisfaction {sat} "
              f"[{v['language']}, {v['validity']}]; flags: {flags}; evidence refs ok "
              f"{r['evidence_check']['n_ok']}/{r['evidence_check']['n_refs']}; E reward eligible: "
              f"{r['e_reward_eligible']['eligible']}")
    rep = f.owner_report(results, corpus_label=f"demo traces ({a.traces})")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "owner_report.md").write_text(rep["markdown"])
    with open(out / "results.jsonl", "w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(strip_private(r), ensure_ascii=False, default=str) + "\n")
    print(f"\ne_reward_allowed = {rep['json']['e_feedback']['e_reward_allowed']}: "
          + "; ".join(rep["json"]["e_feedback"]["reasons"]))
    print(f"Owner report: {out / 'owner_report.md'}")


if __name__ == "__main__":
    main()
