"""F4 — benign-mutation stress test of the M7 v4 checks, on the DEV corpus only.

    python -m v4.f.m7_stress --corpus <m7_corpus> --work <scratch folder>

The scripted corpus is "too clean": real LLM agents and real logs differ in harmless ways. Each mutation below
changes a trace WITHOUT changing what happened, so every flag must stay the same. Any flag that appears or
disappears is a robustness failure (a future false positive or a miss).
  numeric_strings   the agent writes numbers as strings in facts_used ("8", "59.9"), as LLM JSON often does
  float_noise       59.9 -> 59.9000000001 in the claimed amounts (float printing)
  noise_lines       unrelated trace lines (llm_call, debug) inserted after every tool call
  garbled_line      one non-JSON line inserted in the middle of the trace (a partly written log line)
  batch_file        5 conversations written into ONE trace file (a queue batch), as the prototype allows
Output: v4/f/results/m7_stress_dev.json (per mutation: conversations whose flags changed, with the difference).
"""

import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from v4.f.m7.conversations_v4 import parse_trace_v4  # noqa: E402
from v4.f.m7.quality_v4 import review_v4, verify_refs  # noqa: E402


def stringify(d):
    return {k: (str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v) for k, v in d.items()}


def noisy(d):
    return {k: (v + 1e-10 if isinstance(v, float) else v) for k, v in d.items()}


def mutate_lines(lines, kind):
    out = []
    for i, raw in enumerate(lines):
        rec = json.loads(raw)
        if kind in ("numeric_strings", "float_noise"):
            f = stringify if kind == "numeric_strings" else noisy
            if rec["step"] == "proposal" and isinstance(rec["data"].get("facts_used"), dict):
                rec["data"]["facts_used"] = f(rec["data"]["facts_used"])
            if rec["step"] == "coordinator_check" and rec["data"].get("check") == "facts_from_data":
                det = rec["data"].get("detail", "")
                if "agent claimed:" in det:
                    import ast
                    try:
                        claimed = ast.literal_eval(det.split("agent claimed:", 1)[1].strip())
                        if isinstance(claimed, dict):
                            rec["data"]["detail"] = f"agent claimed: {f(claimed)}"
                    except (ValueError, SyntaxError):
                        pass
        out.append(json.dumps(rec, ensure_ascii=False))
        if kind == "noise_lines" and rec["step"] == "tool_call":
            out.append(json.dumps({**rec, "step": "llm_call", "actor": "llm", "data": {"model": "x", "tokens": 12}}))
            out.append(json.dumps({**rec, "step": "debug", "actor": "dev", "data": {"note": "noise"}}))
        if kind == "garbled_line" and i == len(lines) // 2:
            out.append('{"time": "2026-10-09T09:00:01", "run_id": "x", "step": "tool_ca')
    return out


def flags_of(conv):
    r = review_v4(conv)
    return r, Counter((f["code"], f["severity"]) for f in r["flags"])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--work", required=True)
    a = ap.parse_args(argv)
    src = sorted((Path(a.corpus) / "dev" / "traces").glob("*.jsonl"))
    work = Path(a.work)
    if work.exists():
        shutil.rmtree(work)
    base = {}
    for p in src:
        [c] = parse_trace_v4(p)
        base[p.stem] = flags_of(c)[1]
    rep = {"n_conversations": len(src), "split": "dev", "mutations": {}}
    for kind in ("numeric_strings", "float_noise", "noise_lines", "garbled_line"):
        d = work / kind
        d.mkdir(parents=True)
        changed, bad_refs, n_refs = [], 0, 0
        for p in src:
            q = d / p.name
            q.write_text("\n".join(mutate_lines(p.read_text(encoding="utf-8").splitlines(), kind)) + "\n",
                         encoding="utf-8")
            [c] = parse_trace_v4(q)
            r, fl = flags_of(c)
            refs = verify_refs(c, r)
            n_refs += len(refs)
            bad_refs += sum(not x["ok"] for x in refs)
            if fl != base[p.stem]:
                changed.append({"conversation": p.stem, "added": sorted((fl - base[p.stem]).elements()),
                                "removed": sorted((base[p.stem] - fl).elements())})
        rep["mutations"][kind] = {"n_changed": len(changed), "changed": changed[:15], "n_refs": n_refs,
                                  "refs_not_ok": bad_refs}
        print(kind, len(changed), "changed;", bad_refs, "bad refs of", n_refs, flush=True)
    # batch: groups of 5 files concatenated into one
    d = work / "batch_file"
    d.mkdir(parents=True)
    changed, n_refs, bad_refs = [], 0, 0
    for g in range(0, len(src), 5):
        group = src[g:g + 5]
        q = d / f"batch_{g // 5:03d}.jsonl"
        q.write_text("".join(p.read_text(encoding="utf-8") for p in group), encoding="utf-8")
        convs = parse_trace_v4(q)
        if len(convs) != len(group):
            changed.append({"batch": q.name, "problem": f"{len(convs)} conversations parsed for {len(group)}"})
            continue
        for p, c in zip(group, convs):
            r, fl = flags_of(c)
            refs = verify_refs(c, r)
            n_refs += len(refs)
            bad_refs += sum(not x["ok"] for x in refs)
            if fl != base[p.stem]:
                changed.append({"conversation": p.stem, "added": sorted((fl - base[p.stem]).elements()),
                                "removed": sorted((base[p.stem] - fl).elements())})
    rep["mutations"]["batch_file"] = {"n_changed": len(changed), "changed": changed[:15], "n_refs": n_refs,
                                      "refs_not_ok": bad_refs}
    print("batch_file", len(changed), "changed;", bad_refs, "bad refs of", n_refs)
    (HERE / "results" / "m7_stress_dev.json").write_text(json.dumps(rep, indent=1, default=str))


if __name__ == "__main__":
    main()
