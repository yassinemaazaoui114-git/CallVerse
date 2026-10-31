"""Score every candidate on the VALIDATION sets and apply the choosing rule fixed in advance (T23, steps 3-5).

    python -m benchmarks.m3.benchmark          # needs out/t23/emb/*.pkl from embed_run.py (one per model)

No model is loaded here: it works on the saved vectors, so trying 51 thresholds x 3 top-k is instant.
Writes benchmarks/m3/results/intake_val.json, rag_val.json and choice.json, and prints the tables.

Intake (step 3): for each model, top-k (1, 3, 5, one value for both companies, like config.yaml) and a threshold
per company (0.40-0.90, step 0.01) are tuned on val for the best macro-F1 averaged over the two companies.
When several thresholds give the same best macro-F1, the middle one is taken (safer than an edge).
Baselines: TF-IDF nearest examples (same matcher; its grid starts at 0.00 because TF-IDF scores are low) and
"always the most frequent reason". Today's setting (bge-small, top-k 3, 0.66 / 0.68) is scored as it is.

Rule search (step 4), each question in its own company's rules: dense (each model, without a prompt = how the
system does it today, and with the model's documented prompts), BM25, hybrid (dense + BM25, reciprocal rank
fusion k = 60), hybrid + reranker (bge-reranker-base re-orders the hybrid top 10).
"""

import json
import pickle
import time

import numpy as np

from benchmarks.m3 import common
from callverse import companies

TFIDF_THRESHOLDS = [round(i / 100, 2) for i in range(91)]       # 0.00 .. 0.90


def load(key: str) -> dict | None:
    path = common.WORK / "emb" / f"{key}.pkl"
    return pickle.loads(path.read_bytes()) if path.exists() else None


def meta(key: str) -> dict | None:
    path = common.RESULTS / "models" / f"{key}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# ================================================================ Intake

def company_info(company: str) -> tuple[list[str], list[str], list[str]]:
    """(reasons, precedence order, true labels of the val set)."""
    cfg = companies.get(company)
    return cfg["reasons"], cfg["main_reason_order"], [m["reason"] for m in common.intake_val(company)]


def score_matrices(index: dict, message_vectors: list[np.ndarray], top_k: int) -> list[np.ndarray]:
    return [common.sentence_scores(v, index, top_k) for v in message_vectors]


def predict(matrices: list[np.ndarray], reasons: list[str], order: list[str], threshold: float) -> list[str]:
    return [common.main_reason(common.found_reasons(m, reasons, threshold), order) for m in matrices]


def tune_threshold(matrices, company: str, grid: list[float]) -> tuple[float, dict]:
    """Best macro-F1 over the grid; ties -> the middle threshold of the tied ones."""
    reasons, order, true = company_info(company)
    rows = [(t, common.intake_measures(true, predict(matrices, reasons, order, t), reasons, common.MONEY[company]))
            for t in grid]
    best = max(r[1]["macro_f1"] for r in rows)
    tied = [r for r in rows if r[1]["macro_f1"] == best]
    return tied[len(tied) // 2]


def intake_model(key: str, emb: dict, grid=common.THRESHOLDS) -> dict:
    """Tune top-k + thresholds for one model; also return the curve of the best setting per top-k."""
    per_k = {}
    for k in common.TOP_KS:
        per_company = {}
        for company in common.COMPANIES:
            data = emb["intake"][company]
            matrices = score_matrices(data["index"], [m["vectors"] for m in data["messages"]], k)
            t, measures = tune_threshold(matrices, company, grid)
            per_company[company] = {"threshold": t, **measures}
        per_k[k] = {"avg_macro_f1": round(np.mean([per_company[c]["macro_f1"] for c in common.COMPANIES]), 4),
                    "avg_accuracy": round(np.mean([per_company[c]["accuracy"] for c in common.COMPANIES]), 4),
                    "companies": per_company}
    best_k = max(common.TOP_KS, key=lambda k: (per_k[k]["avg_macro_f1"], per_k[k]["avg_accuracy"], -k))
    return {"model": key, "top_k": best_k, **per_k[best_k],
            "by_top_k": {k: {"avg_macro_f1": v["avg_macro_f1"],
                             "thresholds": {c: v["companies"][c]["threshold"] for c in common.COMPANIES}}
                         for k, v in per_k.items()}}


def intake_fixed(emb: dict, top_k: int, thresholds: dict) -> dict:
    """Score one fixed setting (today's)."""
    per_company = {}
    for company in common.COMPANIES:
        reasons, order, true = company_info(company)
        data = emb["intake"][company]
        matrices = score_matrices(data["index"], [m["vectors"] for m in data["messages"]], top_k)
        pred = predict(matrices, reasons, order, thresholds[company])
        per_company[company] = {"threshold": thresholds[company],
                                **common.intake_measures(true, pred, reasons, common.MONEY[company])}
    return {"top_k": top_k, "avg_macro_f1": round(np.mean([per_company[c]["macro_f1"] for c in per_company]), 4),
            "avg_accuracy": round(np.mean([per_company[c]["accuracy"] for c in per_company]), 4),
            "companies": per_company}


def tfidf_embeddings() -> tuple[dict, list[float]]:
    """The same structure as a model's saved vectors, with TF-IDF vectors (fitted on each company's examples)."""
    emb, timings = {"intake": {}}, []
    for company in common.COMPANIES:
        examples = common.reason_examples(company)
        vectorizer = common.TfIdf([t for texts in examples.values() for t in texts])
        index = {r: vectorizer.vectors(texts) for r, texts in examples.items()}
        messages = []
        for m in common.intake_val(company):
            start = time.perf_counter()
            sentences = common.split_sentences(m["text"])
            vectors = vectorizer.vectors(sentences)
            common.found_reasons(common.sentence_scores(vectors, index, 3), list(examples), 0.3)
            timings.append(time.perf_counter() - start)
            messages.append({"vectors": vectors})
        emb["intake"][company] = {"index": index, "messages": messages}
    return emb, timings


def majority_baseline() -> dict:
    per_company = {}
    for company in common.COMPANIES:
        reasons, _, true = company_info(company)
        most = max(set(true), key=true.count)
        per_company[company] = {"always": most, **common.intake_measures(true, [most] * len(true), reasons,
                                                                         common.MONEY[company])}
    return {"avg_macro_f1": round(np.mean([per_company[c]["macro_f1"] for c in per_company]), 4),
            "avg_accuracy": round(np.mean([per_company[c]["accuracy"] for c in per_company]), 4),
            "companies": per_company}


# ================================================================ Rule search

def rag_methods(models: dict[str, dict], reranker: dict | None) -> dict:
    """Rankings (rule ids, best first), top score and per-question latency of every method on every question."""
    questions = common.rag_val()
    rules = {c: [r["id"] for r in common.rules(c)] for c in common.COMPANIES}
    bm25 = {c: common.BM25(common.rule_texts(c)) for c in common.COMPANIES}

    out = {}
    # BM25 (baseline), timed here.
    bm25_rank, bm25_s = [], []
    for q in questions:
        start = time.perf_counter()
        s = bm25[q["company"]].scores(q["question"])
        order = list(np.argsort(-s, kind="stable"))
        bm25_s.append(time.perf_counter() - start)
        bm25_rank.append((order, [float(s[i]) for i in order]))
    out["bm25"] = {"rank": bm25_rank, "latency_s": bm25_s, "parts": 0, "params_m": 0}

    for key, emb in models.items():
        m = meta(key)
        dense_s = m["rag_dense_latency_s_each"]
        spec = common.MODELS[key]
        variants = ["plain"] if not spec["query_prompt"] and not spec["doc_prompt"] else ["plain", "prompt"]
        for variant in variants:
            label = f"{key}" if variant == "plain" else f"{key}+prompt"
            dense_rank = []
            for i, q in enumerate(questions):
                s = emb["rag"][q["company"]][f"rules_{variant}"] @ emb["rag"][f"questions_{variant}"][i]
                order = list(np.argsort(-s, kind="stable"))
                dense_rank.append((order, [float(s[j]) for j in order]))
            out[f"dense {label}"] = {"rank": dense_rank, "latency_s": dense_s, "parts": 1,
                                     "params_m": m["parameters_m"]}

            hybrid_rank, hybrid_s = [], []
            for i in range(len(questions)):
                start = time.perf_counter()
                fused = common.rrf([dense_rank[i][0], bm25_rank[i][0]])
                fuse_s = time.perf_counter() - start
                d_pos = {d: r for r, d in enumerate(dense_rank[i][0], 1)}
                b_pos = {d: r for r, d in enumerate(bm25_rank[i][0], 1)}
                hybrid_rank.append((fused, [1 / (60 + d_pos[d]) + 1 / (60 + b_pos[d]) for d in fused]))
                hybrid_s.append(dense_s[i] + bm25_s[i] + fuse_s)
            out[f"hybrid {label}"] = {"rank": hybrid_rank, "latency_s": hybrid_s, "parts": 2,
                                      "params_m": m["parameters_m"]}

            if reranker:
                r_meta = meta("reranker")
                rr_rank, rr_s = [], []
                for i in range(len(questions)):
                    top10, rest = hybrid_rank[i][0][:10], hybrid_rank[i][0][10:]
                    scores = reranker["scores"][i]
                    reordered = sorted(top10, key=lambda d: -scores[d])
                    rr_rank.append((reordered + rest, [scores[d] for d in reordered] + [float("nan")] * len(rest)))
                    rr_s.append(hybrid_s[i] + r_meta["rerank_latency_s_each"][i])
                out[f"hybrid+rerank {label}"] = {"rank": rr_rank, "latency_s": rr_s, "parts": 3,
                                                 "params_m": m["parameters_m"] + r_meta["parameters_m"]}

    # Turn indexes into rule ids, then measure.
    results = {}
    for name, method in out.items():
        rankings = [[rules[q["company"]][j] for j in order] for q, (order, _) in zip(questions, method["rank"])]
        top_scores = [scores[0] for _, scores in method["rank"]]
        results[name] = measure_rag(questions, rankings, top_scores)
        results[name].update({"latency_ms": {"p50": common.percentile_ms(method["latency_s"], 50),
                                             "p95": common.percentile_ms(method["latency_s"], 95)},
                              "parts": method["parts"], "params_m": method["params_m"]})
    return results


def measure_rag(questions: list[dict], rankings: list[list[str]], top_scores: list[float]) -> dict:
    scored = [i for i, q in enumerate(questions) if q["expected"]]
    res = {"all": common.rank_measures([rankings[i] for i in scored], [questions[i]["expected"] for i in scored])}
    for c in common.COMPANIES:
        idx = [i for i in scored if questions[i]["company"] == c]
        res[c] = common.rank_measures([rankings[i] for i in idx], [questions[i]["expected"] for i in idx])
    # No-rule questions (report only): their top score vs the lowest top score of a correct top-1 hit (same company).
    no_rule = []
    for i, q in enumerate(questions):
        if q["expected"]:
            continue
        hits = [top_scores[j] for j in scored if questions[j]["company"] == q["company"]
                and rankings[j][0] in questions[j]["expected"]]
        lowest = min(hits) if hits else float("nan")
        no_rule.append({"id": q["id"], "top": rankings[i][0], "top_score": round(top_scores[i], 4),
                        "lowest_correct_hit": round(lowest, 4), "gap": round(lowest - top_scores[i], 4)})
    res["no_rule"] = no_rule
    res["no_rule_separable"] = sum(n["gap"] > 0 for n in no_rule)
    res["misses"] = [{"id": questions[i]["id"], "expected": questions[i]["expected"], "top2": rankings[i][:2]}
                     for i in scored if not any(r in questions[i]["expected"] for r in rankings[i][:2])]
    return res


# ================================================================ choose (rule fixed in advance, item 9)

def choose_intake(rows: dict) -> dict:
    eligible = {k: r for k, r in rows.items() if r["p95_ms"] <= 100 and r["peak_rss_mb"] <= 1500}
    best = max(r["avg_macro_f1"] for r in eligible.values())
    tied = [k for k, r in eligible.items() if best - r["avg_macro_f1"] <= 0.01]
    winner = min(tied, key=lambda k: rows[k]["parameters_m"])
    return {"winner": winner, "best_macro_f1": best, "tied_within_0.01": tied,
            "eligible": sorted(eligible), "not_eligible": sorted(set(rows) - set(eligible))}


def choose_rag(results: dict) -> dict:
    eligible = {k: r for k, r in results.items() if r["latency_ms"]["p95"] <= 200}
    key = lambda k: (eligible[k]["all"]["top2"], eligible[k]["all"]["mrr"])
    best = max(key(k) for k in eligible)
    tied = [k for k in eligible if key(k) == best]
    winner = min(tied, key=lambda k: (eligible[k]["parts"], eligible[k]["params_m"]))   # simplest, then smallest
    return {"winner": winner, "best_top2_mrr": best, "tied": tied, "eligible": sorted(eligible),
            "not_eligible": sorted(set(results) - set(eligible))}


# ================================================================ main

def main() -> None:
    models = {k: e for k in common.MODELS if (e := load(k)) is not None}
    skipped = {k: (meta(k) or {}).get("skipped", "not run") for k in common.MODELS if k not in models}

    intake_rows = {}
    for key, emb in models.items():
        m = meta(key)
        row = intake_model(key, emb)
        row.update({"p50_ms": m["intake_latency_ms"]["p50"], "p95_ms": m["intake_latency_ms"]["p95"],
                    "peak_rss_mb": m["peak_rss_mb"], "rss_before_model_mb": m["rss_before_model_mb"],
                    "parameters_m": m["parameters_m"], "disk_mb": m["disk_mb"], "licence": m["licence"]})
        intake_rows[key] = row
    today = intake_fixed(models[common.TODAY["model"]], common.TODAY["top_k"], common.TODAY["thresholds"])
    tfidf_emb, tfidf_s = tfidf_embeddings()
    tfidf = intake_model("tfidf", tfidf_emb, TFIDF_THRESHOLDS)
    tfidf.update({"p50_ms": common.percentile_ms(tfidf_s, 50), "p95_ms": common.percentile_ms(tfidf_s, 95)})
    baselines = {"tfidf": tfidf, "majority": majority_baseline()}

    reranker = load("reranker")
    rag = rag_methods(models, reranker)

    choice = {"intake": choose_intake(intake_rows), "rag": choose_rag(rag)}
    w = choice["intake"]["winner"]
    choice["intake"]["settings"] = {"model": w, "name": common.MODELS[w]["name"],
                                    "revision": common.MODELS[w]["revision"], "top_k": intake_rows[w]["top_k"],
                                    "thresholds": {c: intake_rows[w]["companies"][c]["threshold"]
                                                   for c in common.COMPANIES}}
    choice["rag"]["settings"] = {"method": choice["rag"]["winner"]}

    common.RESULTS.mkdir(parents=True, exist_ok=True)
    dump("intake_val.json", {"models": intake_rows, "today": today, "baselines": baselines, "skipped": skipped})
    dump("rag_val.json", {"methods": rag, "skipped": skipped})
    dump("choice.json", choice)
    print_tables(intake_rows, today, baselines, rag, choice, skipped)


def dump(name: str, data: dict) -> None:
    (common.RESULTS / name).write_text(json.dumps(data, indent=1, default=float) + "\n", encoding="utf-8")


def print_tables(intake_rows, today, baselines, rag, choice, skipped) -> None:
    print("\nINTAKE (val)  model | top-k | thr S/A | macroF1 S/A/avg | acc S/A | critical S/A | needsLLM S/A | p50/p95 ms | peak RAM")
    def line(name, r):
        s, a = r["companies"]["shopnova"], r["companies"]["atlas"]
        print(f"{name:14s} k{r.get('top_k', '-')} {s.get('threshold', '-')}/{a.get('threshold', '-')} | "
              f"{s['macro_f1']:.3f}/{a['macro_f1']:.3f}/{r['avg_macro_f1']:.3f} | {s['accuracy']:.3f}/{a['accuracy']:.3f}"
              f" | {s['critical_errors']}/{a['critical_errors']} | {s['needs_llm_rate']:.3f}/{a['needs_llm_rate']:.3f}"
              f" | {r.get('p50_ms', '-')}/{r.get('p95_ms', '-')} | {r.get('peak_rss_mb', '-')}")
    for k, r in intake_rows.items():
        line(k, r)
    line("TODAY", today)
    for k, r in baselines.items():
        line(k, r)
    print("skipped:", skipped)
    print("\nRULE SEARCH (val)  method | top1 all | top2 all | MRR | top2 S/A | p50/p95 ms | no-rule separable")
    for k, r in sorted(rag.items(), key=lambda x: (-x[1]["all"]["top2"], -x[1]["all"]["mrr"])):
        print(f"{k:32s} {r['all']['top1']:.3f} | {r['all']['top2']:.3f} | {r['all']['mrr']:.3f} | "
              f"{r['shopnova']['top2_count']}/{r['shopnova']['n']} {r['atlas']['top2_count']}/{r['atlas']['n']} | "
              f"{r['latency_ms']['p50']}/{r['latency_ms']['p95']} | {r['no_rule_separable']}/5")
    print("\nCHOICE:", json.dumps(choice, indent=1))


if __name__ == "__main__":
    main()
