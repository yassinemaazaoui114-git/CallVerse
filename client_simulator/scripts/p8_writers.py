"""TASK3 step 2/4: small writers. One model loaded at a time (unloaded after each model).
python p8_writers.py MODEL[:style] ...   style = ex5 (prompted, 5 real examples; default) or ft (fine-tuned, compact card)"""
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import RESULTS, SEED, load_json, save_json  # noqa: E402
from llm import cached_chat, chat, ps, unload_all  # noqa: E402
from p3_make_cards import all_cards, test1_cards  # noqa: E402
from p3_tests import RP_OPTS, T1_AGENT, _agent_replies, _real_examples  # noqa: E402
from simulator.prompts import compact_roleplay_system, roleplay_messages  # noqa: E402


def messages(card, hist, style, ex):
    if style == "ft":
        m = roleplay_messages(card, hist)
        m[0] = {"role": "system", "content": compact_roleplay_system(card)}
        return m
    return roleplay_messages(card, hist, ex)


def gpu_used():
    return int(subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                              capture_output=True, text=True).stdout.split()[0])


def run(model, style):
    pv = "ft1" if style == "ft" else "rp1-ex5"
    unload_all()
    base = gpu_used()
    card = all_cards()[0]
    ex = _real_examples(card["company"], 5, SEED) if style == "ex5" else None
    chat(model, messages(card, [], style, ex), num_predict=5)
    t = [chat(model, messages(card, [], style, ex), temperature=0.8, num_predict=120, seed=s) for s in range(5)]
    info = next((m for m in ps() if m["name"] == model or m["model"] == model), {})
    probe = {"sec_per_message": round(sum(x["wall_s"] for x in t) / 5, 2), "vram_mib": round(info.get("size_vram", 0) / 2**20),
             "size_mib": round(info.get("size", 0) / 2**20), "nvidia_smi_mib": gpu_used() - base,
             "details": info.get("details", {}), "context": info.get("context_length")}
    # Test 1 (quick role-play) with 5 real examples (ex5) or the fine-tuned format (ft)
    for c in test1_cards():
        e = _real_examples(c["company"], 5, SEED) if style == "ex5" else None
        f = cached_chat("test1", model, pv, f"{c['id']}:first", messages(c, [], style, e), **RP_OPTS)
        h = [{"role": "customer", "text": f["text"].strip()}, {"role": "agent", "text": T1_AGENT}]
        cached_chat("test1", model, pv, f"{c['id']}:reply", messages(c, h, style, e), **RP_OPTS)
    # Test 2 (realism): 30 cards x 3 turns, agent turns = real brand replies (same as Phase 3)
    replies = _agent_replies()
    cond = "ft" if style == "ft" else "ex5"

    def one(ic):
        i, c = ic
        rng = random.Random(SEED + i)
        agent = rng.sample(replies[c["company"]], 2)
        e = _real_examples(c["company"], 5, SEED + i) if style == "ex5" else None
        h = []
        for k in range(3):
            r = cached_chat("test2", model, f"rp1-{cond}", f"{c['id']}:t{k}", messages(c, h, style, e), **RP_OPTS)
            h.append({"role": "customer", "text": r["text"].strip()})
            if k < 2:
                h.append({"role": "agent", "text": agent[k]})
    with ThreadPoolExecutor(4) as x:
        list(x.map(one, enumerate(all_cards())))
    unload_all()
    return probe


if __name__ == "__main__":
    path = RESULTS / "p8_writers_probe.json"
    res = load_json(path) if path.exists() else {}
    for arg in sys.argv[1:]:
        model, _, style = arg.partition("@")
        t0 = time.time()
        res[model] = {**run(model, style or "ex5"), "style": style or "ex5", "seconds": round(time.time() - t0)}
        save_json(res, path)
        print(model, res[model]["sec_per_message"], res[model]["vram_mib"], res[model]["seconds"], flush=True)
