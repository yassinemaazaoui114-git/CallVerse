"""T23: offline tests of the M3 benchmark code (no model download, no ABCD file, no locked test file)."""

import hashlib

import numpy as np

from benchmarks.m3 import build_data, common
from callverse.intake import reasons


# ---------------------------------------------------------------- the matcher reproduces reasons.py

def fake_embed(texts: list[str]) -> np.ndarray:
    """A deterministic stand-in for M3: words hashed into 64 dimensions, length 1."""
    out = np.zeros((len(texts), 64))
    for row, text in enumerate(texts):
        for word in common.tokens(text) or ["empty"]:
            out[row, int(hashlib.md5(word.encode()).hexdigest(), 16) % 64] += 1
    return out / np.linalg.norm(out, axis=1, keepdims=True)


def test_matcher_reproduces_reasons_py_on_the_system_settings(monkeypatch):
    examples = common.reason_examples("shopnova")
    vectors = {r: fake_embed(t) for r, t in examples.items()}
    monkeypatch.setattr(reasons, "embed", fake_embed)
    monkeypatch.setattr(reasons, "example_vectors", lambda company="shopnova": vectors)
    names = list(examples)
    messages = ["Where is my order? It was due last week.", "I want my money back. The box arrived crushed.",
                "Hi!", "My parcel never came and I want a refund", "Do you sell gift cards?"]
    for threshold in (0.2, 0.35, 0.5, 0.66):
        for text in messages:
            system = [r["reason"] for r in reasons.match_reasons(text, threshold=threshold)["reasons"]]
            scores = common.sentence_scores(fake_embed(common.split_sentences(text)), vectors, 3)  # top_k 3
            assert common.found_reasons(scores, names, threshold) == system


def test_main_reason_follows_the_precedence_order():
    order = ["damaged_item", "refund_request", "late_delivery", "other"]
    assert common.main_reason(["late_delivery", "refund_request"], order) == "refund_request"
    assert common.main_reason([], order) == common.NEEDS_LLM


# ---------------------------------------------------------------- measures on toy examples

def test_intake_measures_toy():
    true = ["a", "a", "b", "m"]
    pred = ["a", "b", "b", common.NEEDS_LLM]
    m = common.intake_measures(true, pred, ["a", "b", "m"], money={"m", "b"})
    assert m["accuracy"] == 0.5
    # a: P 1, R 0.5, F1 2/3; b: P 0.5, R 1, F1 2/3; m: 0 (needs_llm is a miss) -> macro (2/3 + 2/3 + 0) / 3
    assert abs(m["macro_f1"] - 4 / 9) < 1e-3
    assert m["critical_errors"] == 1            # a (not money) predicted as b (money); needs_llm is not critical
    assert m["needs_llm_rate"] == 0.25


def test_rank_measures_and_rrf_and_bm25():
    m = common.rank_measures([["x", "y", "z"], ["y", "x", "z"], ["z", "y", "x"]], [["x"], ["x"], ["x"]])
    assert (m["top1_count"], m["top2_count"]) == (1, 2)
    assert abs(m["mrr"] - (1 + 1 / 2 + 1 / 3) / 3) < 1e-3
    # 0 and 2: 1/61 + 1/63 (tie, broken by the first ranking); 1: 2/62, a little lower
    assert common.rrf([[0, 1, 2], [2, 1, 0]]) == [0, 2, 1]
    assert common.rrf([[0, 1], [0, 1]]) == [0, 1]
    bm25 = common.BM25(["refund for a late order", "damaged item photo", "delivery date promise"])
    assert int(np.argmax(bm25.scores("my item arrived damaged"))) == 1


# ---------------------------------------------------------------- the data builder follows the mapping

def chat(convo_id, subflow, turns):
    return {"convo_id": convo_id, "scenario": {"subflow": subflow}, "original": turns}


def test_build_data_follows_the_mapping_on_a_fake_abcd():
    mapping = {"_note": "x", "refund_request": ["refund_initiate"], "damaged_item": ["return_stain"],
               "other": "every other subflow", "other_cap_per_split": 2, "seed": 2026}
    chats = [
        chat(1, "refund_initiate", [["agent", "Hello"], ["customer", "hi"], ["customer", "I want my money back now"]]),
        chat(2, "return_stain", [["customer", "There is a stain on my shirt"]]),
        chat(3, "reset_2fa", [["customer", "hi there"]]),                       # no turn with >= 4 words: dropped
        chat(4, "reset_2fa", [["customer", "I cannot log in at all"]]),
        chat(5, "cost", [["customer", "how much does this jacket cost"]]),
        chat(6, "slow_speed", [["customer", "your website is very slow today"]]),
    ]
    rows = build_data.build(chats, mapping)
    by_id = {r["id"]: r for r in rows}
    assert by_id["abcd-1"]["text"] == "I want my money back now"        # the first customer turn with 4+ words
    assert by_id["abcd-1"]["reason"] == "refund_request"
    assert by_id["abcd-2"]["reason"] == "damaged_item"
    assert "abcd-3" not in by_id
    others = [r for r in rows if r["reason"] == "other"]
    assert len(others) == 2                                             # "other" capped (3 -> 2)
    assert rows == build_data.build(chats, mapping)                     # same seed, same sample
