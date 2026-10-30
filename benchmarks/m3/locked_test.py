"""Step 7 of T23: run the two WINNERS once on the LOCKED test sets. Nothing is tuned or changed after this.

    python -m benchmarks.m3.locked_test

Reads the winners and their settings from benchmarks/m3/results/choice.json (chosen on validation only):
  - Intake winner (model, top-k, thresholds) on ShopNova's ABCD "test" split (built here, into git-ignored out/)
    and on tests/data/atlas_intake_test.json;
  - rule-search winner (method) on tests/data/rag_test.json.
Writes benchmarks/m3/results/locked_test.json. It refuses to run a second time (the test is used ONCE).
"""

import json
import sys

import numpy as np

from benchmarks.m3 import build_data, common
from callverse import companies

OUT = common.RESULTS / "locked_test.json"
ATLAS_TEST = common.ROOT / "tests" / "data" / "atlas_intake_test.json"
RAG_TEST = common.ROOT / "tests" / "data" / "rag_test.json"


def load_model(key: str):
    from sentence_transformers import SentenceTransformer
    spec = common.MODELS[key]
    return SentenceTransformer(spec["name"], revision=spec["revision"], device="cpu")


def encode(model, texts, prompt=""):
    return model.encode(texts, prompt=prompt or None, normalize_embeddings=True, convert_to_numpy=True,
                        show_progress_bar=False)


def intake(settings: dict) -> dict:
    # ShopNova's locked test from ABCD "test", with the same builder and mapping as val.
    mapping = common.load_json(build_data.MAPPING_PATH)
    rows = build_data.build(common.load_json(build_data.ABCD_PATH)["test"], mapping)
    build_data.TEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    build_data.TEST_PATH.write_text(json.dumps({"messages": rows}, indent=1, ensure_ascii=False), encoding="utf-8")
    test_sets = {"shopnova": rows, "atlas": common.load_json(ATLAS_TEST)["messages"]}

    model = load_model(settings["model"])
    out = {}
    for company in common.COMPANIES:
        cfg = companies.get(company)
        examples = common.reason_examples(company)
        index = {r: encode(model, texts) for r, texts in examples.items()}
        true, pred = [], []
        for m in test_sets[company]:
            scores = common.sentence_scores(encode(model, common.split_sentences(m["text"])), index,
                                            settings["top_k"])
            found = common.found_reasons(scores, cfg["reasons"], settings["thresholds"][company])
            true.append(m["reason"])
            pred.append(common.main_reason(found, cfg["main_reason_order"]))
        out[company] = common.intake_measures(true, pred, cfg["reasons"], common.MONEY[company])
        out[company]["counts"] = {r: true.count(r) for r in cfg["reasons"]}
    out["avg_macro_f1"] = round(np.mean([out[c]["macro_f1"] for c in common.COMPANIES]), 4)
    return out


def rag(method: str) -> dict:
    """Run one method ("bm25", "dense <model>[+prompt]", "hybrid ...", "hybrid+rerank ...") on the locked questions."""
    questions = common.load_json(RAG_TEST)["questions"]
    kind, _, label = method.partition(" ")
    key, prompted = label.replace("+prompt", ""), label.endswith("+prompt")
    model = load_model(key) if kind != "bm25" else None
    spec = common.MODELS.get(key, {})
    reranker = None
    if kind == "hybrid+rerank":
        from sentence_transformers import CrossEncoder
        reranker = CrossEncoder(common.RERANKER["name"], revision=common.RERANKER["revision"], device="cpu")

    rankings, top_scores = [], []
    for q in questions:
        rules = common.rules(q["company"])
        texts = common.rule_texts(q["company"])
        b = common.BM25(texts).scores(q["question"])
        bm25_order = list(np.argsort(-b, kind="stable"))
        if kind == "bm25":
            order, scores = bm25_order, [float(b[i]) for i in bm25_order]
        else:
            rule_vectors = encode(model, texts, spec["doc_prompt"] if prompted else "")
            s = rule_vectors @ encode(model, [q["question"]], spec["query_prompt"] if prompted else "")[0]
            dense_order = list(np.argsort(-s, kind="stable"))
            order, scores = dense_order, [float(s[i]) for i in dense_order]
            if kind in ("hybrid", "hybrid+rerank"):
                order = common.rrf([dense_order, bm25_order])
                d_pos = {d: r for r, d in enumerate(dense_order, 1)}
                b_pos = {d: r for r, d in enumerate(bm25_order, 1)}
                scores = [1 / (60 + d_pos[d]) + 1 / (60 + b_pos[d]) for d in order]
            if kind == "hybrid+rerank":
                top10 = order[:10]
                r = reranker.predict([(q["question"], texts[i]) for i in top10], show_progress_bar=False)
                pairs = sorted(zip(top10, r), key=lambda p: -p[1])
                order = [i for i, _ in pairs] + order[10:]
                scores = [float(v) for _, v in pairs]
        rankings.append([rules[i]["id"] for i in order])
        top_scores.append(scores[0])

    from benchmarks.m3.benchmark import measure_rag
    return measure_rag(questions, rankings, top_scores)


def main() -> None:
    if OUT.exists():
        sys.exit(f"{OUT.relative_to(common.ROOT)} exists: the locked test was already run once. Not running again.")
    choice = common.load_json(common.RESULTS / "choice.json")
    result = {"intake_settings": choice["intake"]["settings"], "intake": intake(choice["intake"]["settings"]),
              "rag_method": choice["rag"]["settings"]["method"], "rag": rag(choice["rag"]["settings"]["method"])}
    OUT.write_text(json.dumps(result, indent=1, default=float) + "\n", encoding="utf-8")
    i, r = result["intake"], result["rag"]
    print(f"Intake {choice['intake']['settings']}: macro-F1 S {i['shopnova']['macro_f1']} "
          f"A {i['atlas']['macro_f1']} avg {i['avg_macro_f1']}; accuracy S {i['shopnova']['accuracy']} "
          f"A {i['atlas']['accuracy']}; critical S {i['shopnova']['critical_errors']} A {i['atlas']['critical_errors']}")
    print(f"Rule search {result['rag_method']}: top1 {r['all']['top1']} top2 {r['all']['top2']} MRR {r['all']['mrr']}"
          f" (n {r['all']['n']}); no-rule separable {r['no_rule_separable']}/{len(r['no_rule'])}")


if __name__ == "__main__":
    main()
