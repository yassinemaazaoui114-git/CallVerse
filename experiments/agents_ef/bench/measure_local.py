"""Measure the candidate tiny models on THIS machine (meant for the team's RTX 4050 laptop, Windows 11).

    python -m bench.measure_local --out results/local_measure [--skip-encoders] [--trim-vocab 60000]
Uses CUDA when available (peak VRAM = torch.cuda.max_memory_allocated), otherwise CPU. Records the hardware.
Latency / memory do not depend on trained weight values, so no checkpoint is needed:
  Agent E: v1 and Intake-aware (obs 43) networks of DQN, Dueling DDQN, PPO - decision latency batch 1.
  Agent F: TinyBERT-4L, multilingual-e5-small, paraphrase-multilingual-MiniLM-L12, mMiniLMv2-L6; each full and
           with the vocabulary trimmed to --trim-vocab tokens (what real_data/eval_f_v2.py does);
           inference batch 1 / 64 and one training step at the benchmark settings (length 128, batch 16),
           fp32 and (on CUDA) fp16 autocast.
Never downloads more than the 4 encoders (~1.4 GB total, cached by Hugging Face).
"""

import argparse
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from env.callcenter_env import CallCenterEnv  # noqa: E402
from env.factory import obs_dim  # noqa: E402
from rl.agents import make_agent  # noqa: E402

ENCODERS = {"tinybert_4l": "huawei-noah/TinyBERT_General_4L_312D",
            "e5_small": "intfloat/multilingual-e5-small",
            "mminilm_l12": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            "mminilmv2_l6": "nreimers/mMiniLMv2-L6-H384-distilled-from-XLMR-Large"}


def peak_ram_mb():
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    except ImportError:                       # Windows
        import psutil
        return psutil.Process().memory_info().peak_wset / 2**20


def sync(dev):
    if dev.type == "cuda":
        torch.cuda.synchronize()


def timed(fn, dev, n=100, warm=10):
    for _ in range(warm):
        fn()
    sync(dev)
    t = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        sync(dev)
        t.append(time.perf_counter() - t0)
    return {"p50_ms": round(1e3 * float(np.median(t)), 4), "p95_ms": round(1e3 * float(np.percentile(t, 95)), 4)}


def vram(dev, fn):
    if dev.type != "cuda":
        return None
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    fn()
    sync(dev)
    return round(torch.cuda.max_memory_allocated() / 2**20, 1)


def measure_encoder(name, dev, trim, seq=128):
    from transformers import AutoModel
    m = AutoModel.from_pretrained(name).float()          # some checkpoints ship in fp16
    if trim and m.get_input_embeddings().num_embeddings > trim:
        emb = m.get_input_embeddings()
        new = torch.nn.Embedding(trim, emb.embedding_dim, padding_idx=emb.padding_idx)
        new.weight.data = emb.weight.data[:trim].clone()
        m.set_input_embeddings(new)
    m.to(dev)
    vocab = m.get_input_embeddings().num_embeddings
    ids = lambda b: torch.randint(5, vocab, (b, seq), device=dev)
    att = lambda b: torch.ones(b, seq, dtype=torch.long, device=dev)
    i1, a1, i64, a64, i16, a16 = ids(1), att(1), ids(64), att(64), ids(16), att(16)
    head = torch.nn.Linear(m.config.hidden_size, 1).to(dev)
    r = {"params": sum(p.numel() for p in m.parameters()), "vocab": vocab}
    m.eval()
    with torch.no_grad():
        r["infer_batch1"] = timed(lambda: m(input_ids=i1, attention_mask=a1), dev)
        r["infer_batch64"] = timed(lambda: m(input_ids=i64, attention_mask=a64), dev, n=10, warm=2)
        r["vram_infer_batch64_mb"] = vram(dev, lambda: m(input_ids=i64, attention_mask=a64))
    m.train()
    opt = torch.optim.AdamW(list(m.parameters()) + list(head.parameters()), lr=1e-5)
    y = torch.zeros(16, device=dev)

    def step(amp=False):
        with torch.autocast(device_type=dev.type, dtype=torch.float16, enabled=amp):
            out = m(input_ids=i16, attention_mask=a16).last_hidden_state.mean(1)
            loss = torch.nn.functional.mse_loss(head(out).squeeze(-1).float(), y)
        opt.zero_grad()
        loss.backward()
        opt.step()
    r["train_step_batch16_fp32"] = timed(step, dev, n=5, warm=2)
    r["vram_train_batch16_fp32_mb"] = vram(dev, step)
    if dev.type == "cuda":
        r["train_step_batch16_fp16"] = timed(lambda: step(True), dev, n=5, warm=2)
        r["vram_train_batch16_fp16_mb"] = vram(dev, lambda: step(True))
    del m, opt
    if dev.type == "cuda":
        torch.cuda.empty_cache()
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/local_measure")
    ap.add_argument("--skip-encoders", action="store_true")
    ap.add_argument("--trim-vocab", type=int, default=60000, help="vocab size of the trimmed variants")
    ap.add_argument("--device", default=None, help="cuda / cpu (default: cuda if available)")
    a = ap.parse_args()
    dev = torch.device(a.device or ("cuda" if torch.cuda.is_available() else "cpu"))
    res = {"hardware": {"device": str(dev), "gpu": torch.cuda.get_device_name(0) if dev.type == "cuda" else None,
                        "gpu_total_mb": round(torch.cuda.get_device_properties(0).total_memory / 2**20)
                        if dev.type == "cuda" else None,
                        "platform": platform.platform(), "python": sys.version.split()[0], "torch": torch.__version__,
                        "cuda": torch.version.cuda, "cpu_threads": torch.get_num_threads()},
           "agent_e": {}, "agent_f": {}}
    for kind in ("v1", "intake"):
        obs = torch.zeros(1, obs_dim(kind), device=dev)
        for algo in ("dqn", "dueling_double_dqn", "ppo"):
            agent = make_agent(algo, obs_dim(kind), CallCenterEnv.n_actions, 0)
            net = agent.policy_module().to(dev).eval()
            fwd = (lambda: net(obs)) if algo != "ppo" else (lambda: net.pi(obs))
            with torch.no_grad():
                res["agent_e"][f"{kind}_{algo}"] = {"params": sum(p.numel() for p in net.parameters()),
                                                    **timed(fwd, dev, n=500), "vram_mb": vram(dev, fwd)}
    if not a.skip_encoders:
        for key, name in ENCODERS.items():
            for trim in (None, a.trim_vocab):
                if trim and key == "tinybert_4l":
                    continue
                tag = key + ("" if trim is None else f"_trim{trim // 1000}k")
                try:
                    res["agent_f"][tag] = measure_encoder(name, dev, trim)
                except Exception as e:                       # e.g. out of memory: record it, keep going
                    res["agent_f"][tag] = {"error": str(e)[:300]}
                print(tag, json.dumps(res["agent_f"][tag])[:200], flush=True)
    res["peak_ram_mb"] = round(peak_ram_mb(), 1)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"measure_v2_{dev.type}.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res["hardware"], indent=1))


if __name__ == "__main__":
    main()
