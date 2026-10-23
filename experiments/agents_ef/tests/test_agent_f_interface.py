"""Agent F interface: a vocabulary-trimmed multilingual checkpoint reloads and predicts the same scores (EN + FR)."""

import json

import pytest
import torch

pytest.importorskip("transformers")


def test_trimmed_checkpoint_round_trip(tmp_path):
    from transformers import AutoModel, AutoTokenizer
    from integration.agent_f_predictor import SatisfactionPredictor
    from real_data.eval_f_v2 import ENC, Reg, build_remap, trim_model
    name = ENC["e5small"]
    try:
        tok, bert = AutoTokenizer.from_pretrained(name), AutoModel.from_pretrained(name)
    except Exception:
        pytest.skip("model not cached (offline)")
    texts = ["query: The parcel never arrived, terrible.", "query: Très bon produit, livraison rapide, merci !"]
    kept, remap = build_remap(tok, texts + ["query: some other words for the vocabulary"])
    model = Reg(trim_model(bert, kept), remap).eval()
    assert model.bert.config.vocab_size == len(kept) < 1000
    torch.save(model.state_dict(), tmp_path / "model.pt")
    (tmp_path / "meta.json").write_text(json.dumps({"base_model": name, "prefix": "query: ", "max_length": 128}))
    f = SatisfactionPredictor.load(tmp_path)
    got = f.predict([t[len("query: "):] for t in texts])
    with torch.no_grad():
        b = tok(texts, padding=True, return_tensors="pt")
        ref = model(b["input_ids"], b["attention_mask"]).numpy()
    for g, r in zip(got, ref):
        assert g["score"] == pytest.approx(min(max(float(r), 1), 5), abs=1e-3)
        assert g["label"] in ("unhappy", "neutral", "happy")


def _tiny_subset(tmp_path):
    texts = [("Great product, fast delivery", 5, "en"), ("Never arrived, terrible", 1, "en"),
             ("Produit correct sans plus", 3, "fr"), ("Très déçu, colis abîmé", 1, "fr"),
             ("Parfait, merci beaucoup", 5, "fr"), ("It is ok I guess", 3, "en")]
    for split, n in (("train", 12), ("val", 6), ("test", 6)):
        with open(tmp_path / f"{split}.jsonl", "w", encoding="utf-8") as f:
            for i in range(n):
                t, r, lg = texts[i % len(texts)]
                f.write(json.dumps({"id": f"{split}{i}", "text": f"{t} {i}", "rating": float(r), "lang": lg}) + "\n")
    (tmp_path / "corpus.jsonl").write_text("\n".join(json.dumps({"text": t}) for t, _, _ in texts), encoding="utf-8")


def test_training_is_deterministic_on_cpu(tmp_path):
    """Same seed, same data, same threads -> bit-identical weights (what makes the checkpoint reproducible)."""
    import argparse
    import hashlib
    from real_data.eval_f_v2 import load, run_ft
    try:
        from transformers import AutoTokenizer
        AutoTokenizer.from_pretrained("intfloat/multilingual-e5-small")
    except Exception:
        pytest.skip("model not cached (offline)")
    _tiny_subset(tmp_path)
    torch.set_num_threads(1)
    a = argparse.Namespace(epochs=1, lr=4e-5, vocab_corpus=[str(tmp_path / "corpus.jsonl")], device="cpu",
                           fp16=False, save_dir=None)
    tr, va, te = (load(tmp_path, s) for s in ("train", "val", "test"))
    hashes = []
    for _ in range(2):
        predict, info = run_ft("e5small_trim_ft", 0, tr, va, te, a)
        hashes.append(hashlib.sha256(predict(te).tobytes()).hexdigest())
    assert hashes[0] == hashes[1]


def test_pipeline_refuses_a_work_folder_inside_the_repository():
    from pipelines.agent_f_pipeline import HERE, main
    with pytest.raises(SystemExit):
        main(["--work", str(HERE / "results" / "should_not_exist")])
