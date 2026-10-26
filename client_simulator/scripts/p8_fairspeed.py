"""Same prompt, both server settings: s/message, VRAM alone and next to qwen2.5:3b. python p8_fairspeed.py MODEL[@style] ..."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import llm  # noqa: E402
from common import RESULTS, SEED, load_json, save_json  # noqa: E402
from p3_make_cards import all_cards  # noqa: E402
from p3_tests import _real_examples  # noqa: E402
from p8_memory import ALT, start_alt  # noqa: E402
from p8_writers import gpu_used, messages  # noqa: E402


def measure(model, style, ctx):
    card = all_cards()[0]
    ex = _real_examples(card["company"], 5, SEED) if style == "ex5" else None
    llm.unload_all()
    base = gpu_used()
    llm.chat(model, messages(card, [], style, ex), num_predict=5, num_ctx=ctx)
    t = [llm.chat(model, messages(card, [], style, ex), temperature=0.8, num_predict=120, seed=s, num_ctx=ctx) for s in range(5)]
    alone = next((m for m in llm.ps() if m["name"] == model), {})
    r = {"sec_per_message": round(sum(x["wall_s"] for x in t) / 5, 2),
         "tokens_per_message": round(sum(x["eval_count"] for x in t) / 5, 1),
         "vram_alone_mib": round(alone.get("size_vram", 0) / 2**20), "nvidia_smi_alone_mib": gpu_used() - base}
    llm.chat("qwen2.5:3b", [{"role": "user", "content": "hi"}], num_predict=3, num_ctx=4096)
    both = {m["name"]: (round(m["size"] / 2**20), round(m["size_vram"] / 2**20)) for m in llm.ps()}
    r["with_qwen2.5_3b"] = both
    r["nvidia_smi_with_qwen_mib"] = gpu_used() - base
    r["fits_with_qwen"] = len(both) == 2 and all(a == b for a, b in both.values())
    llm.unload_all()
    return r


if __name__ == "__main__":
    path = RESULTS / "p8_fairspeed.json"
    res = load_json(path) if path.exists() else {}
    for arg in sys.argv[1:]:
        model, _, style = arg.partition("@")
        style = style or "ex5"
        res[f"{model} | default server, num_ctx 4096"] = measure(model, style, 4096)
    p = start_alt()
    try:
        llm.OLLAMA = ALT
        for arg in sys.argv[1:]:
            model, _, style = arg.partition("@")
            style = style or "ex5"
            res[f"{model} | KV q8_0 + flash attention, num_ctx 1024"] = measure(model, style, 1024)
    finally:
        llm.OLLAMA = "http://127.0.0.1:11434"
        p.terminate()
    save_json(res, path)
    for k, v in res.items():
        print(k, v["sec_per_message"], v["tokens_per_message"], v["vram_alone_mib"], v["nvidia_smi_with_qwen_mib"], v["fits_with_qwen"])
