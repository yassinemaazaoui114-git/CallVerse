"""T25 step 2: score today's bge-small and the two fine-tuned models on the VALIDATION sets, on the demo PC.

    python -m benchmarks.m3.t25_score bge-small        # one model per process, so peak RAM is that model's alone
    python -m benchmarks.m3.t25_score bge-small-ft
    python -m benchmarks.m3.t25_score bge-base-ft
    python -m benchmarks.m3.t25_score table            # prints the 3-row table from the saved files

It reuses the T23 code: the same top-k / threshold grid and tie rule (benchmark.intake_model), the same measures
(common.*, benchmark.measure_rag). Speed and peak RAM are measured like pc_check.py (Windows). The locked test
files are never opened here. Results: benchmarks/m3/results/t25/<model>.json.
"""

import json
import sys
import time

import numpy as np

from benchmarks.m3 import benchmark, common
from benchmarks.m3.pc_check import peak_ram_mb
from callverse import companies

WARMUP = 10
OUT = common.RESULTS / "t25"
QUERY_PROMPT = "Represent this sentence for searching relevant passages: "      # same text as kb/search.py
# model key -> (what SentenceTransformer loads, revision or None)
MODELS = {
    "bge-small": ("BAAI/bge-small-en-v1.5", "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"),
    "bge-small-ft": ("models/bge-small-callverse-ft", None),
    "bge-base-ft": ("models/bge-base-callverse-ft", None),
}


def run(key: str) -> None:
    from sentence_transformers import SentenceTransformer
    name, revision = MODELS[key]
    t0 = time.perf_counter()
    model = SentenceTransformer(name, device="cpu", **({"revision": revision} if revision else {}))
    load_s = time.perf_counter() - t0

    def encode(texts, prompt=""):
        return model.encode([prompt + t for t in texts], normalize_embeddings=True, convert_to_numpy=True,
                            show_progress_bar=False)

    for _ in range(WARMUP):
        encode(common.split_sentences("hello, where is my order?"))

    # ---- Intake: embed once, tune top-k + thresholds with the T23 grid and rule.
    emb = {"intake": {}}
    for company in common.COMPANIES:
        index = {r: encode(texts) for r, texts in common.reason_examples(company).items()}
        messages = [{"vectors": encode(common.split_sentences(m["text"]))} for m in common.intake_val(company)]
        emb["intake"][company] = {"index": index, "messages": messages}
    intake = benchmark.intake_model(key, emb)
    top_k = intake["top_k"]

    # ---- Intake speed: each val message alone with the tuned settings (split + embed + score + pick).
    times = []
    for company in common.COMPANIES:
        index = emb["intake"][company]["index"]
        reasons = list(index)
        th = intake["companies"][company]["threshold"]
        for m in common.intake_val(company):
            start = time.perf_counter()
            vectors = encode(common.split_sentences(m["text"]))
            common.found_reasons(common.sentence_scores(vectors, index, top_k), reasons, th)
            times.append(time.perf_counter() - start)

    # ---- Rule search, with and without the BGE query prompt (rules are embedded plain, as the system does).
    questions = common.rag_val()
    rules = {c: [r["id"] for r in common.rules(c)] for c in common.COMPANIES}
    rule_vectors = {c: encode(common.rule_texts(c)) for c in common.COMPANIES}
    search = {}
    for variant, prompt in [("no_prompt", ""), ("prompt", QUERY_PROMPT)]:
        rankings, tops, secs = [], [], []
        for q in questions:
            start = time.perf_counter()
            scores = rule_vectors[q["company"]] @ encode([q["question"]], prompt)[0]
            order = list(np.argsort(-scores, kind="stable"))
            secs.append(time.perf_counter() - start)
            rankings.append([rules[q["company"]][j] for j in order])
            tops.append(float(scores[order[0]]))
        res = benchmark.measure_rag(questions, rankings, tops)
        search[variant] = {"all": res["all"], "shopnova": res["shopnova"], "atlas": res["atlas"],
                           "misses": res["misses"], "no_rule_separable": res["no_rule_separable"],
                           "latency_ms": {"p50": common.percentile_ms(secs, 50), "p95": common.percentile_ms(secs, 95)}}

    result = {"model": key, "loaded": name, "load_s": round(load_s, 1), "intake": intake,
              "intake_latency_ms": {"p50": common.percentile_ms(times, 50), "p95": common.percentile_ms(times, 95),
                                    "n": len(times)},
              "search": search, "peak_ram_mb": round(peak_ram_mb())}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{key}.json").write_text(json.dumps(result, indent=1, default=float) + "\n", encoding="utf-8")
    print(key, "done")


def table() -> None:
    print("model | top-k thr S/A | macroF1 S/A/avg | critical S/A | needsLLM S/A | Intake p50/p95 | RAM")
    for key in MODELS:
        r = json.loads((OUT / f"{key}.json").read_text(encoding="utf-8"))
        i = r["intake"]
        s, a = i["companies"]["shopnova"], i["companies"]["atlas"]
        print(f"{key} | k{i['top_k']} {s['threshold']}/{a['threshold']} | {s['macro_f1']:.3f}/{a['macro_f1']:.3f}/"
              f"{i['avg_macro_f1']:.3f} | {s['critical_errors']}/{a['critical_errors']} | "
              f"{s['needs_llm_rate']:.3f}/{a['needs_llm_rate']:.3f} | {r['intake_latency_ms']['p50']}/"
              f"{r['intake_latency_ms']['p95']} ms | {r['peak_ram_mb']} MB")
        for v, x in r["search"].items():
            print(f"    search {v:9s} top1 {x['all']['top1']:.3f} top2 {x['all']['top2']:.3f} ({x['all']['top2_count']}/30) "
                  f"MRR {x['all']['mrr']:.3f} | p50/p95 {x['latency_ms']['p50']}/{x['latency_ms']['p95']} ms | "
                  f"no-rule separable {x['no_rule_separable']}/5 | misses {[m['id'] for m in x['misses']]}")


if __name__ == "__main__":
    table() if sys.argv[1] == "table" else run(sys.argv[1])
