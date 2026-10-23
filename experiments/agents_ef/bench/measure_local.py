"""Measure the selected tiny models on THIS machine (meant for the team's RTX 4050 laptop, Windows 11).

    python -m bench.measure_local --out results/local_measure
Uses CUDA when available (peak VRAM = torch.cuda.max_memory_allocated), otherwise CPU. Records the hardware.
Measures: Agent E policies (decision latency batch 1, 10k decisions/s), Agent F encoders (TinyBERT-4L,
DistilBERT, bge-small: inference latency batch 1 / 64, one training step batch 32), the shared E+F model.
Model weights for the encoders come from Hugging Face (same architecture as benchmarked; VRAM and latency do
not depend on the fine-tuned values). Nothing here changes any result file except the output folder.
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
from rl.agents import make_agent  # noqa: E402


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


def timed(fn, dev, n=200, warm=20):
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
    return round(torch.cuda.max_memory_allocated() / 2**20, 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/local_measure")
    ap.add_argument("--runs", default="results/runs")
    ap.add_argument("--skip-encoders", action="store_true")
    a = ap.parse_args()
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    res = {"hardware": {"device": str(dev), "gpu": torch.cuda.get_device_name(0) if dev.type == "cuda" else None,
                        "platform": platform.platform(), "python": sys.version.split()[0], "torch": torch.__version__,
                        "cpu_threads": torch.get_num_threads()}, "agent_e": {}, "agent_f": {}}
    env = CallCenterEnv()
    obs = torch.as_tensor(env.reset(seed=0, scenario="normal")[0]).unsqueeze(0).to(dev)
    for algo in ("dqn", "dueling_double_dqn", "ppo"):
        run = Path(a.runs) / f"{algo}_balanced_h64x64_s0"
        if not (run / "best.pt").exists():
            continue
        agent = make_agent(algo, env.obs_dim, env.n_actions, 0)
        agent.load_state_dict(torch.load(run / "best.pt", map_location="cpu", weights_only=False))
        net = agent.policy_module().to(dev).eval()
        fwd = (lambda: net(obs)) if algo != "ppo" else (lambda: net.pi(obs))
        with torch.no_grad():
            res["agent_e"][algo] = {"params": sum(p.numel() for p in net.parameters()), **timed(fwd, dev),
                                    "vram_mb": vram(dev, fwd)}
    if not a.skip_encoders:
        from transformers import AutoModel, AutoTokenizer
        text = ["Where is my order 4512? || I've taken care of it. || Thanks."]
        for key, name in (("tinybert_4l", "huawei-noah/TinyBERT_General_4L_312D"),
                          ("bge_small", "BAAI/bge-small-en-v1.5"), ("distilbert", "distilbert-base-uncased")):
            tok, m = AutoTokenizer.from_pretrained(name), AutoModel.from_pretrained(name).to(dev)
            b1 = {k: v.to(dev) for k, v in tok(text, return_tensors="pt").items()}
            b64 = {k: v.to(dev) for k, v in tok(text * 64, return_tensors="pt", padding=True).items()}
            m.eval()
            with torch.no_grad():
                r = {"params": sum(p.numel() for p in m.parameters()),
                     "infer_batch1": timed(lambda: m(**b1), dev), "infer_batch64": timed(lambda: m(**b64), dev, n=30),
                     "vram_infer_batch64_mb": vram(dev, lambda: m(**b64))}
            m.train()
            opt = torch.optim.AdamW(m.parameters(), lr=1e-5)
            b32 = {k: v.to(dev) for k, v in tok(text * 32, return_tensors="pt", padding=True).items()}

            def train_step():
                loss = m(**b32).last_hidden_state.mean()
                opt.zero_grad()
                loss.backward()
                opt.step()
            r["train_step_batch32"] = timed(train_step, dev, n=10, warm=2)
            r["vram_train_batch32_mb"] = vram(dev, train_step)
            res["agent_f"][key] = r
            del m, opt
            if dev.type == "cuda":
                torch.cuda.empty_cache()
    res["peak_ram_mb"] = round(peak_ram_mb(), 1)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"measure_{dev.type}.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
