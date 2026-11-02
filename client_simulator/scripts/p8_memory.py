"""TASK3 step 5: memory settings for the chosen writer. Second Ollama server on :11435 with KV q8_0 + flash attention.
python p8_memory.py MODEL STYLE   (STYLE ex5|ft)"""
import os
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import llm  # noqa: E402
from common import CACHE, RESULTS, SEED, load_json, read_jsonl, save_json  # noqa: E402
from p3_make_cards import all_cards  # noqa: E402
from p3_tests import RP_OPTS, _agent_replies, _real_examples  # noqa: E402
from p8_writers import gpu_used, messages  # noqa: E402

ALT = "http://127.0.0.1:11435"


def start_alt():
    env = dict(os.environ, OLLAMA_HOST="127.0.0.1:11435", OLLAMA_KV_CACHE_TYPE="q8_0", OLLAMA_FLASH_ATTENTION="1")
    p = subprocess.Popen(["ollama", "serve"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        try:
            requests.get(ALT + "/api/tags", timeout=2)
            return p
        except Exception:
            time.sleep(1)
    raise RuntimeError("alt server did not start")


def realism_run(model, style, pv, num_ctx):
    replies = _agent_replies()

    def one(ic):
        i, c = ic
        rng = random.Random(SEED + i)
        agent = rng.sample(replies[c["company"]], 2)
        e = _real_examples(c["company"], 5, SEED + i) if style == "ex5" else None
        h = []
        for k in range(3):
            r = llm.cached_chat("test2", model, pv, f"{c['id']}:t{k}", messages(c, h, style, e), num_ctx=num_ctx, **RP_OPTS)
            h.append({"role": "customer", "text": r["text"].strip()})
            if k < 2:
                h.append({"role": "agent", "text": agent[k]})
    with ThreadPoolExecutor(4) as x:
        list(x.map(one, enumerate(all_cards())))


def probe(model, style, num_ctx):
    card = all_cards()[0]
    ex = _real_examples(card["company"], 5, SEED) if style == "ex5" else None
    base = gpu_used()
    llm.chat(model, messages(card, [], style, ex), num_predict=5, num_ctx=num_ctx)
    t = [llm.chat(model, messages(card, [], style, ex), temperature=0.8, num_predict=120, seed=s, num_ctx=num_ctx) for s in range(5)]
    info = next((m for m in llm.ps() if m["name"] == model or m["model"] == model), {})
    return {"num_ctx": num_ctx, "vram_mib": round(info.get("size_vram", 0) / 2**20), "nvidia_smi_delta_mib": gpu_used() - base,
            "sec_per_message": round(sum(x["wall_s"] for x in t) / 5, 2)}


def main(model, style):
    pv0 = "ft1" if style == "ft" else "rp1-ex5"
    cond = "ft" if style == "ft" else "ex5"
    toks = [r["prompt_tokens"] for r in read_jsonl(CACHE / "test2.jsonl") if r["model"] == model and r["pv"] == f"rp1-{cond}" and r.get("prompt_tokens")]
    need = max(toks) + 120
    ctx = next(c for c in (512, 1024, 1536, 2048, 3072, 4096) if c >= need)
    res = {"longest_prompt_tokens": max(toks), "needed_with_output": need, "chosen_num_ctx": ctx}
    llm.unload_all()
    res["default_4096"] = probe(model, style, 4096)
    llm.unload_all()
    res[f"default_{ctx}"] = probe(model, style, ctx)
    realism_run(model, style, f"rp1-{cond}-ctx{ctx}", ctx)
    llm.unload_all()
    p = start_alt()
    try:
        llm.OLLAMA = ALT
        res[f"kvq8_fa_{ctx}"] = probe(model, style, ctx)
        realism_run(model, style, f"rp1-{cond}-ctx{ctx}-kvq8fa", ctx)
        llm.unload_all()
    finally:
        llm.OLLAMA = "http://127.0.0.1:11434"
        p.terminate()
    path = RESULTS / "p8_memory.json"
    allr = load_json(path) if path.exists() else {}
    allr[model] = res
    save_json(allr, path)
    print(res)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
