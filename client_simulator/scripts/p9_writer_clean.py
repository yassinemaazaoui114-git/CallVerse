"""Writer clean-up check: gemma3:1b through the kit's simulate_turn (clean-up rules on) on the same 30 cards x 3 turns
and the 3 Test-1 cards, same real examples and agent turns as before. Stored in the LLM cache as pv rp1-ex5-clean."""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import CACHE, RESULTS, SEED, read_jsonl, save_json  # noqa: E402
from p3_make_cards import all_cards, test1_cards  # noqa: E402
from p3_tests import T1_AGENT, _agent_replies, _real_examples  # noqa: E402
import simulator.core as core  # noqa: E402

MODEL, PV = "gemma3:1b", sys.argv[1] if len(sys.argv) > 1 else "rp1-ex5-clean"


def put(cache, item, text):
    with (CACHE / f"{cache}.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"model": MODEL, "pv": PV, "item": item, "text": text, "error": None}, ensure_ascii=False) + "\n")


def main():
    assert core.config()["model"] == MODEL
    done = {(r["model"], r["pv"], r["item"]) for r in read_jsonl(CACHE / "test2.jsonl")}
    replies = _agent_replies()
    core._OPENERS.clear()
    for i, c in enumerate(all_cards()):
        agent = random.Random(SEED + i).sample(replies[c["company"]], 2)
        ex = _real_examples(c["company"], 5, SEED + i)
        h = []
        for k in range(3):
            item = f"{c['id']}:t{k}"
            if (MODEL, PV, item) in done:
                break
            out = core.simulate_turn(c, h, examples=ex, seed=SEED)
            put("test2", item, out)
            h.append({"role": "customer", "text": out})
            if k < 2:
                h.append({"role": "agent", "text": agent[k]})
    for c in test1_cards():
        ex = _real_examples(c["company"], 5, SEED)
        f = core.simulate_turn(c, [], examples=ex, seed=SEED)
        r = core.simulate_turn(c, [{"role": "customer", "text": f}, {"role": "agent", "text": T1_AGENT}], examples=ex, seed=SEED)
        put("test1", f"{c['id']}:first", f)
        put("test1", f"{c['id']}:reply", r)
    save_json(dict(core.STATS), RESULTS / f"p9_writer_clean_stats_{PV}.json")
    print(core.STATS)


if __name__ == "__main__":
    main()
