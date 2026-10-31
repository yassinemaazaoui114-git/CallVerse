"""Run ONE candidate model on the validation data and save its vectors + measurements (T23, steps 2-4).

    python -m benchmarks.m3.embed_run bge-small        # one of common.MODELS, or "reranker"

Each model runs in its own process (benchmark.py starts them one by one), so "peak RAM" is that model's alone.
What it saves (out/t23/emb/<model>.pkl, git-ignored, and benchmarks/m3/results/models/<model>.json):
  - Intake: vectors of every company's examples (the index) and of every sentence of every val message.
    Each val message is embedded ALONE, like the live system does, and timed: split + embed + score + pick the
    best reason (top-k 3), after a warm-up. That is the latency per message.
  - Rule search: vectors of every rule ("title. text", as the system embeds them) and of every val question,
    without a prompt and with the model's documented prompts; the time to embed one question and rank the rules.
  - parameters, disk size of the downloaded files, load time, peak RAM, pinned revision.
Only VALIDATION files are read here. The locked test files are never opened.
"""

import json
import pickle
import resource
import sys
import time
from pathlib import Path

import numpy as np

from benchmarks.m3 import common

WARMUP = 10


def rss_mb() -> float:
    """Resident memory of this process now (Linux /proc), in MB."""
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    return float("nan")


def peak_rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024      # Linux: KB


def disk_mb(name: str, revision: str) -> float:
    """Size of the files actually downloaded for this revision (the Hugging Face cache snapshot)."""
    from huggingface_hub import snapshot_download
    folder = Path(snapshot_download(name, revision=revision, local_files_only=True))
    return round(sum(p.resolve().stat().st_size for p in folder.rglob("*") if p.is_file()) / 1e6, 1)


def run_model(key: str) -> None:
    spec = common.MODELS[key]
    import torch
    from sentence_transformers import SentenceTransformer
    base_rss = rss_mb()                                   # Python + torch + libraries, before the model

    t0 = time.perf_counter()
    try:
        model = SentenceTransformer(spec["name"], revision=spec["revision"], device="cpu")
    except Exception as error:            # e.g. a gated model without a Hugging Face login: skip it, say why
        write_meta(key, {"key": key, "name": spec["name"], "revision": spec["revision"],
                         "licence": spec["licence"], "skipped": f"{type(error).__name__}: {str(error)[:300]}"})
        return
    load_s = time.perf_counter() - t0

    def encode(texts, prompt=""):
        return model.encode(texts, prompt=prompt or None, normalize_embeddings=True, convert_to_numpy=True,
                            show_progress_bar=False)

    saved = {"intake": {}, "rag": {}}
    timings = {"intake_s": [], "rag_s": []}

    # Warm-up (first calls are slow: memory allocation, lazy init) - not timed.
    for text in ["hello, where is my order?"] * WARMUP:
        encode(common.split_sentences(text))

    # ---- Intake: index vectors, then each val message alone, timed like the live matcher (top-k 3).
    for company in common.COMPANIES:
        examples = common.reason_examples(company)
        reasons = list(examples)
        index = {r: encode(texts) for r, texts in examples.items()}
        messages = []
        for m in common.intake_val(company):
            start = time.perf_counter()
            sentences = common.split_sentences(m["text"])
            vectors = encode(sentences)
            scores = common.sentence_scores(vectors, index, 3)
            common.found_reasons(scores, reasons, 0.66)
            timings["intake_s"].append(time.perf_counter() - start)
            messages.append({"id": m["id"], "sentences": sentences, "vectors": vectors})
        saved["intake"][company] = {"index": index, "messages": messages}

    # ---- Rule search: rule vectors (plain and with the document prompt), question vectors (plain and prompted).
    questions = common.rag_val()
    for company in common.COMPANIES:
        texts = common.rule_texts(company)
        saved["rag"][company] = {"rules_plain": encode(texts), "rules_prompt": encode(texts, spec["doc_prompt"])}
    for variant, prompt in [("plain", ""), ("prompt", spec["query_prompt"])]:
        vectors = []
        for q in questions:
            rules = saved["rag"][q["company"]][f"rules_{variant}"]
            start = time.perf_counter()
            v = encode([q["question"]], prompt)[0]
            np.argsort(-(rules @ v))
            elapsed = time.perf_counter() - start
            if variant == "prompt":                       # the prompted query is the documented way: timed
                timings["rag_s"].append(elapsed)
            vectors.append(v)
        saved["rag"][f"questions_{variant}"] = np.array(vectors)

    out = common.WORK / "emb" / f"{key}.pkl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(pickle.dumps(saved))

    meta = {
        "key": key, "name": spec["name"], "revision": spec["revision"], "licence": spec["licence"],
        "parameters_m": round(sum(p.numel() for p in model.parameters()) / 1e6, 1),
        "dimensions": int(model.get_sentence_embedding_dimension()),
        "disk_mb": disk_mb(spec["name"], spec["revision"]), "load_s": round(load_s, 1),
        "rss_before_model_mb": round(base_rss, 0), "peak_rss_mb": round(peak_rss_mb(), 0),
        "intake_latency_ms": {"p50": common.percentile_ms(timings["intake_s"], 50),
                              "p95": common.percentile_ms(timings["intake_s"], 95), "n": len(timings["intake_s"])},
        "rag_dense_latency_ms": {"p50": common.percentile_ms(timings["rag_s"], 50),
                                 "p95": common.percentile_ms(timings["rag_s"], 95), "n": len(timings["rag_s"])},
        "rag_dense_latency_s_each": [round(s, 5) for s in timings["rag_s"]],
        "torch": torch.__version__, "threads": torch.get_num_threads(),
    }
    write_meta(key, meta)


def run_reranker() -> None:
    """bge-reranker-base: a score for every (question, rule) pair of the question's own company, and the time to
    rerank 10 rules for one question (what "hybrid + reranker" does on the hybrid top 10)."""
    import torch
    from sentence_transformers import CrossEncoder
    base_rss = rss_mb()
    t0 = time.perf_counter()
    model = CrossEncoder(RERANK["name"], revision=RERANK["revision"], device="cpu")
    load_s = time.perf_counter() - t0

    texts = {c: common.rule_texts(c) for c in common.COMPANIES}
    for _ in range(WARMUP):
        model.predict([("warm up", t) for t in texts["atlas"][:10]], show_progress_bar=False)

    scores, timings = [], []
    for q in common.rag_val():
        pairs = [(q["question"], t) for t in texts[q["company"]]]
        scores.append(model.predict(pairs, show_progress_bar=False).astype(float).tolist())
        ten = pairs[:10]                     # the same cost as any 10 rules: always 10 pairs (8 for ShopNova)
        start = time.perf_counter()
        model.predict(ten, show_progress_bar=False)
        timings.append(time.perf_counter() - start)

    out = common.WORK / "emb" / "reranker.pkl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(pickle.dumps({"scores": scores}))
    write_meta("reranker", {
        "key": "reranker", "name": RERANK["name"], "revision": RERANK["revision"], "licence": RERANK["licence"],
        "parameters_m": round(sum(p.numel() for p in model.model.parameters()) / 1e6, 1),
        "disk_mb": disk_mb(RERANK["name"], RERANK["revision"]), "load_s": round(load_s, 1),
        "rss_before_model_mb": round(base_rss, 0), "peak_rss_mb": round(peak_rss_mb(), 0),
        "rerank_latency_s_each": [round(s, 5) for s in timings],
        "rerank_latency_ms": {"p50": common.percentile_ms(timings, 50), "p95": common.percentile_ms(timings, 95)},
        "torch": torch.__version__, "threads": torch.get_num_threads(),
    })


RERANK = common.RERANKER


def write_meta(key: str, meta: dict) -> None:
    path = common.RESULTS / "models" / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in meta.items() if not k.endswith("_each")}))


if __name__ == "__main__":
    run_reranker() if sys.argv[1] == "reranker" else run_model(sys.argv[1])
