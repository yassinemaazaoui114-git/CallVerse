"""Run Test 1 + Test 2 for the fine-tuned writer through transformers on CPU (temp venv), turn by turn,
and store the outputs in the normal LLM cache (model "callverse-sim-writer", same keys as the Ollama writers)."""
import json
import random
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import CACHE, ROOT, SEED, read_jsonl  # noqa: E402
from p3_make_cards import all_cards, test1_cards  # noqa: E402
from p3_tests import T1_AGENT, _agent_replies  # noqa: E402
from p8_writers import messages  # noqa: E402

MODEL = "callverse-sim-writer"
PY = ROOT / "models" / "tmp" / "venv" / "Scripts" / "python.exe"
MDIR = ROOT / "kaggle_out" / "writer" / "merged"
TMP = ROOT / "models" / "tmp"


def cached(name):
    return {(r["model"], r["pv"], r["item"]): r for r in read_jsonl(CACHE / f"{name}.jsonl")}


def generate(jobs):
    """jobs: list of (cache_name, pv, item, messages). Skips cached ones; appends results to the cache."""
    todo = []
    for cname, pv, item, msgs in jobs:
        if (MODEL, pv, item) not in cached(cname):
            todo.append({"key": f"{cname}|{pv}|{item}", "messages": msgs, "seed": SEED})
    if not todo:
        return
    inp, outp = TMP / "ft_in.jsonl", TMP / "ft_out.jsonl"
    inp.write_text("\n".join(json.dumps(t, ensure_ascii=False) for t in todo), encoding="utf-8")
    outp.unlink(missing_ok=True)
    subprocess.run([str(PY), str(ROOT / "scripts" / "p8_hf_generate.py"), str(MDIR), str(inp), str(outp)], check=True)
    for r in read_jsonl(outp):
        cname, pv, item = r["key"].split("|")
        with (CACHE / f"{cname}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"model": MODEL, "pv": pv, "item": item, "text": r["text"], "wall_s": r["wall_s"],
                                "eval_count": r["eval_count"], "prompt_tokens": r["prompt_tokens"], "error": None,
                                "backend": "transformers CPU fp32"}, ensure_ascii=False) + "\n")


def main():
    cards = all_cards()
    replies = _agent_replies()
    agents = {c["id"]: random.Random(SEED + i).sample(replies[c["company"]], 2) for i, c in enumerate(cards)}
    t1 = test1_cards()
    for turn in range(3):
        jobs = []
        c2 = cached("test2")
        for c in cards:
            h = []
            for k in range(turn):
                h.append({"role": "customer", "text": c2[(MODEL, "rp1-ft", f"{c['id']}:t{k}")]["text"].strip()})
                h.append({"role": "agent", "text": agents[c["id"]][k]})
            jobs.append(("test2", "rp1-ft", f"{c['id']}:t{turn}", messages(c, h, "ft", None)))
        if turn == 0:
            jobs += [("test1", "ft1", f"{c['id']}:first", messages(c, [], "ft", None)) for c in t1]
        if turn == 1:
            c1 = cached("test1")
            jobs += [("test1", "ft1", f"{c['id']}:reply", messages(c, [{"role": "customer", "text": c1[(MODEL, 'ft1', c['id'] + ':first')]['text'].strip()},
                                                                       {"role": "agent", "text": T1_AGENT}], "ft", None)) for c in t1]
        generate(jobs)
        print("turn", turn, "done", flush=True)


if __name__ == "__main__":
    main()
