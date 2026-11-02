"""Phase 3: speed + memory probe per candidate (run before sizing the samples).
Usage: python p3_speed_memory.py model1 model2 ..."""
import subprocess
import sys
import time

from common import RESULTS, load_json, save_json
from llm import chat, ps, short, unload_all

PROMPT = [{"role": "system", "content": "You are role-playing a customer of an online shop writing to its support chat. "
                                        "Write only the customer's message, 1-3 sentences."},
          {"role": "user", "content": "Write your first message: your laptop order 4512 is 7 days late."}]
SCORE = [{"role": "system", "content": "You are the customer. Rate the support conversation."},
         {"role": "user", "content": "Agent: Your parcel is delayed, we will refund 20%.\nReturn JSON {\"score\": 1-5, \"comment\": \"...\"}"}]


def gpu_used_mib():
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout
    return int(out.strip().splitlines()[0])


def probe(model):
    unload_all()
    base = gpu_used_mib()
    t0 = time.time()
    chat(model, PROMPT, num_predict=5)  # load
    load_s = time.time() - t0
    msg = [chat(model, PROMPT, temperature=0.8, num_predict=120, seed=s) for s in range(5)]
    sc = [chat(model, SCORE, temperature=0, num_predict=80) for _ in range(2)]
    info = next((m for m in ps() if m["name"] == model or m["model"] == model), {})
    used = gpu_used_mib()
    r = {
        "model": short(model), "ollama_name": model, "load_s": round(load_s, 1),
        "sec_per_message": round(sum(m["wall_s"] for m in msg) / len(msg), 2),
        "tokens_per_s": round(sum(m["eval_count"] for m in msg) / max(sum(m["eval_s"] for m in msg), 1e-9), 1),
        "sec_per_score_call": round(sum(m["wall_s"] for m in sc) / len(sc), 2),
        "ollama_ps_size_mib": round(info.get("size", 0) / 2**20), "ollama_ps_vram_mib": round(info.get("size_vram", 0) / 2**20),
        "nvidia_smi_used_mib": used, "nvidia_smi_baseline_mib": base,
        "context": info.get("context_length"),
        "details": info.get("details", {}),
        "sample_message": msg[0]["text"][:300],
    }
    # co-load next to the agents' writer model (qwen2.5:3b): both must stay 100% in VRAM
    chat("qwen2.5:3b", PROMPT, num_predict=5)
    chat(model, PROMPT, num_predict=5)
    both = {m["name"]: (round(m["size"] / 2**20), round(m["size_vram"] / 2**20)) for m in ps()}
    r["coload_with_qwen2.5_3b"] = both
    r["coload_nvidia_smi_used_mib"] = gpu_used_mib()
    r["fits_next_to_qwen2.5_3b"] = len(both) == 2 and all(v[0] == v[1] for v in both.values())
    unload_all()
    return r


if __name__ == "__main__":
    path = RESULTS / "p3_speed_memory.json"
    res = load_json(path) if path.exists() else {}
    for m in sys.argv[1:]:
        res[short(m)] = probe(m)
        print(res[short(m)])
        save_json(res, path)
